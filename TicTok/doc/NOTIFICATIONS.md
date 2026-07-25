# 通知(Alert)基盤

## 何のためにあるか

このtoolは無人運転が前提であるにもかかわらず、これまで外部への通知経路が1本も無く、届くのは
画面を開いている間のWebSocket broadcastだけでした。そのため「配信の切断や録画の失敗に翌日まで
気付かない」という失敗を構造的に防げませんでした。この機構はその1点を埋めます。

## 設計

判定材料は既に揃っていたため、新しい観測は足していません。

| 事象 | 取得元 |
| --- | --- |
| LIVE開始 | `ops_events` の `session.started` |
| 切断・録画停止・再接続の打ち切り・録画不可判定・job中断 | `ops_events` のseverity |
| coin急増 | collectorが毎回算出している直近1分のcoin量(`stats.rate_diamonds`) |
| Battle開始 | collectorの `_on_battle`(窓が開く分岐) |

`ops_events` は障害系と状態遷移の単一の口として既に成立しているため、通知はそこへ観測者を
1本ぶら下げるだけにしてあります(`Storage.set_ops_observer`)。各所へ通知用の計装を足していく
方式は採っていません。

`core/spike.py` の z-score 判定は使いません。あれは母集団をsession内に閉じることで「配信ごとに
規模が桁で違う」問題を回避する事後解析用の判定であり、bucketが `MIN_BUCKETS` 未満の配信開始
直後には値を出せません。通知は配信の頭から効いている必要があるため、coin急増は絶対値の閾値
(coin/分)で判定し、spike.pyの設計意図には触れていません。

### 層の分割

* `tictok/core/alert.py` — 判定と重複抑止。I/Oを持たないので、serverもwebhookも起こさずにtestできます。
* `tictok/core/notify.py` — 送信(webhook)。唯一のI/O境界です。

### 通知が本体を止めないこと

`Notifier.submit` はthread safeかつnon-blockingで、例外を呼び出し元へ返しません。実際の送信は
serverのevent loop上の単一workerがqueue越しに行います。collector・recorder・DB書き込みthreadの
どこから呼ばれても、収集と録画は通知の成否に影響されません。

## 宛先の設定

宛先URLは設定画面ではなく `TicTok/.env` に置きます。

```
TICTOK_NOTIFY_WEBHOOK_URL=https://discord.com/api/webhooks/xxx/yyy
```

設定画面(DB)に置かない理由は、webhook URLがそれ自体で投稿権限を持つ資格情報であり、
設定画面の値は (a) 画面に平文で表示され、(b) 変更時に `Settings.update` が old -> new を
`ops_events` へ書き込み、保持期間ぶん残るためです。資格情報の置き場は既にEulerStream API keyで
`.env` と決まっているので、そこへ揃えています。

カンマ区切りで複数指定でき、全宛先へ同じ通知を送ります。変更後はServerの再起動が必要です。

### payload形式

`TICTOK_NOTIFY_WEBHOOK_FORMAT`(既定 `auto`)で決まります。`auto` は宛先hostから判定し、
判定できないものは汎用JSONになります。`discord` / `slack` / `generic` を明示すると全宛先を
その形式で送ります。不正な値はエラーにします(既定へ黙って倒しません)。

汎用JSONのbody:

```json
{"source": "tictok", "text": "...", "alert": {"rule": "...", "severity": "...", "detail": {}}}
```

### その他の環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `TICTOK_NOTIFY_QUEUE_MAX` | 500 | 送信待ちの上限。超過分は破棄し、破棄したことを `ops_events` に残す |
| `TICTOK_NOTIFY_SHUTDOWN_DRAIN_SECONDS` | 5.0 | 終了時に送信待ちを吐き切るのを待つ秒数 |

## 設定画面(通知(webhook))

閾値・有効無効・retryは全て設定画面から変更できます(hard-codeしていません)。

| key | 既定 | 内容 |
| --- | --- | --- |
| `notify_enabled` | しない | 通知全体のON/OFF |
| `notify_rule_live_started` | する | 監視中の配信者のLIVE開始 |
| `notify_rule_ops` | する | 障害・状態遷移(運用log連動) |
| `notify_ops_min_severity` | warning以上 | 上記で拾う範囲 |
| `notify_rule_battle_started` | しない | Battle開始 |
| `notify_rule_coin_rate` | しない | coin急増 |
| `notify_coin_rate_threshold` | 10000 | coin急増と判定する量(coin/分) |
| `notify_refractory_seconds` | 300 | 同一事象を再通知しない秒数 |
| `notify_retry_max` | 3 | 送信失敗時の再試行回数 |
| `notify_retry_base_delay` | 2.0 | 再試行の初回待機秒数 |
| `notify_timeout_seconds` | 10.0 | 1回の送信のtimeout |

## 重複抑止

抑止したい重複が2種類あるため、機構も2つ持っています。

* **不応期(refractory)** — 同じ事象が短時間に何度も記録される場合(再接続の繰り返し等)を
  時間窓で畳みます。keyは「配信者 × ruleまたはops kind」単位です。severityで畳むと、再接続の
  打ち切りと録画停止が同じ枠を奪い合って片方が消えます。
* **立ち上がり検出** — coin急増のような閾値判定は、閾値の上に居る限り条件を満たし続けるため、
  時間窓だけでは不応期が明けるたびに鳴り続けます。「下→上」に変わった瞬間だけ発火させます。
  Battle開始も同じ仕組みで1戦1件に閉じています。

## 送信失敗の扱い

握り潰しません。

1. 設定回数まで再試行します(待ち時間は倍々)。
2. 4xx(429以外)は再試行しても結果が変わらないため、回数を待たずに打ち切ります。
3. 諦めた時点で `ops_events` に `notify.delivery_failed` をerrorとして記録します。
4. queue溢れで破棄した場合は `notify.queue_overflow` を記録します。

`notify.` で始まるkindのops_eventは通知対象から除外しています。除外しないと、送信失敗の記録が
次の通知を生み、それがまた失敗する無限循環になります。

## 動作確認

設定画面の「通知の宛先」cardの「テスト通知を送る」で、実際にwebhookへ1件送信し、その結果
(HTTP status)を表示します。queueを通さず同期送信するのは、「積めた」ではなく「届いた」を
確かめるためです。

## 実装していないもの

**desktop通知(toast)** は実装していません。Windows/Linuxで別々の追加libraryが必要になるうえ、
このserverは無人運転で常時上がっている前提であり、toastは画面の前に人が居るときにしか届き
ません。それはWebSocket broadcastで既に満たされている条件で、この機構が埋めようとしている穴
(「画面を見ていない間に起きたことに気付けない」)には届きません。webhookはphoneまで届きます。

**通知履歴の一覧(既読/未読)** も作っていません。通知の実体は `ops_events` の行そのもので、
それを読む導線は運用log画面として既にあります(severity・kind・配信者・期間で絞れ、keyset
pagingも実装済み)。別の履歴表を作ると同じ事象が2箇所に記録され、どちらが正かという問題を
新たに作ります。既読/未読も、通知の宛先(Discord/Slack)側が既に持っている機能です。
