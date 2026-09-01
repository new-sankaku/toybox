# 保存先の二重化 — 対象の棚卸しと実装cost

「DBがmain SSDに集中していて、飛ぶと復旧できない」「録画の保存先も1か所」への回答です。
結論から言うと、**最大の穴は設定1行で今日塞げます**。本格的な二重化はそのあとです。

## 1. まず結論

| | 内容 | 実装 | 効果 |
|---|---|---|---|
| **今すぐ** | `TICTOK_DB_BACKUP_DIR` を別driveへ向ける | **0行** | DBの唯一の原本がSSDと道連れになるのを止める |
| Phase 1 | DB backupの定期実行 | 小 (0.5人日) | 手動と migration 直前しか取られない状態を直す |
| Phase 2 | DB backupを2か所へ | 小 (1〜2人日) | driveの故障に対してDBが生き残る |
| Phase 3 | 録画の複製(mirror) | **大 (8〜15人日)** | 録画原本がdrive 1台の故障で消えなくなる |
| Phase 4 | off-site(cloud等) | 中 (3〜5人日) | 火災・盗難・ransomware・誤操作 |

## 2. 何を守るのか — 棚卸し

**「DB / file / log」で数えると足りません。** 実際には次の13種類があります。
再取得可否が実装の優先順位を決めます。

| # | data | 既定の場所 | 再取得 | 失うと |
|---|---|---|---|---|
| 1 | `tictok.db` | DB path (main SSD) | **不可** | event・解析・設定・監視対象・文字起こし・fan台帳が全滅 |
| 2 | 録画素材 `.ts` | `record_dir` / `record_dir_final` | **不可** | 録画そのもの |
| 3 | `_backup/` 退避mp4 | 各rootの直下 | **条件付きで不可** | 下記(※1) |
| 4 | `.sidecars/*.timing.json` | mp4と同じroot | **実質不可** | 下記(※2) |
| 5 | pool `avatars/` `emotes/` `gift_icons/` | **work root固定** | **実質不可** | 下記(※3) |
| 6 | `backups/` (DB退避3世代) | **DBの隣 = 同じSSD** | — | 下記(※4) |
| 7 | `journal/` (耐久journal 14日) | project root | 不可 | DB commit前のeventが消える(※5) |
| 8 | mp4(素材が残る録画) | mp4 root | 再mp4化で可 | GPU時間だけ |
| 9 | 焼き込み `.overlay.mp4` / Up出力 `.up.mp4` | mp4 root | 再生成可 | GPU時間だけ(焼き込みは10.0秒/分) |
| 10 | `_clips/` `_screenshots/` | work root固定 | 再生成可(人の選択は戻らない) | 切り出し位置の判断 |
| 11 | `semantic_index.db` + `semantic_vectors.bin` | DBの隣 | 再構築可 | 埋め込みの再実行cost |
| 12 | `logs/` (text + JSONL) | project root | 不可 | 事後調査の材料 |
| 13 | `.env` / model weights | project root / 任意 | 書き直し・再DL可 | 手間だけ |

### ※1 `_backup/` は「派生物」ではありません

`doc/BACKUP_PRUNE.md` の実測(2026-07-25)では、2次rootの退避86件のうち **13件27.4GB が
削除保留**でした。内訳は現行mp4が無い5件・**現行mp4にvideo streamが無い2件**・
frame数が明らかに足りない5件・行が実fileを指していない1件です。

**作り直しが壊れた録画がこれだけ実在し、その原本は `_backup/` にしかありません。**
複製対象から一律に外すと、この13件を守れません。

### ※2 `timing.json` は作り直せますが、作り直すと文字起こしがズレます

`scripts/repair_timing_pts.py` で `.ts` から再生成はできます。しかし
`doc/TIME_AXIS.md` が「**文字起こしは引き直せない** — 古い軸から今の軸へ戻すmapは、
timing.jsonを作り直した時点で失われる」と記録しています。実測では331 groupのうち
134 groupが取り残され、中央値167秒・最大1,194秒(約20分)ずれました。

**`.sidecars/` を「派生物だから後回し」に分類すると、復元したDBの文字起こしが
動画とズレます。**復元できたように見えて中身が合わない、という一番たちの悪い壊れ方です。

### ※3 pool は work root にしか存在せず、CDN URLは期限切れします

`layout.py` の通り `avatars/` `emotes/` `gift_icons/` は **work root ただ1つ**に置かれ、
書くのは収集時のcollectorだけです。TikTok CDNのURLは期限切れするため、
後から取り直せません。焼き込み前の録画のavatar表示が失われます。

### ※4 backupがDBと同じdriveに在ります ← **最大の穴**

`get_db_backup_dir()` の既定は `get_db_path()` の親、つまり **`tictok.db` の隣**です。

```
tictok.db          <- 原本
tictok.db-wal
backups/           <- 3世代の退避。同じdrive
```

**このSSDが飛ぶと、DBと3世代の退避が同時に消えます。**しかも退避が取られていたことは
logに残るので、無いことに気づくのは戻したい時です。

同種の事故は既に起きています。`doc/DB_MAINTENANCE.md` の記録では、2026-08-23に
intern migration直前の **1.85GBの退避が、test 1回の実行で消えました**(393KBのtest退避3つに
押し出された)。これは別volume化とは別の話ですが、**「取れているつもり」が実際には
取れていなかった**実例です。

### ※5 journal は DB の backup ではありません

`get_journal_dir()` の docstring は "Kept next to the DB so the backup lives on the same
SSD as the data it protects" と明言しています。journal が守るのは
**writer が止まったときの event 列**であって、**DB file 自体ではありません**。
disk が飛べば journal も一緒に消えます。混同しないでください。

## 3. 3-2-1 に当てはめる

| 規則 | 現状 | Phase後 |
|---|---|---|
| コピーを**3**つ | 1つ(録画)〜2つ(DB本体+同じdriveのbackup) | 原本 + mirror + off-site |
| **2**種類の媒体 | SSD / HDD には既に分かれている | 維持 |
| **1**つを off-site | **無し** | Phase 4 |

**RAID1 は backup ではありません。**誤削除・retention の暴走・ransomware・DBの論理破損は
そのままmirrorされます。この project では「作り直しが壊れた録画が13件実在する」ことが
実測で分かっている以上、**論理事故は仮定ではなく既往**です。RAID1は録画dataの
drive故障対策としては有効ですが、DBには不十分です。

## 4. Phase 0 — 実装0でできること（今日）

`.env` を3行足すだけです。

```
TICTOK_DB_BACKUP_DIR=<別driveのpath>/tictok_backups
TICTOK_JOURNAL_DIR=<別driveのpath>/tictok_journal
TICTOK_LOG_DIR=<別driveのpath>/tictok_logs
```

* backup先の空き容量checkは既にあります(`TICTOK_DB_BACKUP_MIN_FREE_RATIO` 既定1.2)。
* 起動時のmigration前退避は、退避に失敗すると **migrationを走らせず起動を中止**します。
  別driveが外れている状態で起動すると止まります。これは仕様として正しい挙動です。
* **journal と log を遅いdriveへ移す場合は実測してください。** journal は event ごとの
  追記で、log も同様に書き込み頻度が高い経路です。HDDへ向けて `http.loop_lag` や
  `db.write_wait` が悪化しないかを `GET /api/perf` で確認してから確定させます。
  悪化するなら journal と log は SSD のまま残し、**DB backup だけ**別driveへ向けます
  (優先度は圧倒的に backup です)。

これだけで「SSDが飛ぶとDBが復旧不能」は解消します。残るのは
「最後のbackup以降のeventが失われる」だけで、Phase 1 がその窓を縮めます。

## 5. Phase 1 — DB backupの定期実行（小 / 0.5人日）

### 現状

backupが走るのは2経路だけです。

| 契機 | 実装 |
|---|---|
| 人が押したとき | `POST /api/maintenance/backup` |
| 破壊的migrationの直前 | `Storage.__init__` |

**定期実行はありません。**migrationが無い期間が続けば、最後の手動backupのまま何週間も
経ちます。

### 実装

`_capacity_sampler_bg()`(`api/startup.py`)と**同じ形**の background task を1本足します。
capacity sampler が既に「起動時に前回時刻を見て、間隔を過ぎていれば1回実行」を
やっているので、写す先がある状態です。

| 触る場所 | 内容 |
|---|---|
| `core/config.py` | `get_db_backup_interval_hours()` を追加(既定24) |
| `core/dbmaint.py` | `REASON_SCHEDULED = "scheduled"` を追加 |
| `api/startup.py` | `_db_backup_bg()` と `create_task` 1行 |
| `core/settings.py` | `SETTING_DEFS` へ `db_backup_interval_hours` |
| `tests/` | 間隔判定と ops_events の記録 |

世代は**種別ごと**に数える設計なので、`scheduled` を新しい reason にすれば
`premigration` の唯一の像を押し出しません。ここは既存設計がそのまま効きます。

**新しい表は要りません。** capacity sampler は「前回sample」をDBの `capacity_samples` から
引きますが、backup の場合は `dbmaint.list_backups(reason="scheduled")` の最新世代の
stamp がそのまま「前回」です。退避file自体が履歴なので、経過時間の記録先を別に持つ
必要がありません。

**規模: 約60〜100行 + test。**

## 6. Phase 2 — DB backupを2か所へ（小 / 1〜2人日）

### やってはいけない実装

```python
# 駄目 — 2つの異なる瞬間の像になり、しかもDBを2回読む
src.backup(dest_primary)
src.backup(dest_secondary)
```

`create_backup` は `PRAGMA integrity_check` を通してから最終名へ rename するため、
**最終名で存在するfileは必ず「読めることを確認済み」**です。2か所目はその
**検証済みfileの複製**にします。同一の像であることが保証され、DBへの負荷も1回分です。

### 実装

```python
# create_backup の末尾、partial.replace(final) の後
if secondary_dir:
    _copy_durable(final, secondary_dir / final.name)   # fsyncまで待つ既存関数
```

`_copy_durable`(`record/recorder.py`)は **`shutil.copy` がOS cacheへ入った時点で返る**
問題を既に解いてある関数です。外付けdriveがcopy途中でbusから外れた場合、
失敗はcallが返ったずっと後に「遅延書き込みの失敗」として現れます。
2か所目がまさに外付けdriveなので、この関数を通す必要があります。
**新しくcopy処理を書かないでください。**

| 触る場所 | 内容 |
|---|---|
| `core/config.py` | `get_db_backup_dir_secondary()` (既定 空 = 無効) |
| `core/dbmaint.py` | 複製・`prune_backups` の2か所対応・`list_backups` の2か所表示 |
| `record/recorder.py` | `_copy_durable` を共通の場所へ移す(現在は recorder 内) |
| `api/routes/system.py` / `static/ops.js` | 画面に2か所目の状態と最終成功時刻 |
| `tests/` | 複製失敗時に1か所目が残ること・prune が両方に効くこと |

### 失敗の扱い

**2か所目の失敗で起動を止めてはいけません。**1か所目が検証を通っていれば backup は
成立しています。`storage.record_ops_event(kind="maintenance.mirror_failed",
severity=warning)` を書けば、既存の通知rule(`notify_rule_ops`)がそのまま拾います
(`doc/CAPACITY_FORECAST.md` が同じ経路を使っています)。**新しい通知経路は要りません。**

ただし**「2か所目が何日も失敗し続けている」は検知が要ります。**warning 1本は流れます。
capacity と同じく、最終成功からの経過時間で閾値を持たせてください。

**規模: 約150〜250行 + test。**

## 7. Phase 3 — 録画の複製（大 / 8〜15人日）

ここが本体です。**設計上の地雷が2つあります。**

### 地雷1: mirror root を `record_roots()` に足してはいけません

`api/runtime.py` に既に root list の抽象があります。

```python
_RECORD_ROOTS = [RECORD_DIR] if FINAL_DIR == RECORD_DIR else [RECORD_DIR, FINAL_DIR]
layout.set_record_roots(_RECORD_ROOTS)
```

そして `routes/clips.py` は **2本であることを前提に zip しています**。

```python
ROOT_KEYS = ("work", "final")
return {key: Path(root) for key, root in zip(ROOT_KEYS, layout.record_roots())}
```

3本目を足すと `zip` が黙って切り捨てます。それ以前に、
**`record_roots()` は「録画の実体を探す root」**なので、mirror を足すと:

* retention が mirror の bytes を解放見込みに数える
* 「最終保存先へ移動」が「退避先に同名が既にある」と判定して対象から外す
* `_has_usable_media` が mirror 側の素材を見て、原本を派生物として消しにいく
* 再生・再mp4化が mirror 側を掴む

**mirror は `record_roots()` とは別の概念として持つ必要があります。**
これが Phase 3 の規模を押し上げている主因です。

### 地雷2: mover を二重に持たない

`Recorder._move_recording_files` の docstring は
「the ops-screen "relocate to the final dir" action has to move the same set ... Making it
static lets that path reuse this verbatim **instead of growing a second mover that could
drift from this one**」と、二重化を明示的に避けた経緯を残しています。

複製も**同じ集合**(mp4・session dir・派生file・`.sidecars`)を扱うので、
copierを別に生やすと同じ drift を招きます。**「消すか消さないか」をparameterにして
1つの関数に畳む**のが既存設計と整合します。

`_move_session_dir` は既に copy → 全fileのsize検証 → **その後で**元を削除、という
順序で書かれています。`fsync` も入っています。**削除の一歩手前まで、複製に必要な
処理は既にあります。**

### 実装の内訳

| 触る場所 | 内容 | 規模 |
|---|---|---|
| `record/recorder.py` | `_move_*` を copy/move 両対応へ一般化 | 中 |
| `core/layout.py` | mirror root の解決(`record_roots` とは別系統) | 小 |
| `store/_common.py` / `store/maintenance.py` | `recordings` へ `mirror_root` / `mirrored_at` / `mirror_bytes` 列 + migration | 中 |
| `api/media_jobs.py` | job kind `"mirror"` を追加(17→18)、`_run_media_job` の分岐 | 中 |
| `core/ops_labels.py` | 訳語(1箇所に持つ約束) | 小 |
| `api/routes/bulk.py` | 一括複製の投入 | 中 |
| `api/disk.py` / `static/capacity.*` | 「複製済 N本/X GB / 未複製 M本/Y GB」の常時表示 | 中 |
| `core/capacity.py` 周辺 | mirror先の空き容量の予測と閾値割れ通知 | 小 |
| retention | mirror先を削除対象から確実に外す | 小 |
| `tests/` | 既存の mover test に倣う | 大 |

**job queue に乗せれば進捗・取り消し・再実行・GPU枠との共存が全部ただで付きます。**
`MEDIA_JOB_KINDS` に1つ足すだけで Job 画面に出ます(「別台帳だった頃はJob一覧に出ず、
GPUを同じ枠で取り合っているのに『動いているのにjobが無い』と読める状態だった」)。

### 複製する範囲の既定

| 対象 | 既定 | 理由 |
|---|---|---|
| 素材 `.ts` | **複製する** | 再取得不能な原本 |
| mp4(素材なしの録画) | **複製する** | その録画の唯一の原本 |
| mp4(素材ありの録画) | 複製しない | 再mp4化で戻る。316.3GBを倍にする価値が無い |
| `_backup/` | **複製する** | 唯一原本であり得る(実測13件27.4GB) |
| `.sidecars/` | **複製する** | 小さく、失うと文字起こしがズレる(※2) |
| pool `avatars/` 他 | **複製する** | 小さく、CDN URLが期限切れする(※3) |
| 焼き込み・Up出力・`_clips/` | 複製しない | 再生成可。GPU時間だけ |

この既定は `doc/RETENTION.md` の資産序列(transient → derived → source)の**裏返し**です。
retention が最後に消すものを、mirror は最初に複製します。同じ序列を2箇所に別の形で
書かないよう、判定は `_has_usable_media` / `has_media` を通してください。

### 検証

`_copy_durable` の size 一致 + fsync が最低線です。**sha256 は option** にします
(8.69GB/日なら1〜2分ですが、既存に録画の content hash は1つも無く、
指紋を持ち始めると持ち主と更新契機の設計が要ります)。

**規模: 約600〜1,000行 + test。8〜15人日。**

## 8. Phase 4 — off-site（中 / 3〜5人日）

火災・盗難・ransomware・誤操作に効くのはこの層だけです。2つの道があります。

| 方式 | 実装 | 引き換え |
|---|---|---|
| **app外**: 定時task + `rclone sync` | **0行**(script と手順のみ) | appのDBが把握しないので画面に出ない。失敗が通知経路に乗らない |
| **app内**: Phase 3 の mirror 先をcloudにする | Phase 3 + 3〜5人日 | 画面・通知・job台帳に全部乗る |

**Phase 3 を作るなら app 外の rclone で十分**です。mirror が local に在れば、
そこから rclone で cloud へ流すのが一番単純で、`_copy_durable` の fsync 前提とも
衝突しません。Phase 3 を作らないなら、app内でやる意味も薄くなります。

## 9. 費用

### local HDD 1台

原本相当(素材 + 唯一原本のmp4 + `_backup` + DB + sidecars + pool)は概ね **2TB級**です
(2026-07-20実測で K: 使用2,085GB)。8.69GB/日で増えるので、

* 8TB HDD 1台: **¥15,000〜20,000**(1回)
* 満杯まで: (8,000 - 2,000) ÷ 8.69 ≒ **690日(約1.9年)**

### cloud (ap-northeast-1 実価格)

2TBを置く場合の月額です。単価は前回のAWS調査で取得した実値です。

| tier | 単価 | 2TB/月 |
|---|---:|---:|
| S3 Standard | $0.023/GB | $47.1 |
| S3 Standard-IA | $0.0138/GB | $28.3 |
| **S3 Glacier IR** | $0.005/GB | **$10.2** (¥1,530) |
| S3 Deep Archive | $0.002/GB | $4.1 |

**復元は無料ではありません。**Glacier IR から 2TB を手元へ戻すと、
取り出し $0.03/GB = $61 + 転送 $0.114/GB = $228 で、**合計約$290(¥44,000)** です。
災害時に1回払う額としては妥当ですが、「気軽に戻せる」ものではないことは
把握しておいてください。

**Deep Archive は原本には使えません**(取り出しに最大12時間)。

### まとめ

| 構成 | 初期 | 月額 |
|---|---:|---:|
| Phase 0 のみ(既存の空きdriveへ向ける) | ¥0 | ¥0 |
| + local HDD 1台 (Phase 3) | ¥20,000 | ¥0(電気代) |
| + cloud off-site 2TB (Phase 4) | ¥0 | ¥1,530 |

**local HDD 1台は約1年でcloudのcostを下回ります**が、off-site の代わりにはなりません
(同じ部屋にある2台は、火災と盗難に対しては1台です)。

## 10. 採らない案

| 案 | 理由 |
|---|---|
| DBを RDS / PostgreSQL へ | `doc/STORAGE_SPLIT.md` の lock 契約(`_lock -> _buf_lock` 一方向)がSQLite前提。改修が大きく、backup問題は別volume化で解ける |
| RAID1 だけで済ませる | 論理破損・誤削除がmirrorされる。この project では「壊れた作り直し」が実測13件実在する |
| `src.backup()` を2回叩く | 2つの異なる瞬間の像になり、DBを2回読む |
| mirror root を `record_roots()` へ追加 | retention・relocate・再生・`_has_usable_media` が mirror を原本と取り違える。`ROOT_KEYS` の zip が3本目を黙って捨てる |
| 録画の複製に `shutil.copy` を使う | OS cache へ入った時点で返る。外付けdriveの遅延書き込み失敗を検出できない。`_copy_durable` を使う |
| 複製の判定に尺(duration)を使う | `doc/BACKUP_PRUNE.md` の実測で18件中13件を誤判定。frame数で見る |

## 11. 検証 — backupは「戻せた」ことでしか確認できない

`doc/DB_MAINTENANCE.md` に復元手順(4段)があります。**この手順を1度も通していない
backupは、backupではありません。**

Phase 1 を入れたら、そのタイミングで1度やってください。

1. serverを停止する(単一instance lockがあるため起動したままの差し替えはできない)
2. `tictok.db` / `-wal` / `-shm` を別名で残す
3. 退避fileを `tictok.db` としてcopyする(**`-wal` / `-shm` はcopyしない**)
4. 起動して、画面が読めることと件数が合うことを確かめる

Phase 3 を入れたら、**mirror 側から1本の録画を戻して再生できるか**を同じように
1度通してください。素材だけでなく `.sidecars` が揃っていないと、
戻した録画の文字起こしがズレます(※2)。

## 12. 順序

```
Phase 0 (今日・0行)  ->  Phase 1 (0.5人日)  ->  復元testを1度通す
   -> Phase 2 (1〜2人日)  -> [ここまでで DB は守れている]
   -> Phase 3 (8〜15人日) -> [録画原本が drive 故障で消えなくなる]
   -> Phase 4 (3〜5人日)  -> [火災・盗難・ransomware]
```

**Phase 0 と Phase 1 で、被害の大きい方(DB)の穴はほぼ塞がります。**
Phase 3 は工数が一桁大きいので、そこまで一気にやる必要はありません。
