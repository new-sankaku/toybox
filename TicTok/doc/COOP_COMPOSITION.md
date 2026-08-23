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
| v3 | v2 + 切断を「誰の切断か」で読み分け、繋いだまま終わった窓も確定 | 録画47本と照合。幻5.42h/取りこぼし4.46h。**退出snapshotで窓を開く欠陥** |
| v4 | v3 + 退出/取消/拒否のsnapshotのrosterを読まない、自室のゲストはco-hostに数えない | 同じ47本で幻0.11h/取りこぼし0.88h |

### v3で見つかった3つの欠陥(録画47本・33.3GB・映像38.36hとの照合)

**① 退出のsnapshotで窓が開く(幻3.95h)**。`group_change_content` の `source` は、その
snapshotが何の操作で出たかを名乗る(`click_quick_leave_button` 等)。退出のsnapshotは
**抜ける本人をまだLINKEDのまま載せた変化前のroster**で、v3はこれを「own LINKED +
他室LINKED」と読み、コラボが終わった瞬間に窓を開いていた。次のsnapshotが届くまで
(実測で最長1時間40分、その間eventは1件も来ない)ソロ時間をコラボに数える。この署名の
窓は14件・14,230秒あり、映像と一致したのは22秒(0.2%)だけだった。
→ v4は退出系sourceのsnapshotでは状態を変えない。開閉のどちらにも使わない。
退出の当事者(`biz_content` が名乗る)をrosterから外して読む案も試したが、groupコラボで
本物の窓まで閉じ、取りこぼしが0.88h→8.50hへ悪化したので採らない。

**② 配信が切れた後の再接続retry期間を飲み込む(幻79,922秒)**。配信が切れてもcollectorは
再接続を試み続け、sessionはその間開いたままになる(実測13.6時間/8.6時間、その間
viewer_sampleは0件でeventは全部`system`)。開いたままの窓をsession終了時刻で閉じると、
この尾を丸ごとコラボに数える。
→ 終端は `collector._open_collab_end` = **配信が生きていた最後の時刻**で頭打ちにする。
`_last_data_at` はcollector自身のsystem eventでも進むので使えない。配信由来のdataだけが
動かす `_last_stream_at` を見る。
なお「最後に接続を確認できた時刻」で切るのは**誤り**である。接続中にLinkLayer eventが
止まることがあり(実測で最長1時間40分)、切断eventも来ないままコラボが配信終了まで
続く。そこで切ると取りこぼしが0.87h→4.12hへ悪化する。

**③ serverが落ちると開いていた窓が消える(実測13/38 session)**。開いている窓はメモリに
しか無く、中間永続化は確定済みの窓しか書いていなかった。graceful終了なら
`_close_open_collab_windows` が先に走るので漏れない前提だったが、再起動・強制終了で
崩れる(sessionは起動時復旧が確定させるが、in-memoryの窓は知らない)。
→ `_collab_windows_public` は開いている窓も暫定の終端つきで書く(`closed_by: "open"`)。
保存はsession単位の全置換なので、窓が伸びれば上書きされ、閉じれば確定形に変わる。

### 版を上げてもdataを捨てない

判定ruleの版を上げると分析は現行版の窓だけを集計するので、過去の窓はすべて落ちる。
`linklayer_raw_capture` の生capture(`samples/raw/LinkLayerEvent_<session>.jsonl`)が
残っているsessionは `scripts/rebuild_collab_windows.py` で作り直せる。窓管理の手順は
collectorと同じものをscript側でも再現してある — 手順が割れると「作り直した窓」と
「これから収集する窓」が別ruleになる。生captureのJSONは**protoの型を連れて読む**こと
(betterprotoはprotoに在るfieldを未設定でも空messageで返し、無いfieldはAttributeErrorに
なる。判定はその差で枝を選んでいるので、素のdictだと `closed_by` が本番と違う名前になる)。

**④ 退出を一律に無視すると閉じる合図も消える**。①で退出系snapshotを無視した結果、
コラボが終わっても閉じる合図が無くなり窓が開いたままになる例が出た(実測47分)。
`leave_with_user_click_disconnect` は**自分が切った**ことの名乗りで、生captureの4件とも
映像のコラボはその1〜4秒後に終わっていた。rosterは変化前のままなので読まず、名乗り
だけで切断として扱う。似た値の `clear_cross_states:...userLeaveTriggerToIdle` は3件中
1件しか終端と一致せず(1件は730秒後、1件はコラボ中ですらない)、合図に使えない。

**⑤ 自室のゲストをコラボに数えていた**。`list_content` / `join_direct_content` の
`linked_list` に、相手の room_id が**自室と同じ**entryが来ることがある。co-hostではなく
自室へゲストを上げるmulti-guestで、group_change側は自室entryを `is_own` として既に
除いており、こちらだけ残っていた。実測1件(35分)を録画の実フレームで確かめたところ、
画面は最後まで配信者ひとりで共演は映っていない。

### v4の実測(録画47本で確定)

| closed_by | 窓数 | 秒 | 映像と一致 |
|---|---|---|---|
| join_direct_content | 93 | 90,814 | 99.7% |
| finish_content | 81 | 23,866 | 99.3% |
| session_end | 14 | 14,057 | 100.0% |
| group_change_content:own_disconnect | 4 | 3,373 | 100.0% |
| group_change_content | 7 | 3,206 | 99.7% |

**幻0.11h・取りこぼし0.88h**(v3は幻5.42h・取りこぼし4.46h)。残る取りこぼし2,756秒の
うち2,428秒(88%)は下記「接続時に既にコラボ中」の既知の穴で、録画の先頭から始まる区間
である。残り328秒は境界のjitter。

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
- 録画のHLSは2秒ごとの独立fileではなく、**packへまとめられ playlist が `#EXT-X-BYTERANGE` で
  その中のbyte範囲を指す**(実測: playlist entry 4,888件に対し実file 28個・pack平均349秒)。
  entryのfile名だけを見てpackごとprobeすると、**そのpackの先頭の解像度**しか判らず、pack途中の
  切替を取り落とす。packごとにkeyframeを全走査し、解像度が変わったkeyframeのbyte位置を
  BYTERANGEで時刻へ戻すこと。分解能はkeyframe間隔(実測2秒)。
- process起動が支配的な走査になりやすい。ffprobe 1回は実測51ms、うち34msがprocess起動で、
  file読みは0.3ms(512KB)しかない。entryごとに起動すると録画47本で20万回になる。
  pack単位なら1本あたり28〜52回で済み、同じ情報が得られる(実測4.7倍・33.3GBを552秒)。

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
