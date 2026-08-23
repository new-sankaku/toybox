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
