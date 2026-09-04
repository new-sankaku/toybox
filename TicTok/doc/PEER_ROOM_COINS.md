# 相手・味方Roomの実弾(コイン)収集

PK(Battle)で各hostに付く数字は2つある。**BS(バトルスコア=PKポイント)** と
**実弾(コイン)** で、出どころも取れる範囲もまったく違う。

- BS は armies event が全hostぶん名乗る。相手でも味方でも取れる。
- 実弾は**その配信者のRoomに繋いでいた間しか取れない**。armiesはコインを持たない。

実dataの `LinkMicArmies` 8,759件で確認したところ、`user_armies` の要素が持つfieldは
`avatar_thumb / nickname / score / user_id / user_id_str` **だけ**である。`diamond_score`
は1件も無い。Gift履歴のAPIも無いので、**繋いでいなかった瞬間のコインは永久に失われる**。
後から補う手は無く、その場で繋ぎ直す以外にできることは無い。

## 誰のRoomへ繋ぐか

自分以外の全hostである。**味方(コラボ相手)も含む** — 味方の実弾も味方のRoomにしか
流れないので、取りに行く先は陣営で変わらない。

## いつ繋いで、いつ切るか

寿命は**hostごと**で、PK1戦ではない(`Collector._sync_peer_listeners`)。つないでおく
のは次のいずれかに当てはまる相手:

- 進行中のPKに居る
- 今つないでいるコラボ(`_collab_open` の `now_peers`)に居る
- 直前のPKの相手で、まだ `opponent_room_keep_seconds` の内にいる

戦ごとに切っていた頃は、コラボ中の連戦でそのたびに張り直していた。実測した延べ2,937本の
うち **1,617本(55.1%)が同一session・同じ相手への張り直し**で、前の戦の終了からの
間隔は中央値104秒・最短13秒だった。1本ごとにPlaywrightで相手のliveページを開き、その間
**全監視のlive検出と同じlockを握る**ので、これは接続数だけの問題ではない。

コラボ相手の room_id は LinkLayer eventが名乗る(`_peer_rooms`)。判っている相手には
resolverを通さない。

## 失敗したらどうするか

`opponent_room_retry_seconds` をあけて繋ぎ直す。間隔は失敗のたびに伸び、60秒で頭打ち。

**再試行が効く根拠**: sign serverの500はその室の恒久的な拒否ではない。500を受けた80 host
のうち **66 host(82.5%)** は別のPKでは実弾を取れている(@streamer_e は31戦中4回500で25戦は
成功)。1回で諦めると、PKの残り時間(全戦301秒固定)を丸ごと捨てることになる。

**それでも上限は要る**: 相手が配信を終えた室は何度撃っても通らない。

- `opponent_room_retry_max`(既定8) … 連続失敗の上限。既定の15秒間隔なら累計約390秒で、
  PK1戦を撃ち切る長さになる。
- `_PEER_ROOM_MAX_ATTEMPTS`(50) … listener 1本の生涯の総試行数。連続失敗の数は繋がる
  たびに0へ戻るので、「繋がっては即切れる」相手はそれだけでは止まらない。暴走を止める
  ためだけの背板で、通常運用で当たる値ではない。

諦めた時点は `collector.opponent_listener_gave_up` で残す。「まだ試している」のか
「もう来ない」のかで、0の読み方が変わるため。

撃ち切ったlistenerは張り直さない。ただし**次のPKが始まった時だけ**は作り直す
(`_sync_peer_listeners(restart_exhausted=True)`) — その相手が戦えている以上、室は戻って
いる。この作り直しはPK1戦につき相手1人1本までなので、戦ごとに張り直していた頃の接続数を
超えることはない。

## sign server(EulerStream)側の失敗そのもの

繋げない直接の原因はここである。TikTokのWebSocketは必ずsign serverを経由するので、
署名が返らなければ室には入れない。**署名を通すこと自体はこちらのcodeでは直せない**が、
これまで手を打てていなかったのは、直せない部分ではなく**確かめていなかった部分**である。

### 判っていること

- **API keyは適用されている**(keyed tier)。`.env` の `TICTOK_EULER_API_KEY` が読まれ、
  `WebDefaults.tiktok_sign_api_key` に入る。anonymous tierのまま動いていたわけではない。
- **利用上限(429)ではない**。上限は `SignatureRateLimitError` になり理由も別に出る。
  観測しているのは素の500である。
- **service全体の障害でもない**。500の122件は112分に散っており、同じ分に別roomも落ちたのは
  9分だけ。落ちるのは1室ずつで、同時刻に他の室の署名は通っている。

### 判っていなかったこと

**500の中身を1文字も残していなかった**。`sign_server_outage` が拾っていたのは reason /
status / log_id だけで、例外messageに入っている応答bodyも、EulerStreamが付ける
`X-Log-Code` も捨てていた。122件すべてが「500だった」以外に何も語らない記録として
積み上がっていた。log文言は "Sign serverの一時障害" と名乗っていたが、これは
**確かめていない診断**で、上の分布とも合わない。

そこで:

- `_sign_response_ctx` で応答body(先頭400文字)・`X-Log-Code`・`X-Agent-Id`・
  RateLimit系headerをctxへ残す。読むのは応答側だけなのでこちらのkeyは載らない。
- log文言から「一時障害」を外し、起きた事実だけを書く。
- keyed / anonymous のどちらで撃った結果かを毎回のctxに載せ、起動時にも1行残す
  (`process.sign_key_state`)。keyの適用はmodule import時で、その時点ではlog handlerが
  無いため `collector.sign_key_configured` は全logに1件も残っていなかった。

次に500が出たときは、その理由がlogに残る。**原因が判るまで、こちらの打ち手は再取得しか
無い** — 判ったら手が変わる可能性がある。

### 署名要求のtimeoutも500と同じ扱い

TikTokLiveが `SignAPIError` へ包むのは `httpx.ConnectError` **だけ**で、署名要求
(`fetch_signed_websocket`、timeout=15秒)の `ReadTimeout` は生のhttpx例外のまま上がって
くる。そのため `sign_server_outage` の分類を素通りし、httpx/httpcore内部で終わる
Stack Traceとして積まれていた(実測44件、全件が署名要求のframe付き)。

宛先が sign server (`WebDefaults.tiktok_sign_url` のhost)である通信errorだけを
sign server側の失敗として名乗る(`_sign_transport_outage`)。宛先が読めない例外や
TikTok宛の通信断は分類しない — 未知の失敗を外部要因へ吸わせないため。

主Collector側でも同じ判定を通す。timeoutを「TikTokとの通信」として数えていると、署名が
通らないまま撃ち続ける室が `sign_blocked`(room単位の保留)へ落ちない。

### 予期される中断はStack Traceを出さない

相手Roomのlistenerは、分類できない失敗をStack Trace付きで残す。そこに積まれていた113件
のうち86件(76%)は、通信の中断(`httpx.TransportError`)と相手側からのwebsocket切断
(`ConnectionClosed`)で、いずれもStack Traceはhttpx/websocketsの内部で終わり読む材料が
無い。主Collectorは同じ2種を既に1行に落としているので、判定を `expected_transient` へ
括り出して相手Room listenerも同じ物差しにした
(event: `collector.opponent_listener_transient`)。残りの27件 —
`WebcastBlocked200Error` / `LiveResolveBlocked` / `UserNotFoundError` など — は分類の
対象にせず、従来どおりStack Traceのまま残す。

### 利用上限は言われた通り待つ

429のときはserverが `RateLimit-Remaining` で待ち時間を指定してくる。これを無視して
こちらの間隔で撃ち直すと、上限を押し広げることになる。listenerは次の1回だけ、こちらの
間隔とcapより優先して指定秒数を待つ(`_forced_wait`)。

## 取れなかったことを名乗る

`battle.coin_coverage[host_id] = {handle, attached_at, attempts, error}` を残す。

- `attached_at` が `None` … 一度も繋がらなかった。画面は「**実弾 未取得**」。
- `attached_at` が `start_time` より後 … 途中から繋がった。画面は「**実弾 途中(mm:ss〜)**」。
  それ以前のGiftは入っていない。

数値だけを残すと、欠測が「実弾0」として、部分取得が全量として読まれる。**0は不明であって
送信0ではない**(`common.js` の `fmtBs` / `coinCoverageNote`)。

`coin_coverage` を持たない既存recordには断りを付けない。当時つながっていたかどうかを
後から知る手は無く、決め打つと嘘になる。

## 貢献の宛先(host_id)

**チーム戦の armies はチーム1つぶんの集約**で、誰への貢献かを名乗らない(実dataの
`anchor_id_str` は空か陣営placeholder)。以前は代表member(自陣はowner)へ寄せていたが、
それは味方hostを支えた人を自分の貢献者として記録することになる。実例として、session 578
のPKでは **BS 46,004 の貢献者が味方host(RO·RO)のもの**なのに自hostのカードに並んでいた。

宛先が確定するのは実測だけである:

- 自室のGift event … `apply_battle_gift_contributions` が自hostを付ける
- 相手/味方Roomのlistener … `_on_opponent_gift` がそのhostを付ける

どちらも無い分は `host_id` を空のままにし、画面は「**宛先不明（陣営の合計のみ）**」の枠
へ出す(`buildBattleUnattributed` / `unattributedGroup`)。hostのカードへ寄せない。

## 陣営(side)

`_on_opponent_gift` は拾った実弾の陣営を **participants から引く**。"opp" と決め打つと、
味方hostのRoomで拾った実弾が敵陣の貢献として記録され、配信者profileの敵陣集計が味方を
数えることになる。

## opponents に味方が混ざる件

収集時の `_capture_opponents` は anchor_info に載る「自分以外のhost」を全員 `opponents` へ
入れる。anchor_infoは陣営を名乗らないので、その時点では区別できないからである。

陣営が確定するのは participants なので、**読み出し時に濾す**(`core.battle.opponent_hosts`
を `annotate_result` が呼ぶ)。保存dataは触らない — 勝敗判定と同じ方針。新規保存分は
`_battle_public` が濾した形で書く。

実dataでは **1,534戦のうち190戦(12.4%)** で味方が相手として記録されていた(延べ195 host、
最多は @viewer_12 の20戦)。これは配信者profileの対戦相手ranking・履歴カードの「vs」・
users表の対戦履歴に効く。participantsが陣営を持たない古い記録は判定材料が無いので触らない
(味方かどうか判らないhostを落とすと、本物の相手まで消える)。
