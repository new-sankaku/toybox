# route が event loop を塞がないようにする

## 何が問題だったか

`Storage` の `self._lock` は **書き込みlock** である。event batch writer が INSERT〜commit を
握っている間、`get_recording` のような1行readも含めて全部が待たされる。

route本体から直に `storage.*` を呼ぶと、待つのが **event loop 自身** になる。1回のcommit
遅延で、そのrequestだけでなく**他の全requestとWS配信が同時に止まる**。「1行readだから軽い」
では済まないのはこのためで、軽いかどうかではなく**どのthreadで待つか**の問題である。

対象は route本体から直に呼んでいた **52 route / 72箇所**(`to_thread` へ渡す入れ子関数の中は
既にloopの外なので除外)。

## 直し方

`session_detail` が元から持っていた形に揃えた。

```python
# 駄目 — loopを握ったまま書き込みlockを待つ
recording = runtime.storage.get_recording(recording_id)

# これ — 待つのはworker thread側。loopは他のrequestを回せる
recording = await asyncio.to_thread(runtime.storage.get_recording, recording_id)
```

呼び出しが複数並ぶrouteや、DB読み→file削除→DB削除と続くrouteは、1件ずつ出すと往復だけで
嵩むので**入れ子関数にまとめて1回で**出す(`delete_session` / `delete_sessions_by_users` /
`transcribe_queue_api`)。

## event loop 側に残したもの(意図的)

**live collector に触る部分は残す。** collectorはprocess内で収集中に書き換わっている
snapshotで、別threadから覗くと書き換えの途中を掴む。DBのように lock で守られていない。

| 箇所 | 何を | なぜ残したか |
|---|---|---|
| `sessions.delete_session` | `manager.active_session_ids()` | 収集中判定。live collectorの集合 |
| `sessions.delete_sessions_by_users` | 同上 | 同上 |
| `sessions.list_sessions` | `manager.active_session_ids()` / `manager.get()` / `collector.stats` | 収集中sessionの実績はcollectorが持つ |
| `sessions._battles_for_session` | `collector.battles_snapshot()` | **収集中の枝だけ**。終わったsessionを読むDB側の枝はthreadへ出した |
| `sessions.session_rankings` | `manager.snapshots()` | 同上 |
| `monitors.*` (8 route) | `_get_collector()` と `collector.*_snapshot()` | 監視中の実況値そのもの。DBを読まない(in-memory) |
| `search.add_live_bookmark_api` | `_get_collector()` | 同上 |
| ~~`ws.websocket_endpoint`~~ | `manager.snapshots()` | **撤回**。in-memoryでも重い（下記「2巡目」を参照） |

`_get_collector` は `manager.get()` + 404 で、**DBを読まない**。残しても書き込みlockは待たない。

## 72箇所に入っていなかったが、同じ理由で直したもの

route本体の `storage.*` だけを数えると出てこないが、**中でDBを読む支援層の同期関数**が
loop上に残っていると、そのrouteは結局塞がる。実測で見つけて直した:

- `media_jobs.media_job_queue.list_jobs()` — `transcribe_queue_api` / `cancel_transcriptions_api` / `ws`
- `runtime._get_session_or_404()` — session系7 route と AI系2 route
- `sessions._battles_for_session()` のDB枝 — 上記のとおり枝で分けた

いずれも呼び出し側(route)で `to_thread` に包んだ。支援層(`runtime.py` / `media_jobs.py`)は
1行も変えていない。

## 効果(実測)

収集中のcommitを模して **storageの書き込みlockを別threadから400ms握り**、その間にrouteを
叩いて、**同じevent loop上のtickが止まった最長時間**を測った。testのpassでは出ない差なので、
ここを数字で見る。

| | loopが200ms以上止まったroute |
|---|---|
| 修正前 | **15 / 43** |
| 修正後 | **0 / 43** |

代表例(loop停止時間):

| route | 前 | 後 |
|---|---:|---:|
| `/api/recordings` | 405.3ms | 32.0ms |
| `/api/recordings/{id}/transcript` | 414.7ms | 16.0ms |
| `/api/sessions/{id}` | 401.5ms | 19.1ms |
| `/api/sessions/{id}/battles` | 412.6ms | 16.1ms |
| `/api/transcribe/queue` | 403.6ms | 16.0ms |
| `/api/monitors/{id}/history-stats` | 402.8ms | 16.6ms |

悪化したrouteは無い。routeの**応答時間**が400ms前後になるのは当然で(lockが空くまで結果は
出ない)、問題は「その間ほかの全部が止まるか」だった。残る16msはtickの粒度(5ms)と測定の揺れ。

計測の落とし穴を2つ踏んだので書いておく:

* **appは測定用loopの上で動かすこと。** `TestClient` は自前のloopを別threadに立てるので、
  それで測ると何をしても「塞いでいない」に見える
* **測定側が `thread.join()` を直に呼ばないこと。** routeが即返る場合、測定側の停止を
  routeのせいだと読み違える(これで9本を誤って「塞いでいる」と数えた)

## 2巡目 — routeではなく背後の処理（2026-08-23）

route側を直した後も、`http.loop_lag` は1日17〜28回・1回0.8〜1.4秒（最大5.7秒）残っていました。
全gz回転logを展開した836件のうち、**593件（71%）は処理中のrequestが0件**です。つまり残りの
犯人はrouteではなく、background処理でした。

### in-memoryなら軽い、は成り立たない

上の表で `ws.websocket_endpoint` を「DBを読まない(in-memory)」という理由で残しましたが、
これは誤りでした。重さの理由はDBだけではありません。

`manager.snapshots()` が返す `recent_events` は設定 `event_history`（既定200・最大5000）の
ぶんだけ積まれており、実測で **1接続あたり5,466,601 byte**（1配信者ぶんで99.95%がこの列）。
`js_safe()` の全走査と `json.dumps` がそのまま loop 上に乗ります。

| | 同時刻の `/api/disk` |
| --- | ---: |
| idle時 | 4ms |
| WS接続中 | **976 / 1008 / 1177ms**（3回とも再現） |

**11画面すべてがWSを張る**ので、画面を開くたびにserverが約1秒止まり、その画面が続けて投げる
APIが丸ごと後ろに並んでいました。直下の `jobs` は既にthreadへ出してあり、重い方だけが
残っていた形です。

判定の基準を書き換えます。**loopに残してよいのは「in-memoryかどうか」ではなく「量が
有界で小さいかどうか」です。** `_get_collector()` のような参照1回は残してよく、
snapshot全体のcopyとserializeは量に比例するので出します。

WSが送る件数は `ws_recent_events` で持ちます。`event_history`（DB・画面側の保持）とは別の
関心事なので、設定も分けています。

### 直したもの

| 箇所 | 何が loop 上にいたか | 実測 |
| --- | --- | --- |
| `search/indexer.py` `index_comments` / `index_transcript` / `index_laughter` | `async def` だが本体は同期。`iter_events` → `replace_search_hits`（FTS5のDELETE+一括INSERT）→ `set_recording_time_axis` | `search.comments_indexed` 2,136件中173件(8.1%)が4秒以内にloop停止を伴い、中央1,466ms・最大5,714ms |
| `collect/collector.py` `_idle_watchdog` → `_persist_progress` | 30秒ごと、Battle/Collab窓が開いている間。`save_battles` ほか4本をDELETE→INSERT全置換 | write lock待ちがそのままloop停止になる |
| `collect/collector.py` `_on_recording_finalized` | `delete_recording` / `update_recording` / `get_recording` を直に呼ぶ | 1巡目でroute側52本を出したときcollector側は手つかずだった |
| `api/routes/ws.py` | 上記 | `/api/disk` 4ms → 976〜1177ms |

`index_*` はDBを触る所を `_write_comment_hits` のような同期関数へ寄せてからthreadへ出し、
loop上には `await` する材料集めだけを残しています。

`_persist_progress` は **写しを組むのをloop上に残し、DB書き込みだけをthreadへ出す**形に
分けました（`_checkpoint_progress`）。写しを組む所をlockの中に入れているのは「写しを取った
順 = 書く順」を保つためで、外に出すと先に取った古い写しが後から取った新しい写しを
DELETE→INSERTで上書きし得ます（窓が一時的に巻き戻る）。

### 2巡目で意図的に残したもの

| 箇所 | なぜ残したか |
| --- | --- |
| `collector._persist_final` | 呼び出し3箇所のうち2箇所が `except asyncio.CancelledError` の中。そこで `await` すると再度cancelを浴びて確定が途中で落ちる（sessionが `ended_at` を持たないまま残る） |

### 止まっている最中のstackを写す

request一覧では犯人に届きません。`note_loop_lag` はloopが**動き出してから**呼ばれるので、
その時点で犯人は既に戻っています。実測でも停止836件のうち **593件(71%)が「同時刻に処理中の
requestなし」** でした。

止まっている間に覗けるのは、そのloopに乗っていない別threadだけです。`core/perf.py` の
`_stall_watchdog`（thread名 `perf-stall-watchdog`）がloopのheartbeatを見張り、閾値を超えて
止まっている間に `sys._current_frames()` からloop threadのstackを写して
`http.loop_stall_stack` に残します。

| 設定 | 既定 | 意味 |
| --- | ---: | --- |
| `TICTOK_PERF_STALL_SAMPLE_MS` | `2000` | これを超えて止まっている間にstackを写します |
| `TICTOK_PERF_STALL_SAMPLE_ENABLED` | `1` | 番人そのもの |

平常時の費用はtickごとの引き算1回だけです。stackを歩くのは停止1回につき1度で、同じ停止の
間は二度写しません（写した瞬間のframeが全てで、何枚撮っても中身は変わりません）。見張りの
粒度は閾値の1/8に従わせています（独立のつまみを増やしても、調整する材料がありません）。

故意にloopを止めて確かめた出力です。犯人の関数名と、止めている行そのものが出ます:

```
event loopが879ms止まっている最中のstackです（同時刻に処理中: 処理中のrequestなし）
  File ".../stall_check.py", line 22, in main
    guilty_function_that_blocks_the_loop()
  File ".../stall_check.py", line 17, in guilty_function_that_blocks_the_loop
    time.sleep(2.5)
```

### まだ残っているもの

15〜20秒 × 約110秒間隔で反復する大きな停止（08-06 / 08-11 / 08-14 / 08-17）は犯人を特定
できていません。前後5秒にlogが1行も無く、当該時刻にmedia jobもSTT jobも0件で、`/api/disk`
の61秒pollは乱れずに通っています。次に踏んだときは
`http.loop_stall_stack` に犯人のstackが残ります（上の節）。

起動時backfillの空振りも26件残しました。`session_id` が無い47件は `index_comments` が
入口で空を書くだけなので対象から外しましたが、残る26件（本当にcomment 0件の録画15本と、
空の文字起こし11本）は「0件でindex済み」の印がDBに要ります。列を1つ増やして済み判定の
根拠を2つ抱えるより、threadへ出した後のms級の空振りとして残す方を選びました。

## 併せて直した静的解析の指摘

分割で見えるようになっただけで、**分割前の7,537行版にも同じく存在していた**もの。

- `routes/search.py` **`RUF006`** 3件 — 進捗通知の `loop.create_task()` の戻り値を保持して
  いなかった。asyncioはrunning taskを強参照しないので、**通知が配られる前にGCへ回収され得る**
  (buildは走り続けるが画面は0%のまま動かない)。`semantic_build_api` が
  `runtime._semantic_build_tasks` でやっているのと同じ流儀に揃え、`_spawn_progress` で保持する
- mypy 5件 — `_MaterialMetric` の `label`/`attach` が `object` で「呼べない」と言われていた
  ので `Callable` にした。`metrics` は指標が増えると要素数が変わるので `tuple` 注釈にした。
  `search.py` の `state` dict は int と str が同居して値が `object` に潰れていた
- `F541` 1件 — placeholderの無い f-string(連結の一部)。`f` を外しただけ


## 3巡目 — loopが「diskに触る」こと自体を止める（2026-09-03）

2巡目で仕込んだ `http.loop_stall_stack` が、未解明だった **15〜20秒 × 約100秒間隔の
反復停止** の正体を写しました。

### 何が起きていたか

停止の時刻は **Windows Update が更新の直前に作る「システムの復元ポイント」** と秒単位で
一致していました（Application log の `System Restore 8194 … wuauserv`、同時に VSS が
`8219/8220 Ran out of time`）。復元ポイント = VSS snapshot で、作成中は volume の I/O を
止めて dirty data を書き切ります（flush and hold）。録画 ffmpeg と DB が書き続けている
最中だったため、C: の file 操作（stat・dir 列挙・exe の起動）が **15〜19秒返りません**でした。

それ自体は Windows の仕様です。被害を大きくしていたのは、その間 loop thread が同期の
file 操作の中に居たことです（stall stack 26件の内訳）:

| 場所 | 件数 |
| --- | ---: |
| `recorder.progress_token`（5秒ごとの録画進捗 check、scandir + stat） | 6 |
| `recorder._segment_facts`（確定時、segment ごとの stat × 4〜5 pass） | 5 |
| `ffprobe.run` / `recorder._launch` の `CreateProcess` | 5 |
| `media_queue._run` の writer lock 待ち（VACUUM 中） | 2 |
| `shutil.disk_usage`、`avatar_pool` の stat / write | 3 |
| OS の sleep（`select` の中、対象外） | 3 |

**連鎖**: stall ≥3秒の直後 3秒以内に live 接続断（5/5件）→ 再接続 → 録画が別 file へ分断
（66秒・86秒・8秒の断片）→ 断片ごとに finalize → その finalize が loop 上で stat を数千回
→ 次の stall。08-21 以降の録画 128 本中 83 本が前の録画の終了から 120 秒以内の再開でした
（接続断 76 件のうち stall 起因は 5 件、残りは TikTok 側）。

### 判定基準の更新

2巡目の「量が有界で小さいか」では足りません。**stat 1回でも、disk が応答しなければ
応答するまで loop が止まります。** loop 上で disk（と writer lock）に触らない、が基準です。
触る必要のある処理は `asyncio.to_thread` で worker thread へ出し、loop は結果を待つだけに
します（その間 websocket の ping は送れるので、disk が凍っても接続は切れません）。

### 直したもの

- `collector._recording_stalled` → `progress_token` を thread で
- `recorder._finalize_body` → 空き容量・segment 数・採用 segment の走査を thread で 1 回だけ
  取り、確定中は `_finalize_kept` の写しを `_playlist_segments()` が返す（timing map・尺・
  検証・結合の 4 箇所が同じ答えを共有。以前は 4〜5 回走査していた）
- `recorder._validate_source` / `_write_timing_map` / `_await_healthy` / `start()` の preflight
  → file 操作を thread で
- `ffprobe.run` → `run_sync` を thread で（Windows の `create_subprocess_exec` は process 生成を
  loop thread で行う）。cancel token は contextvar なので `to_thread` がそのまま持ち込む。
  試験は Popen を差し替える（`tests.conftest.popen_via`）
- `media_queue._run` → `claim_next_pending_media_job` を thread で
- `asset_prefetch` → 投入側は disk を見ない。「取得済み」の記憶（`_known`）だけで落とし、初見は
  queue を通して worker が thread で確かめる。`avatar_pool.persist` の stat / write も thread へ
- `ingest._journal_append` → 専用 thread（`_journal_loop`）へ queue で渡す。以前は event ごとに
  loop 上で write+flush。失う窓は「disk が凍っている最中に process が死ぬ」同時発生に限られ、
  journal は元々 fsync しない（電源断は非対象）ので実質の trade-off は無い

### 3巡目で意図的に残したもの

- `recorder._launch`（ffmpeg 本体の起動、stall stack 1件）— asyncio の Process API に
  24 箇所が依存しており、Popen 化は録画の待ち合わせの書き直しになる
- collector の `record_ops_event`（14 箇所）と session 系の書き込み（17 箇所）— writer lock を
  loop 上で取るが、stall stack には 1 件も出ていない（lock 保持は drain の 0.1ms、VACUUM 中を
  除く）
- gift icon / emote の pool の `persist`（write）— 投入側の stat は無くしたが、worker 側の
  write は loop 上のまま（件数が少ない）

### OS 側

Store app の自動更新を止める、または C: の「システムの保護」（復元ポイント）を切れば、
発生そのものが無くなります。code 側の修正は「起きても録画が分断されない」ためのものです。
