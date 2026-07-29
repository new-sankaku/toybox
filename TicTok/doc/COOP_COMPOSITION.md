# 共演構成(コラボ / Battle / ソロ)

配信者tabの「■ 共演構成」。配信時間をコラボ・Battle・ソロへ割り、配信1時間あたりの
回数まで出す。「この配信者はソロで回すのか、共演に寄せるのか」を1画面で見るための指標。

## 何をコラボと呼ぶか

コラボは**Battle以外のLinkMic**である。収集は `collect/collector.py` の LinkLayerEvent 側で、
channel単位に開閉して `collab_windows` 表(session_id / start / end / guests_max)へ落ちる。
BattleもLinkMicの上で起きるため、**同じ時間が両方の窓に入り得る**。

## 二重計上を避ける規則

秒の割り当ては次の順で固定する。analytics側の入室コンテキスト(`_payload_join_context`)と
同じ扱いで、画面ごとに定義が割れないようにする。

| 区分 | 定義 |
|---|---|
| Battle | Battle窓(重複除外後)を merge した秒 |
| コラボ | コラボ窓を merge し、**そこからBattle区間を差し引いた**秒 |
| ソロ | 配信時間 − Battle秒 − コラボ秒 |

区間演算は `tictok/core/intervals.py`(merge / subtract / total_span)に一本化してある。
analytics と storage が別実装を持つと、同じ画面の数字が片方だけ直った時に食い違う。

## 数える前に必ずclipする

窓は所属sessionの範囲へclipしてから数える。収集断でsession側が先に終わっている窓を
全長のまま足すと、比率が100%を超える。sessionの終端は `ended_at`、収集中のsessionは
「最後に何かが届いた時刻」(events / viewer_samples の最大時刻)を使う。開始時刻で潰すと
その配信の窓がまるごと落ちる。

分母(配信時間)と分子(共演の秒)は**同じsession集合**から採る。profileのsession一覧は
制限中を除いた直近 `limit` 件なので、窓もそのsessionのものだけを数える。

## 長さ0の窓は「1回」に数えない

実測(2026-07-27): `collab_windows` 506件のうち14件が start == end。いずれも配信終了の
直前に開いた窓で、finalize が同じ時刻で閉じたもの。秒の情報を持たないので、これを
1回に数えると「1時間あたりの回数」だけが持ち上がる。回数からも秒からも外す。

## 頻度は単独で読ませない

「1時間あたり何回」は総配信時間が短いほど跳ねる。KPI barには回数の実数と集計対象の
配信時間を並べて出し、頻度だけを切り出して見せない。

## 出口

- backend: `storage.streamer_profile()` の戻り値 `coop`(集計は純関数 `_coop_summary`)
- API: `GET /api/streamers/{unique_id}/profile`
- 画面: `static/streamers.js` の `renderCoop()`、内訳barは `.sm-mix`
- AI講評: `ai/review_digest.py` の `streamer_digest()` が「共演構成」として同じ値を渡す
