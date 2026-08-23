# Databaseの保守（退避・健全性check・VACUUM）

録画mp4は失っても録り直す導線がありますが、event・解析結果・設定・監視対象は `tictok.db`
にしかありません。この文書は、そのDBを守る仕組みと運用手順をまとめたものです。

## なぜfile copyではないのか

`tictok.db` はWAL modeで動いています。直近のcommitはDB本体ではなく `tictok.db-wal` に
入っているため、

- `tictok.db` だけをcopyすると、古い状態の像になります。
- `tictok.db` と `tictok.db-wal` を別々の瞬間にcopyすると、どちらか一方だけの像より
  さらに悪い（整合しない）ものになります。

実測でもこの差は明確です。稼働直後のserverでは DB本体 4KB / WAL 894KB という状態が
普通に発生し、この瞬間のfile copyはほぼ空のDBになります。

そのため退避はSQLiteの backup API（`sqlite3.Connection.backup`）だけで行います。
read transactionを通してWAL込みで読むため、**serverを止めずに** その瞬間として整合の取れた
1本のfileが得られます。

## 実装

| 場所 | 役割 |
| --- | --- |
| `tictok/core/dbmaint.py` | 退避fileの作成・世代管理・file単位のintegrity check |
| `tictok/storage.py` | live接続でしか正しく行えない操作（WAL checkpoint / VACUUM）と起動時hook |
| `tictok/server.py` | `/api/maintenance/*` |
| `static/ops.html` / `static/ops.js` | 運用log画面上部の「Databaseの保守」panel |

退避fileは `.partial` という名前で書き、`PRAGMA integrity_check` を通してから最終名へ
renameします。したがって**最終名で存在するfileは必ず「読めることを確認済み」**です。
検証に落ちたfileは削除され、後から復元に使われることはありません。

退避fileの名前は `tictok-<種別>-<YYYYmmdd-HHMMSS>.db` です（同一秒に複数取ると `-2` などの
連番が付きます）。

## 起動時の自動退避

`tictok/glove_migration.py`（グローブcritの再判定）と `tictok/battle_migration.py`
（battle形式の再判定）は `battles.data_json` をin-placeで書き換えます。元の値はどこにも
残りません。そこで `Storage.__init__` は、この2つを走らせる直前に退避を取ります。

- 判定はmigration側の選択条件を写さず、`db_maintenance` 表のmarker
  （`premigration_backup_versions` = `glove=N,topo=M`）で行います。migrationのSQLを
  複製すると、片方だけ直したときに黙って退避されなくなるためです。
- markerはmigrationが**完走した後**に書きます。途中で落ちた起動は、次回もう一度退避を
  取り直してからやり直します。
- `battles` `transcripts` `cut_list` `events` のどれにも行が無い起動では退避しません
  （守る対象がありません）。**`events` を見ているのは、重複文字列のinternが
  `events` 表の列そのものを落とすためです** — これが無いと、`battles` と `transcripts`
  が空でeventsだけ在るDBが、退避を取らないまま旧列を落とすことになります。
- 退避に失敗した場合はmigrationを走らせず**起動を中止**します。書き換えた行は戻せないため、
  「退避できなかったが先へ進む」は取り返しのつかない選択になります。容量を空けるか、
  `TICTOK_DB_BACKUP_DIR` を別volumeへ向けてから起動し直してください。

`events` の重複文字列を別表の整数idへ畳む仕組み（`event_strings`）は
[DB_INTERN.md](DB_INTERN.md) にあります。**旧列を落とす破壊的なmigrationで、
VACUUMするまでDB fileはむしろ大きくなります**（実測 1,767.6MB -> 2,042.4MB ->
VACUUM後1,262.6MB）。

## 設定

| 環境変数 | 既定値 | 説明 |
| --- | --- | --- |
| `TICTOK_DB_BACKUP_DIR` | `TicTok/backups` | 退避先。別volumeへ向ければそのdiskの故障にも耐えます |
| `TICTOK_DB_BACKUP_KEEP` | `3` | 種別ごとの保持世代数。0で無制限 |
| `TICTOK_DB_BACKUP_MIN_FREE_RATIO` | `1.2` | 開始前に要求する空き容量（DB+WALに対する倍率） |
| `TICTOK_DB_BACKUP_BEFORE_MIGRATION` | `1` | 起動時の自動退避 |
| `TICTOK_DB_INTEGRITY_CHECK_MAX_ERRORS` | `20` | integrity_checkが報告する最大件数 |
| `TICTOK_DB_ANALYZE_ENABLED` | `1` | 起動時のplanner統計。0で止めます（止めると誤選択が戻ります） |
| `TICTOK_DB_ANALYZE_GROWTH_RATIO` | `0.20` | 前回ANALYZE時点からのeventsの伸びが この割合を超えたら採り直します |

保持世代を**種別ごと**に数えるのは意図的です。migration前の退避は「行が書き換わる前の唯一の
像」であり、共通の世代数にすると数回の手動退避で押し出されてしまいます。

## plannerの統計（ANALYZE）

SQLiteは統計（`sqlite_stat1`）が無いと、全てのindexを同じ経験則で見積もります。この
databaseには長らく統計が無く、`ANALYZE` を呼ぶcodeも1箇所もありませんでした。

実害は明確でした。Battleの貢献集計（`battles.battle_gift_contributions`）が経験則で
`idx_events_kind_identity` を選び、**Battle 1件ごとにgift event 30,766件を全部舐めて**
いました。正しいのは `idx_events_session_kind_time` で、そのsessionの数十件だけを見ます。

| | 934 battleのloop |
| --- | ---: |
| 統計なし | 2,066ms |
| 全数ANALYZE後 | **154ms** |

返る行は完全に一致します。速くなっただけで、結果は変わりません。遅くなったqueryは1本も
ありませんでした。

### 全数でないと効きません

`analysis_limit` で刻むと速く終わりますが、**planは変わりません**。

| | 所要 | 934 battleのloop | 選ばれたindex |
| --- | ---: | ---: | --- |
| 統計なし | — | 1,926ms | `idx_events_kind_identity` |
| `analysis_limit=400` + `PRAGMA optimize` | 1ms | 1,929ms | 変わらず（stat1が0行のまま） |
| `analysis_limit=1000` + `ANALYZE` | 115ms | 2,193ms | **変わらず**（sampleが足りない） |
| `analysis_limit=0` + `ANALYZE` | 1,586ms | **272ms** | `idx_events_session_kind_time` |

速いが効かない統計は、無い統計より悪いものです。「ANALYZE済み」というmarkerだけが残り、
次に調べる人が統計を容疑から外してしまいます。

### いつ走るか

`Storage.__init__` の中、**writer threadを起こす前**の1点だけです（`storage.py`）。ANALYZE
は書き込みで、実測2.3秒のあいだwrite lockを保持します。収集中に走らせるとcollectorのdrain
がその秒数だけ止まるため、まだ誰もこの接続を待っていない起動時の窓に限っています。

毎起動では走りません。起動は実測1.65秒で、2.3秒を無条件に足すと倍以上になります。判定は
`ensure_planner_stats`（`store/maintenance.py`）が持ちます。

| 条件 | 動き |
| --- | --- |
| `sqlite_stat1` が無い | 伸びに関わらず**必ず**採る。無い状態は「古い」ではなく「plannerが誤選択する」状態 |
| 前回から `TICTOK_DB_ANALYZE_GROWTH_RATIO` 以上伸びた | 採り直す |
| それ未満 | 何もしない（`skipped: fresh`） |

伸びは `MAX(rowid)` で測ります。`COUNT(*)` は120万行のindexを毎起動で頭から舐めますが、
ここで欲しいのは一桁の精度だけで、rowidはB-treeの右端1回で済みます。session削除でrowidが
飛んだ場合は過大評価になり、ANALYZEが早めに走る安全側へ倒れます。

失敗は握り潰しません。ここで落ちるのはdisk full / I-O / 破損の類で、どのみち数秒後にwriter
が同じ壁に当たります。統計が採れないまま黙って起動すると、遅さの原因が「統計が無い」ことだと
誰も辿れなくなります。

## 画面からの操作（運用log画面）

| button | 内容 | 収集への影響 |
| --- | --- | --- |
| 今すぐ退避 | 1世代取得し、検証してから確定 | なし（backup APIで読むだけ） |
| 健全性check | `PRAGMA integrity_check` | なし（別接続で読むだけ） |
| WAL checkpoint | WALをDB本体へ書き戻しWAL fileを切り詰め | ごく短時間 |
| VACUUM | DB fileを作り直して空き領域を回収 | **大**。実行中は全ての書き込みが待たされます |

VACUUMは手動・明示confirmのみです（APIも `{"confirm": true}` が必須）。自動実行の経路は
用意していません。WAL modeではVACUUMの結果は一旦WALへ書かれDB fileは縮まないため、
`Storage.vacuum` はVACUUMの直後にcheckpointまで行ってから回収量を測ります。

WAL checkpointの応答に含まれる `busy` はSQLiteの生の値です。`1` は「読み取り中の処理が
あり全部は書き戻せなかった」という意味で、成功には丸めません。

## 復元の手順

1. serverを停止します（単一instance lockがあるため、起動したままの差し替えはできません）。
2. `tictok.db` / `tictok.db-wal` / `tictok.db-shm` を退避（別名で残す）します。
3. 目的の世代の退避fileを `tictok.db` としてcopyします。`-wal` / `-shm` は**copyしません**
   （退避fileは単体で完結しています）。
4. serverを起動します。

なお退避fileにはmarkerも含まれるため、退避時点より新しいmigration版のcodeで起動すれば、
その世代に対してもう一度退避を取った上でmigrationが走ります。

## 退避先はtestでも隔離すること

`TICTOK_DB_BACKUP_DIR` の既定は `PROJECT_ROOT/backups` で、**破壊的migrationの直前に取られる
唯一の原本**がそこに在ります。`tests/conftest.py` はこのenvもsandboxへ向けます。

向けていないと、testがStorageを作るたびに数百KBの退避が本番の `backups/` へ積まれ、保持世代
（`TICTOK_DB_BACKUP_KEEP` 既定3）の枠を埋めて本物を追い出します。実際に2026-08-23、intern
migrationの直前に取られた**1.85GBの退避が、その後のtest 1回の実行で消えました**（393KBの
test退避3つに押し出された）。退避が「取られていた」ことはlogに残るので、fileが無いことに
気づくのは戻したくなった時です。

種別ごとに世代を数える設計（`premigration` は手動退避と別枠）は、この事故を防ぎません。
test退避も `premigration` を名乗るからです。**分けるのはdirの方**です。

根本は `get_db_backup_dir()` の既定を **DBの隣**（`get_db_path()` の親）から導くことで
直しました。docstringは元から「Next to the DB by default」と言っていたのに、実装が
project root固定だったという食い違いです。本番では両者が同じdirなので**挙動は変わり
ません**。変わるのは、この codeが開く**他の**database — testのsandbox、検証用のcopy、
使い捨てのscript — の退避先で、それぞれ自分のDBの隣へ行きます。退避はそれが取られた
databaseに属するものです。

## 記録

退避・健全性check・checkpoint・VACUUMは全て `ops_events` に残ります
（`maintenance.backup_completed` / `maintenance.integrity_checked` /
`maintenance.wal_checkpointed` / `maintenance.vacuumed`、失敗は `*_failed` でseverity=error）。
plannerの統計はtext/JSONL logの `storage.planner_stats_analyzed` に残ります（採らなかった
起動は行が出ません）。
運用log画面の一覧にそのまま並びます。
