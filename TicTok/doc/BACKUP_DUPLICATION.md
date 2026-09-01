# DBの継続replicationと保存先の二重化

「DBがmain SSDに集中していて、飛ぶと復旧できない」「録画の保存先も1か所」への回答です。

> **改訂 (2026-09-01)**: 初版はDBの対策を「定期snapshotの2か所化」としていましたが、
> **snapshotの間隔がそのままRPO(失う時間)になる**ため、毎秒eventを取り込むこのsystemには
> 不適切でした。DB側の方針を**継続replication(RPO≈1秒)**へ差し替えています。

## 1. 結論

| | 内容 | 実装 | RPO |
|---|---|---|---|
| **今すぐ** | `TICTOK_DB_BACKUP_DIR` / `TICTOK_JOURNAL_DIR` を別driveへ | **0行** | — |
| **Phase 1** | **Litestreamで2台目driveへ継続replication** | **0行** (設定のみ / 1〜2人日) | **≈1秒** |
| Phase 2 | snapshotを「復旧手段」から「archiveの土台」へ役割変更 | 小 (0.5人日) | — |
| Phase 3 | 録画の複製(mirror) | 大 (8〜15人日) | — |
| Phase 4 | off-site | 中 (3〜5人日) | — |

**Phase 1 はapp側の改修が1行も要りません。**理由は §5 にあります。

## 2. RPOで考える — 軸は2つあり、混ぜてはいけません

「replicaを作れば守れる」も「snapshotを取れば守れる」も、片方だけでは穴が残ります。
守る故障が違うからです。

| | 空間軸 (replica) | 時間軸 (履歴) |
|---|---|---|
| 守る故障 | drive死亡・機器故障・火災 | **誤DELETE**・壊れたmigration・論理破損・気づくのが遅れた事故 |
| 手段 | RAID1 / 継続replication | snapshot / WAL archive |
| RPO | 0〜1秒 | 遡れる範囲ぶん |
| 弱点 | **間違いも忠実に複製する** | 最後の記録点までしか戻せない |

### ご指摘の通り、replicaはDELETEに追従します

**replicaはDELETEを「追従できない」のではなく、追従してしまうのが問題です。**

| 手段 | 誤DELETEが複製されるまで |
|---|---|
| RAID1 | マイクロ秒 |
| 継続replication | 約1秒 |
| 同期dual-write | 同一transaction内(=即時) |

忠実なreplicaほど速く間違いを写します。**空間軸をいくら厚くしても論理事故は1件も防げません。**

### 「snapshotを取っておけばいい？」— 半分正解です

snapshotなら誤DELETEから戻せます。ただし戻せるのは**最後のsnapshot時点**で、
それ以降のeventは失われます。24時間間隔なら、誤DELETEに気づいた時に
「消したsessionは戻るが、丸1日ぶんのeventが消える」という交換になります。

**より良い手が1つあります。WAL archive(継続log shipping)です。**

WAL archiveは「1秒ごとの変更履歴」を保持するので、

* drive死亡 → 直前(≈1秒前)まで復旧できる ← **空間軸**
* 誤DELETE → **そのDELETEの直前の瞬間へ戻せる** ← **時間軸**

の両方を1つの仕組みで満たします。snapshotのように「最後の記録点まで巻き戻る」
必要がありません。これが Phase 1 の中身です。

### この projectでの誤DELETEは仮定ではありません

`tictok/store/` には `DELETE FROM` が **30箇所**あり、20の表に及びます。
特に危険なのは次の3つで、いずれも**人の操作かmigrationで一括して行が消えます**。

| 経路 | 内容 |
|---|---|
| `delete_session` | session とその従属表(events / viewers / buckets / envelopes)を一括削除 |
| retention | 保持policyによる一括削除。既定は0だが設定次第で走る |
| intern migration | `doc/DB_INTERN.md` の**破壊的migration**。`events` 表の**列そのものを落とす** |

さらに `glove_migration` / `battle_migration` は `battles.data_json` を**in-placeで書き換え、
元の値はどこにも残りません**。これらに対して起動時に退避を取る仕組みが既にあるのは、
**論理事故が既にこの project の設計上の前提になっている**ことの表れです。

### journal は replica ではありません

`journal/` は event 取り込み時にNDJSONへ追記される耐久記録ですが、
**DBのreplicaの代わりにはなりません**。実装を読むと3点はっきりしています。

| | 実測 |
|---|---|
| 対象 | `_journal_append` の呼び出しは **2箇所だけ** — `"e"`(event) と `"v"`(viewer sample) |
| 耐久性 | `fh.flush()` のみで **fsyncしない**。「プロセスクラッシュは耐えるが電源断は非対象」(docstring) |
| 削除の扱い | `recover_from_journal` は「**session行が無い(=削除済み)ならresurrectしない(削除の意思を尊重)**」 |

つまり journal が守るのは**event列だけ**で、`recordings` / `transcripts` / `settings` /
`media_job_queue` / `users` / `battles` は1行も守りません。そして**誤DELETEはそもそも
巻き戻さない設計**です(それが正しい — journalの仕事ではありません)。

`get_journal_dir()` の docstring も "Kept next to the DB so the backup lives on the same
SSD as the data it protects" と、**同じSSDに置いてある**ことを明言しています。

## 3. 何を守るのか — 棚卸し

**「DB / file / log」で数えると足りません。**実際には13種類あります。

| # | data | 既定の場所 | 再取得 | 失うと |
|---|---|---|---|---|
| 1 | `tictok.db` | DB path (main SSD) | **不可** | event・解析・設定・監視対象・文字起こし・fan台帳・**録画の身元**が全滅 |
| 2 | 録画素材 `.ts` | `record_dir` / `record_dir_final` | **不可** | 録画そのもの |
| 3 | `_backup/` 退避mp4 | 各rootの直下 | **条件付きで不可** (※1) | 作り直しが壊れた録画の原本 |
| 4 | `.sidecars/*.timing.json` | mp4と同じroot | **実質不可** (※2) | 文字起こしが動画とズレる |
| 5 | pool `avatars/` `emotes/` `gift_icons/` | **work root固定** | **実質不可** (※3) | 焼き込みのavatar表示 |
| 6 | `backups/` (DB退避3世代) | **DBの隣 = 同じSSD** (※4) | — | DBと同時に消える |
| 7 | `journal/` (14日) | project root | 不可 | event列の最終防波堤 |
| 8 | mp4(素材が残る録画) | mp4 root | 再mp4化で可 | GPU時間だけ |
| 9 | 焼き込み `.overlay.mp4` / `.up.mp4` | mp4 root | 再生成可 | GPU時間だけ |
| 10 | `_clips/` `_screenshots/` | work root固定 | 再生成可 | 切り出し位置の人の判断 |
| 11 | `semantic_index.db` + `semantic_vectors.bin` | DBの隣 | 再構築可 | 埋め込みの再実行cost |
| 12 | `logs/` (text + JSONL) | project root | 不可 | 事後調査の材料 |
| 13 | `.env` / model weights | project root / 任意 | 書き直し・再DL可 | 手間だけ |

**1 を失うと 2 が孤児になります。** `recordings` 表が無ければ、diskに残った数TBの
`.ts` と mp4 は「誰の・いつの・何の録画か」を誰も知らないfileの山になります。
**DBの優先度が録画より高いのはこのためです。**

### ※1 `_backup/` は「派生物」ではありません

`doc/BACKUP_PRUNE.md` の実測(2026-07-25)では、2次rootの退避86件のうち
**13件27.4GB が削除保留**でした。内訳は現行mp4が無い5件・**現行mp4にvideo streamが
無い2件**・frame数が明らかに足りない5件・行が実fileを指していない1件です。
作り直しが壊れた録画が実在し、その原本は `_backup/` にしかありません。

### ※2 `timing.json` は作り直せますが、作り直すと文字起こしがズレます

`scripts/repair_timing_pts.py` で `.ts` から再生成はできます。しかし
`doc/TIME_AXIS.md` が「**文字起こしは引き直せない** — 古い軸から今の軸へ戻すmapは、
timing.jsonを作り直した時点で失われる」と記録しています。実測で331 groupのうち
134 groupが取り残され、中央値167秒・最大1,194秒(約20分)ずれました。

**`.sidecars/` を「派生物だから後回し」に分類すると、復元したDBの文字起こしが
動画とズレます。**復元できたように見えて中身が合わない、最もたちの悪い壊れ方です。

### ※3 pool は work root にしか無く、CDN URLは期限切れします

`layout.py` の通り `avatars/` `emotes/` `gift_icons/` は **work root ただ1つ**に置かれ、
書くのは収集時のcollectorだけです。TikTok CDNのURLは期限切れするため後から取り直せません。

### ※4 backupがDBと同じdriveに在ります

`get_db_backup_dir()` の既定は `get_db_path()` の親、つまり **`tictok.db` の隣**です。
このSSDが飛ぶと、DBと3世代の退避が同時に消えます。

同種の事故は既に起きています。`doc/DB_MAINTENANCE.md` の記録では、2026-08-23に
intern migration直前の **1.85GBの退避が、test 1回の実行で消えました**(393KBのtest退避3つに
押し出された)。**「取れているつもり」が実際には取れていなかった**実例です。

## 4. Phase 0 — 実装0でできること（今日）

```
TICTOK_DB_BACKUP_DIR=<別driveのpath>/tictok_backups
TICTOK_JOURNAL_DIR=<別driveのpath>/tictok_journal
TICTOK_LOG_DIR=<別driveのpath>/tictok_logs
```

* 起動時のmigration前退避は、**退避に失敗するとmigrationを走らせず起動を中止**します。
  別driveが外れた状態で起動すると止まります。これは仕様として正しい挙動です。
* **journal と log を遅いdriveへ移す場合は実測してください。** journal は event ごとの
  追記です。`GET /api/perf` の `http.loop_lag` と `db.write_wait` が悪化しないかを見て、
  悪化するなら journal と log はSSDのまま残し、**DB backup だけ**別driveへ向けます。

これは Phase 1 の前提ではなく、**Phase 1 までの繋ぎ**です。

## 5. Phase 1 — 継続replication（RPO≈1秒 / app改修0行）

### 手段: Litestream

SQLiteのWALを継続的に別の場所へ送り続けるtoolです。v0.5.x が現行で、
**Windows Service としての稼働が公式にsupportされています**
(`litestream.io/guides/windows/`)。CLAUDE.md の「Windows/Linuxで動作必須」を満たします。

複製先は **local file path** を選べます。**cloudは要りません。2台目のdriveで足ります。**

### app側の改修が要らない理由

Litestreamが要求するpragmaを、`tictok/storage.py` が**既に4つとも設定済み**でした。

| Litestreamの要求 | `storage.py` の現状 |
|---|---|
| `PRAGMA journal_mode = WAL` | `PRAGMA journal_mode=WAL` ✅ |
| `PRAGMA busy_timeout = 5000` (推奨値そのもの) | `PRAGMA busy_timeout=5000` ✅ |
| `PRAGMA synchronous = NORMAL` | `PRAGMA synchronous=NORMAL` ✅ |
| `PRAGMA foreign_keys = ON` | `PRAGMA foreign_keys=ON` ✅ |

**偶然ではなく、どちらも同じ理由(WALでの並行読み書きと待ち)で同じ値に行き着いています。**
`storage.py` に手を入れる必要はありません。

### 何が得られるか

| | |
|---|---|
| **RPO** | 既定で**1秒ごと**にreplicaへ送る。正常なshutdownでは未送信ぶんを送り切ってから終了する |
| **live replica** | `litestream restore -f` は新しい変更を継続的に反映し続ける。**read-onlyで開く前提の warm standby** |
| **誤DELETEからの復旧** | `-timestamp TIMESTAMP` で**任意の時点へ**、`-txid TXID` で**特定transaction直前へ**戻せる |
| **複製先** | local path / SFTP / S3互換。まず local の2台目driveでよい |

**`-txid` があるので、「誤DELETEの直前」に正確に戻せます。**
snapshot方式のように「最後のsnapshotまで巻き戻る」必要がありません。
§2 のご質問への直接の答えがこれです。

### 設定の要点

```yaml
snapshot:
  interval: 1h      # 既定24h。書き込みが多いとLTX fileが積み上がり復元が遅くなる
  retention: 24h    # 遡れる幅。誤DELETEに気づくまでの時間で決める
dbs:
  - path: <TICTOK_DB_PATH>
    replicas:
      - path: <2台目driveのpath>
```

**`retention` が「誤DELETEに気づくまでに許される時間」そのものです。**
24hだと翌日に気づいた事故はもう戻せません。この projectでは
retentionの暴走やmigrationの破壊が数日後に露見し得るので、**7日以上を推奨します**
(WAL archiveは変更ぶんだけなので、録画の8.69GB/日に比べれば容量は誤差です)。

### この app 固有の注意

| 事項 | 内容 |
|---|---|
| **手動checkpoint** | `/api/maintenance/checkpoint` が `PRAGMA wal_checkpoint(TRUNCATE)` を叩きます。Litestreamは自分でcheckpointを制御するため、この操作は `busy=1` を返しやすくなります。**app側は既に `busy` を成功へ丸めていない**ので誤解は生じませんが、buttonの意味が変わることを運用側へ伝える必要があります |
| **VACUUM** | fileを作り直すので、直後にfull snapshotが要ります。手動・明示confirmのみなので頻度は問題になりません |
| **DB差し替え後** | 復元でDB fileを置き換えたら `litestream reset` が要ります(Litestreamはlocal metadataを `.tictok.db-litestream` に持ち、削除・再作成を追跡しません)。**復元手順に必ず含めてください** |
| **test隔離** | `tests/conftest.py` が `TICTOK_DB_BACKUP_DIR` をsandboxへ向けているのと同じ配慮が要ります。Litestreamの監視対象は**本番のDB pathだけ**にします |
| **`-wal` / `-shm`** | 復元時にDB fileだけ置き換えて古い `-wal` を残すと、SQLiteが古いWAL pageを新しいDBへ適用します。3点セットで消します |

### RAID1 との関係

**どちらか一方ではなく、役割が違います。**

| | RAID1 (Storage Spaces 双方向mirror / mdadm / ZFS) | Litestream |
|---|---|---|
| drive死亡時 | **止まらない**。RPO=0 | 止まる。復元してから再開(RPO≈1秒) |
| 誤DELETE | **無力**(即座に複製される) | `-txid` で直前へ戻せる |
| 実装 | 0行。ただしDBを mirror volume 上へ置く必要あり(`TICTOK_DB_PATH` は設定可) | 0行 |
| 費用 | SSD 1台 | 0円(2台目driveの空き) |

**復旧を求めるなら Litestream、無停止を求めるなら RAID1** です。
ご相談の「吹き飛ぶと復旧もできません」に直接答えるのは Litestream です。
両方入れれば「止まらず、かつ誤操作からも戻せる」になります。

**工数: 設定fileとService登録で1〜2人日。**大半は §11 の復元testを通す時間です。

## 6. Phase 2 — snapshotの役割を変える（小 / 0.5人日）

Litestreamを入れると、**既存の `/api/maintenance/backup` は「復旧手段」ではなくなります**。
役割は2つに絞られます。

1. **Litestream自体が壊れていた場合の保険。** 設定ミス・Service停止・複製先の枯渇に
   気づかないまま数週間、はあり得ます。app自身が取る自己完結したsnapshotは、
   その系統から独立した唯一の像です。
2. **WAL retentionより古い時点への復帰。** archiveが7日なら、8日前の状態はsnapshotにしか
   ありません。

したがって Phase 2 でやることは、初版で書いた「定期化」と「2か所化」のうち**定期化だけ**です。

| 触る場所 | 内容 |
|---|---|
| `core/config.py` | `get_db_backup_interval_hours()` (既定 168 = 週1) |
| `core/dbmaint.py` | `REASON_SCHEDULED = "scheduled"` |
| `api/startup.py` | `_capacity_sampler_bg()` と同形の background task 1本 |
| `core/settings.py` | `SETTING_DEFS` へ追加 |

**新しい表は要りません。** capacity samplerは前回時刻をDBから引きますが、backupは
`dbmaint.list_backups(reason="scheduled")` の最新世代のstampがそのまま「前回」です。
退避file自体が履歴なので、経過時間の記録先を別に持つ必要がありません。

世代は**種別ごと**に数える設計なので、`scheduled` を新しい reason にすれば
`premigration` の唯一の像を押し出しません。既存設計がそのまま効きます。

**「2か所へcopy」は不要になりました。** Litestreamの複製先が既に2か所目です。
snapshotは Phase 0 で別driveへ向けてあれば足ります。

> 初版では `src.backup(dest)` を2回叩かず検証済みfileを `_copy_durable` で複製せよ、と
> 書きました。この注意自体は正しいままですが、**その実装はもう要りません**。

## 7. Phase 3 — 録画の複製（大 / 8〜15人日）

DBと違い、録画は「継続replication」の対象になりません。1本が数百MB〜数GBの
不変fileで、書かれるのは録画中の追記と完了時の1回だけだからです。**完了した録画を
複製するjob**が正しい形です。

### 地雷1: mirror root を `record_roots()` に足してはいけません

`api/runtime.py` に既にroot listの抽象があります。

```python
_RECORD_ROOTS = [RECORD_DIR] if FINAL_DIR == RECORD_DIR else [RECORD_DIR, FINAL_DIR]
layout.set_record_roots(_RECORD_ROOTS)
```

そして `routes/clips.py` は **2本であることを前提に zip しています**。

```python
ROOT_KEYS = ("work", "final")
return {key: Path(root) for key, root in zip(ROOT_KEYS, layout.record_roots())}
```

3本目は `zip` が黙って切り捨てます。それ以前に `record_roots()` は
「録画の実体を探すroot」なので、mirrorを足すと:

* retention が mirror の bytes を解放見込みに数える
* 「最終保存先へ移動」が「退避先に同名が既にある」と判定して対象から外す
* `_has_usable_media` が mirror 側の素材を見て、**原本を派生物として消しにいく**
* 再生・再mp4化が mirror 側を掴む

**mirror は `record_roots()` とは別の概念として持つ必要があります。**
これが Phase 3 の規模を押し上げている主因です。

### 地雷2: mover を二重に持たない

`Recorder._move_recording_files` の docstring は
「a second mover that could drift from this one」を避けた経緯を明示しています。
複製も同じ集合(mp4・session dir・派生file・`.sidecars`)を扱うので、
**「消すか消さないか」をparameterにして1つの関数に畳む**のが既存設計と整合します。

`_move_session_dir` は既に copy → 全fileのsize検証 → **その後で**元を削除、という順序で
`fsync` 込みで書かれています。**削除の一歩手前まで、複製に必要な処理は既にあります。**

`_copy_durable` は「`shutil.copy` はOS cacheへ入った時点で返る」問題を解いた関数です。
複製先が外付けdriveである以上、**新しくcopy処理を書かず必ずこれを通してください。**

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
| retention | mirror先を削除対象から確実に外す | 小 |
| `tests/` | 既存の mover test に倣う | 大 |

job queueに乗せれば**進捗・取り消し・再実行・GPU枠との共存が全部ただで付きます**。

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

これは `doc/RETENTION.md` の資産序列(transient → derived → source)の**裏返し**です。
retentionが最後に消すものを、mirrorは最初に複製します。判定は
`_has_usable_media` / `has_media` を通し、序列を2箇所に別の形で書かないでください。

**規模: 約600〜1,000行 + test。**

## 8. Phase 4 — off-site（中 / 3〜5人日）

火災・盗難・ransomwareに効くのはこの層だけです。

* **DB**: Litestreamの複製先をもう1つ増やすだけです(S3互換を追加)。**実装0行**。
  WAL archiveは変更ぶんだけなので転送量も費用も僅少です。
* **録画**: Phase 3 の mirror が local に在れば、そこから `rclone sync` で流すのが
  一番単純です。app内に取り込む必要はありません(`_copy_durable` の fsync 前提とも
  衝突しません)。

## 9. 費用

### DB (Phase 1)

| | |
|---|---|
| Litestream | 無料(Apache-2.0) |
| 複製先 | **2台目driveの空き**。DB 506MB + WAL archive で数GB規模 |
| off-site を足す場合 | S3 Standard $0.023/GB-月。数GBなら **月$0.1未満** |

**DBの継続replicationは実質タダです。**守る価値との差が最も大きい投資です。

### 録画 (Phase 3 / 4)

原本相当は概ね **2TB級**(2026-07-20実測で K: 使用2,085GB)、8.69GB/日で増えます。

| | 初期 | 月額 |
|---|---:|---:|
| 8TB HDD 1台 | ¥15,000〜20,000 | ¥0(電気代) |
| S3 Glacier IR 2TB | ¥0 | **$10.2 (¥1,530)** |

8TB HDD は満杯まで (8,000−2,000) ÷ 8.69 ≒ **690日(約1.9年)**。
local HDD は約1年でcloudのcostを下回りますが、**off-siteの代わりにはなりません**
(同じ部屋にある2台は、火災と盗難に対しては1台です)。

復元も無料ではありません。Glacier IR から2TBを戻すと取り出し $0.03/GB = $61 +
転送 $0.114/GB = $228 で **合計約$290 (¥44,000)** です。
**Deep Archive は原本に使えません**(取り出しに最大12時間)。

## 10. 採らない案

| 案 | 理由 |
|---|---|
| **定期snapshotだけでDBを守る** | 間隔がそのままRPO。毎秒eventを取り込むsystemで数時間ぶんを捨てる交換になる |
| **replicaだけでDBを守る** | 誤DELETEを1秒で複製する。時間軸が無い |
| RAID1 だけで済ませる | 同上。論理事故に無力。ただし無停止のためには有効で、Litestreamと併用する価値はある |
| journal をDBのbackup代わりにする | 対象は event と viewer の2種のみ。`recordings` も `settings` も守らない。fsyncもせず、削除も巻き戻さない |
| app内に同期dual-writeを実装 | RPO=0だが、書き込みlatencyが倍になり、複製先の失敗時のpolicyが要る。Litestreamで1秒まで詰められる以上、割に合わない |
| DBを RDS / PostgreSQL へ | `doc/STORAGE_SPLIT.md` の lock 契約(`_lock -> _buf_lock` 一方向)がSQLite前提。改修が大きい |
| mirror root を `record_roots()` へ追加 | retention・relocate・再生・`_has_usable_media` が mirror を原本と取り違える。`ROOT_KEYS` の zip が3本目を黙って捨てる |
| 録画の複製に `shutil.copy` を使う | OS cacheへ入った時点で返る。外付けdriveの遅延書き込み失敗を検出できない |
| 複製の判定に尺(duration)を使う | `doc/BACKUP_PRUNE.md` の実測で18件中13件を誤判定。frame数で見る |

## 11. 検証 — 「戻せた」ことでしか確認できません

**通したことのない復元手順は、復元手順ではありません。**

### Phase 1 を入れたら（必須）

1. serverを停止する(単一instance lockがあるため起動したままの差し替えはできない)
2. `tictok.db` / `-wal` / `-shm` を別名で残す
3. `litestream restore -timestamp <10分前> -o tictok.db <replica>` を実行する
4. `litestream reset` を実行する(**忘れるとreplicationが以後おかしくなります**)
5. 起動して、画面が読めることと件数が合うことを確かめる

**3で「10分前」を指定するのが要点です。**最新へ戻すだけでは、
誤DELETEからの復旧が本当にできるかを確かめたことになりません。

### Phase 3 を入れたら

mirror側から1本の録画を戻して**再生できるか**を確かめてください。
素材だけでなく `.sidecars` が揃っていないと、戻した録画の文字起こしがズレます(※2)。

## 12. 順序

```
Phase 0 (今日・0行)
   -> Phase 1 (1〜2人日) Litestream + 復元testを1度通す
        [ここでDBは RPO≈1秒 + 誤DELETEから復旧可能 になる]
   -> Phase 2 (0.5人日) snapshotを週1で定期化
   -> Phase 3 (8〜15人日) 録画の複製
   -> Phase 4 (3〜5人日) off-site
```

**Phase 1 までで、被害が最も大きい対象(DB)の穴は実質塞がります。**
app改修0行・費用ほぼ0円に対して、得られるものが一番大きい段です。
Phase 3 は工数が一桁大きいので、そこまで一気にやる必要はありません。
