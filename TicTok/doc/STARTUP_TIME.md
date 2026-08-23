# 起動時間

server起動が「なんとなく遅い」を、段ごとの実測で答えられるようにするための記録。数字は
2026-08-21時点のこの環境（DB 1.63GB / journal 350MB・15日ぶん / 録画1000本超）のもの。

## 段と実測（2026-08-21 08:41 の起動、合計44.6秒）

| 段 | この日 | 平常 | どこ |
|---|---|---|---|
| import 〜 storage初期化 | 1.1s | 1〜2s | `Storage.__init__`（schema・migration・退避） |
| journalの件数を数える | 6.9s | 6〜10s | `recover_from_journal` の1 pass目 |
| 残っていたsessionの確定 | **20.0s** | 0.1s未満 | `cleanup_stale_sessions` |
| 録画directoryの解決 | 2.2s | 0.1〜1.7s | `runtime` のsidecar移行 |
| 孤児captureの掃除 | 5.8s | 0.1〜0.6s | `lifespan` の `orphan_capture.sweep` |
| browser resolverの起動 | 6.2s | 0.4〜1.1s | `lifespan` の `manager.startup()` |
| 残り（監視復元・media queue） | 2.4s | 1〜2s | `lifespan` |

平常の合計は6〜18秒。ops_eventsの `process.startup_recovery_completed` に37回ぶんの記録が
あり、復旧の段だけで6〜10秒がずっと続いていた。

## 直した2つ

### journalの件数を毎回数え直さない

`recover_from_journal` の1 pass目は、保持期間ぶんのjournal全部（350MB）を毎起動 `json.loads`
していた。実測5.9秒で、内訳は json.loads 3.3s / utf-8 decode 1.4s / file読み 0.3s。37回の起動で
実際に復元が要ったのは1回だけである。

journalは追記onlyなので、既に数えた区間の件数は二度と変わらない。`journal/count_cache.json`
へ「file名・どこまで数えたか(byte位置)・session別の件数」を残し、次の起動はその続きだけを
数える。行の読み方(`_iter_journal_rows`)は1箇所のままで、cacheは**数え直せば同じ数が出る派生物**
でしかない。

| | 実測（350MB） |
|---|---|
| 旧・全走査 | 4.7〜5.2s |
| 新・cache無し（初回とcacheが合わないとき） | 4.0s |
| 新・cache有り（平常） | 0.01s |

同時にtext modeをやめてbyte列のまま `json.loads` へ渡している（decodeは行の解釈に何も足さない）。
これが全走査でも1秒速い理由。

守る不変条件は1つ、**cacheが在っても無くても件数は同じ**。確かめたこと（実journal 350MB・
63 session・58万行で全件突き合わせ）:

- cacheあり/なしで件数が完全一致
- 追記されたぶんだけ増え、二重に数えない
- 書きかけの行が末尾に在るとき / その行が完成した後 / 壊れた行が挟まったときも一致
- cacheが壊れている / 版が違う / fileが縮んだときは頭から数え直し、同じ数になる
- 復元される行そのもの（2 pass目）も旧実装と完全一致

改行で終わっていないfile末尾（書き込み中に落ちた行）だけは特別扱いする。その行は**数には
入れる**（落とすと、DBから欠けた最後の1件が復元されなくなる）が、読み切った位置に含められ
ないので、そのfileはcacheへ残さず次回は頭から数える。数えて位置も進めれば二度数え、数えなけ
れば取りこぼす — cacheの都合で復元の判断を動かさないための逃げ道である。

### 孤児の掃除とbrowser起動を並べる

`lifespan` は `orphan_capture.sweep`（録画dirの走査）と `manager.startup()`（headless browserの
起動）を順に待っていた。resolverのbrowserは録画のfileに触らないので、この2つに順序の理由は無い。
並べて、どちらも `manager.restore()` の前に揃うようにした。冷えた起動で12.0秒 → 6.2秒。

## 実測で否定したこと（同じ道を二度調べないために）

### 「WALが書き戻せていない」— 違う

`tictok.db-wal` は94MBある。これは**高水位のfile sizeであって、未書き戻しの量ではない**。
`-shm` のWAL-index headerを読むと、生きているframeは416〜525本（1.6〜2.1MB）しかない。
SQLiteはpassive checkpointでfileを切り詰めず、先頭から再利用する。自動checkpointの閾値は
1000 page（4MB）で、WALはその範囲を巡回している。

crash直後の状態（1.63GB DB + 未書き戻しWAL 90MB）を作って測った結果:

| | |
|---|---|
| open + PRAGMA | 0.08s |
| 最初のread（WAL indexの復旧走査） | 0.00s |
| 最初のcommit | 0.00s |
| `wal_checkpoint(TRUNCATE)` | 0.77s |

つまり大きいWALは起動を遅くしていない。起動時checkpointは入れない（0.77秒払ってfile sizeが
縮むだけで、得るものが無い）。必要になったら `/api/maintenance/checkpoint` が既に在る。

### 「終了時にcheckpointすればよい」— 走らない

logの18回の起動すべてが「停止済みのpidが残したlockを回収します」で始まり、
`process.shutdown_started` は**1件も無い**。serverは常に強制終了されている（`run.bat` が同じ
venvのpythonを巻き添えで殺す）ので、終了処理に置いた仕事は実行されない。

### 20秒の山（`cleanup_stale_sessions`）— 未解明

対象は1 sessionだけで、event 4,752件・bucket 1,130本。同じqueryを実測すると0.00秒で、
必要なindex（`idx_events_session_kind_time` / `idx_viewer_samples_session_time` /
`idx_buckets_session_start`）は全部効いている。SQLでもWALでもない。冷えたpage cacheかdiskの
競合が疑わしいが、当時のlogは合計しか持っていなかったため確定できない。

同じ形の外れ値は2026-08-15 06:41にもう1件（23.8秒）あるが、そちらは原因が別で、migration前の
DB退避（1.4GB copy）だった。

## 次に遅い起動が来たときの読み方

`process.startup_recovery_completed` のlog行に段ごとの秒が載る。JSONL側は `detail.step_ms` に
`journal` / `stale_sessions` / `backfill_buckets` / `stale_recordings` の4つ。storage初期化は
別行（`storage.initialized` の `ctx.duration_ms`）で、migrationと退避を含む。

```
起動時の復旧: journalから 0件のsessionを復元（…）、残っていた 1件のsessionを確定、
1件の録画を中断扱いにしました（bucketを補完したsession 0件 / 内訳 journal 0.1s・
session確定 20.0s・bucket補完 0.0s・録画 0.0s）
```

合計（`duration_ms`）にはstorage初期化も入るので、4つを足しても合計にはならない。
