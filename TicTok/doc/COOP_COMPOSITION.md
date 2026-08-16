# 共演構成(コラボ / Battle / ソロ)

配信者tabの「■ 共演構成」。配信時間をコラボ・Battle・ソロへ割り、配信1時間あたりの
回数まで出す。「この配信者はソロで回すのか、共演に寄せるのか」を1画面で見るための指標。

## 何をコラボと呼ぶか

コラボは**Battle以外のLinkMic**である。収集は `collect/collector.py` の LinkLayerEvent 側で、
channel単位に開閉して `collab_windows` 表(session_id / start / end / guests_max)へ落ちる。
BattleもLinkMicの上で起きるため、**同じ時間が両方の窓に入り得る**。

## 判定ruleの版と、録画による検証

窓を作った判定ruleの版は `collab_windows.version`(`core.collab.COLLAB_WINDOW_VERSION`)に
記録し、**集計は現行版の窓だけ**を対象にする。版が上がると過去の窓は集計から落ちる。

| 版 | rule | 実測 |
|---|---|---|
| v1 | create/finish だけで開閉 | 配信尺の86.5%がコラボ。窓の中の大半がソロで**過大** |
| v2 | roster(誰がLINKEDか)で開閉 | 映像19.1h 対 窓17.7h。境界は秒単位で正しいが**数%過少** |
| v3 | v2 + 切断を「誰の切断か」で読み分け、繋いだまま終わった窓も確定 | 収集中 |

### 検証方法(録画映像との突き合わせ)

コラボ画面は9:16(720x1280)、ソロは1:2(640x1280。源側の画質低下で432x864等に落ちても比は
不変)なので、`ffprobe -skip_frame nokey -show_entries frame=pts_time,width,height` の走査で
映像側のコラボ区間を独立に出せる。keyframeだけで全frame走査と切替時刻は一致し、実時間の
約245倍速(18録画55.3hで約15分)。区間の終端は「最後のkeyframe」でなく「次の区間の開始」で
埋める — GOP(実測2秒)ぶん手前で切れる。

**この検証法の落とし穴が2つある。どちらも実際に誤検出を出した:**

- `pts_time` は録画のmedia軸**ではない**。幻jump segmentを除いたcurated playlistではpts軸が
  除外EXTINFぶん(実測264秒/2090秒)ずれ、その録画の突合が全滅する。信用できるのはplaylist軸
  (`-ss` で抜いたフレーム)の方。
- aspectでは**Battleとコラボを区別できない**(Battleも分割画面)。`battles` 表の区間を足してから比べる。

### v2で取りこぼしていたもの(v3の修正点)

18録画の照合で出た穴は、中間1586秒 / 録画末尾まで648秒 / 録画先頭から232秒 / 境界jitter 115秒。

- **他の参加者の離脱で窓が閉じていた**(最大成分)。`finish_content` が名乗るのは
  `owner:{room_id, uid}` = 終了したroomで、groupコラボでは他人のroomが入る。v3は名指しが
  自分なら切断、他人なら**その相手を外して残りが居ればまだ接続**と読む。
- **繋いだまま配信が終わった窓を捨てていた**。「最後までコラボを繋いだまま終わる配信は無い」
  という前提が実測で崩れた(3録画)。v3はsession終了時刻で閉じ、終端が実観測でないことを
  `closed_by: "session_end"` で名乗る。
- 接続時に既にコラボ中だと開始eventが無く拾えない件は**未修正**。TikTokは差分しか送らないため
  初期同期の材料が要る。診断設定 `linklayer_raw_capture` で生eventを
  `samples/raw/LinkLayerEvent_<session>.jsonl` へ全件残せる(1配信ぶん取れたら戻す)。

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
