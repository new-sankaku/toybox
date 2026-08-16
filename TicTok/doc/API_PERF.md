# API所要時間の計測

「画面が重い」を調べる口。遅かった1本のrequestを見ても答えは出ない — 1秒待たされる画面は
「1回800msの重いAPIが1本」でも「8msのAPIが100本」でも同じ体感になり、直す場所は違う。
ここは **route別の累計**と、1本の中で時間が **どこへ消えたか** の内訳を持つ。

実体は `tictok/core/perf.py`。集計はprocess内のメモリだけで、DBへは書かない
(計測する側が一番重い書き込みを増やすことになる)。再起動で消えるのは仕様。

## 見る場所

| 場所 | 内容 | いつ見るか |
| --- | --- | --- |
| 運用log画面の「API所要時間」 | route別の累計表(合計時間の降順) | 「どの画面が重いか」を知りたいとき |
| `GET /api/perf` | 同じもののJSON | scriptから比べたいとき |
| text/JSONL logの `http.perf_rollup` | 5分ごとの上位route | 後から「あの時間帯は何が重かったか」 |
| text/JSONL logの `http.request_slow` | 1秒超のrequest1本ずつ(内訳付き) | 特定の操作が遅かったとき |
| text/JSONL logの `http.loop_lag` | event loopが止まった瞬間と、その時いたrequest | 全画面が同時に固まるとき |

並びは **合計時間の降順**で、1回の遅さの順ではない。1回3秒でも日に1回しか呼ばれない
routeより、40msでも毎秒叩かれるrouteの方がserverを占有している。

## 内訳の読み方

| 名前 | 中身 |
| --- | --- |
| `db.read` | 集計read専用接続でのSQL |
| `db.read_wait` | その接続の順番待ち(接続は1本で直列化されている) |
| `db.write_conn` | 書き込み接続でのSQL(読み取りもここを通るものがある) |
| `db.write_wait` | 書き込みlockの順番待ち。ここが大きい＝collectorの取り込みと競合している |
| `fs.stat` / `fs.scan` / `fs.walk` | 個別stat / dir 1回読み / 配下の再帰走査 |
| `proc.ffprobe` | 子processの起動から終了まで |
| `net.embed` | 外部のAI serverへのHTTP(意味検索の埋め込み) |
| `analytics.payload` / `analytics.reduce` | session単位の中間集計 / 横断集計の計算 |
| `other` | 計測点の外。応答の組み立て・JSON化・awaitの待ちがここ |

積むのは各区間の **自分の時間**(経過 − 内側の区間の合計)なので、内訳の合計が全体を
超えない。`other` が支配的なrouteは、次に計装を足す場所そのものである。

## 設定

すべて環境変数。既定のままで運用してよい。

| 変数 | 既定 | 意味 |
| --- | --- | --- |
| `TICTOK_PERF_ENABLED` | `1` | 計測そのもの |
| `TICTOK_PERF_SAMPLE_WINDOW` | `512` | 分位数を出す標本数(routeごと) |
| `TICTOK_PERF_ROLLUP_SECONDS` | `300` | 集計logの間隔。0で止める |
| `TICTOK_PERF_ROLLUP_TOP` | `8` | 1行に名指しするroute数 |
| `TICTOK_PERF_MAX_ROUTES` | `400` | 追跡するroute数の上限 |
| `TICTOK_PERF_LOOP_LAG_INTERVAL_SECONDS` | `0.5` | loop遅れprobeのsleep |
| `TICTOK_PERF_LOOP_LAG_WARN_MS` | `500` | 遅れを書き出す閾値 |
| `TICTOK_LOG_SLOW_HTTP_MS` | `1000` | 1本ずつlogに残すrequestの閾値 |

## 計測の費用

`SELECT 1` 級の軽い文1回あたりの実測(Python 3.10 / Windows):

| 経路 | 1回 |
| --- | --- |
| 素の `sqlite3.Connection.execute` | 0.75μs |
| 計測付き・requestの外(collectorの取り込み・録画・起動時migration) | 1.02μs |
| 計測付き・request処理中 | 3.07μs |

requestの外では ContextVar を1回読むだけで素の実装へ抜ける。実際に見たいqueryは
20〜200msの世界なので、request中の +2.3μs は比率として現れない。

## 前後を比べるとき

累計のままだと、直した後の速い呼び出しが古い遅い呼び出しに薄められる。運用log画面の
「計測をreset」(`DELETE /api/perf`)で区間を切ってから操作すること。

DBの読み取りを変える場合、実DBを2回読んで比べても収集が進むぶんの差が出る。
`sqlite3.Connection.backup` でsnapshotを1つ作り、それに対してA/Bを取る。

## これまでに見つけて直したもの

| 対象 | 前 | 後 | 原因 |
| --- | --- | --- | --- |
| `GET /api/streamers` | 208ms | 4.4ms | 未確定sessionの通算CTEが、未確定が2件でも events index を全走査していた。結合順を未確定側から回すよう固定 |
| `GET /api/dashboard` | 486ms | 56ms | 同じCTEを2回使っている。加えてgifter上位50が全gift eventで行本体を読んでいたのを2段構えへ |
| `GET /api/search/status` | — | — | 36万行のindex走査をevent loop上で回していた(別threadへ)。search_hitsの集計2本を書き込み接続から集計read専用接続へ。※このendpointは後に廃止し、集計は `GET /api/bulk/status` へ一本化した(同じ走査を2箇所で回していた) |

いずれも結果が変わらないことをsnapshot上で突き合わせて確認済み。
