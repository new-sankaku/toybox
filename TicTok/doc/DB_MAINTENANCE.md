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
- `battles` 表が空の起動では退避しません（守る対象がありません）。
- 退避に失敗した場合はmigrationを走らせず**起動を中止**します。書き換えた行は戻せないため、
  「退避できなかったが先へ進む」は取り返しのつかない選択になります。容量を空けるか、
  `TICTOK_DB_BACKUP_DIR` を別volumeへ向けてから起動し直してください。

## 設定

| 環境変数 | 既定値 | 説明 |
| --- | --- | --- |
| `TICTOK_DB_BACKUP_DIR` | `TicTok/backups` | 退避先。別volumeへ向ければそのdiskの故障にも耐えます |
| `TICTOK_DB_BACKUP_KEEP` | `3` | 種別ごとの保持世代数。0で無制限 |
| `TICTOK_DB_BACKUP_MIN_FREE_RATIO` | `1.2` | 開始前に要求する空き容量（DB+WALに対する倍率） |
| `TICTOK_DB_BACKUP_BEFORE_MIGRATION` | `1` | 起動時の自動退避 |
| `TICTOK_DB_INTEGRITY_CHECK_MAX_ERRORS` | `20` | integrity_checkが報告する最大件数 |

保持世代を**種別ごと**に数えるのは意図的です。migration前の退避は「行が書き換わる前の唯一の
像」であり、共通の世代数にすると数回の手動退避で押し出されてしまいます。

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

## 記録

退避・健全性check・checkpoint・VACUUMは全て `ops_events` に残ります
（`maintenance.backup_completed` / `maintenance.integrity_checked` /
`maintenance.wal_checkpointed` / `maintenance.vacuumed`、失敗は `*_failed` でseverity=error）。
運用log画面の一覧にそのまま並びます。
