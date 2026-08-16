# コラボ相手との対戦履歴(監視画面)

監視画面でコラボ(非BattleのLinkMic)が始まったら、その相手との過去の対戦成績を出す。
Battle paneのPK応援欄の上に積み、通算の勝敗・勝率・平均score、1戦ごとの表、
そして戦ごと/1戦の中のscore推移を出す。相手が誰かを思い出す前に、勝てる相手かどうかが
読める状態にするのが目的。

## 相手をどう突き止めるか

コラボのpeerは**数値user_idしか名乗らない**。LinkLayerEventの `linked_list[].link_user` は
proto上 `Player` で、持っているのは `room_id` と `uid` の2 fieldだけ ―― 表示名もavatarも
このeventには載らない。よって戦績は、配信者profileの対戦相手別集計(`battles`表由来)から
**user_id で** 引く。

そのために2箇所を揃えてある。

| 経路 | 変更 |
|---|---|
| `store/_common.py::_opponent_key` | 畳むkeyを **user_id 先頭** へ。以前はhandle先頭で、handleの載らない戦(実data 1921件中24件)が別人として割れ、実測13名が2行になっていた |
| `store/streamers.py::streamer_profile` | 対戦相手別に `user_id`、1戦ごとの履歴に `opponent_user_ids` を出す。keyの中身に頼らず突合できるようにするため |

実data(2026-08-09)での裏取り:

- 保存済みcollab窓のpeer 14件は **14/14** が過去の対戦相手とuser_idで一致した。
- `wicha_3111` の対戦相手 271行すべてがuser_idを持ち、対戦相手別の戦数と履歴の件数は
  相手ごとに完全一致(35戦→35件・22戦→22件…)。頭の数字と表の行数が食い違わない。

## 名前は相手のroom_infoから引く

戦績はuser_idで引けるが、**名前はそれでは足りない** ―― 一度も対戦していない相手は
対戦相手別集計に居らず、以前はそういう相手が `ID …末尾6桁` のまま並んでいた。

名前の出所は**相手のroom_id**である。`linked_list[].link_user.room_id` は届いており
(`core/collab.py::linkmic_state` が `peer_rooms` として返す)、その室の `room_info` を引けば
ownerの表示名・@handle・アイコンが取れる。自室のroom_info取得と同じ**unsigned GET**で、
sign APIを消費しない。

- 解決は `collector._resolve_peer_identities`。LinkLayer eventの処理(窓の開閉)は待たせず
  別taskへ出す。相手1人につき**process内で1回だけ**撃つ(LinkLayer eventは接続中ずっと
  届き続けるため、印は解決の前に付ける)。
- 結果は `users` 表へ残す(`save_peer_identity`)。`broadcaster` / `league_checked_at` には
  触らない ―― あれは「@handleで照会して確かめた」というリーグ取得workerの観測で、
  こちらは室を1つ見ただけである。判っている `broadcaster_room_id` だけ書く。
- 引いた室の主が相手本人でなければ**採らない**。別人の名前をコラボ相手として出すくらいなら
  IDのままの方が正しい。制限中・終了済みで引けない室も同じで、身元を持たないままにする。
- 画面は `peer_info`(解決できた相手だけを持つ)を対戦相手集計の名前より**優先**する。
  後者はその戦の時点の表示名で、改名やアイコン変更に追随しないため。

解決は接続の後から届くので、監視画面の再描画判定(`sig`)には「その相手の名前が解決済みか」
も入れてある。入れないと最初に配られたsnapshotのIDのまま固まる。

## 「今つないでいる相手」は和集合ではない

collectorのcollab窓は `peers`(窓の生涯の和集合)を持つが、これは保存形の値で、
入れ替わりのあるコラボでは今の顔ぶれにならない。live用に `now_peers`(この瞬間のroster)を
別に持ち、`collector.collab_snapshot()` はそちらを出す。保存側(`_collab_window_record`)は
従来どおり和集合を書く ―― `guests_max` の意味が変わってしまうため。

stateを配るのは**顔ぶれが変わった時だけ**。LinkLayer eventは接続中ずっと届き続けるので、
毎回broadcastすると監視画面へsnapshotを撒き散らすことになる(`_collab_signature()` で比較)。

## 出している数

- **通算**: N戦 W勝L敗(引分があれば併記)。勝率の母数は**決着した戦のみ**で、引分・未確定は
  分母に入れない。配信者画面の対戦相手別と同じ作法。
- **直近10戦**: 勝 / 負 / 分 / 未確定(未) を**古→新**で並べる。記号(●○)は塗りの向きを
  覚えていないと勝ちと負けを取り違えるので文字で名乗る。色は履歴表と同じ
  win=ok / lose=warn。1つ1つに日時と自陣/敵陣のscoreをtitleで持たせる。
- **平均**: 自陣 / 敵陣 と その差。個人の点ではなく陣営の点であることをlabelで名乗る。
- **戦ごとのscore推移**: その相手との全戦を古い順に、自陣/敵陣の2本。
- **1戦の中のscore曲線**: 行clickで `GET /api/sessions/{id}/battle-series/{battle_id}`。

## 相手の線は「敵陣」ではなく相手本人

`score_series.opp` は **max(opp_scores)** で、個人マルチ・チーム戦では最強の敵陣であって
コラボ相手本人の点とは限らない。1戦の曲線では `parts[]`(参加者別score)からその相手の
user_idを引いて描き、parts に居ない戦だけ敵陣へ落として **labelで「敵陣（最上位）」と
名乗る**。実data 977件中935件は相手本人のscoreが取れる。

同じ理由で、通算の平均は自陣/敵陣のまま出している。相手個人の平均まで出すなら全戦の
parts を走査することになり、profile 1回の重さが変わるため、このfeatureでは1戦側だけに
留めた。

## 1戦の曲線に専用routeを足した理由

`GET /api/sessions/{id}/battles` は貢献者一覧とグローブ判定まで含み、実測で
**session あたり中央値183KB・最大1.1MB**。曲線1本のためにこれを引かせない。
`battle-series` は該当1戦の `series` と `participants` だけを返す。

score推移が残っていない戦(989件中12件)では空を描かず「時系列が残っていません」と出す ――
空chartは「0点で推移した」に見えるため。

## 触った場所

| 層 | file |
|---|---|
| 収集 | `tictok/collect/collector.py`(`collab_snapshot` / `_collab_signature` / `_on_link_layer` / `_resolve_peer_identities`), `tictok/core/collab.py`(`peer_rooms`) |
| 集計 | `tictok/store/streamers.py`, `tictok/store/_common.py`, `tictok/store/users.py`(`peer_identities` / `save_peer_identity`) |
| API | `tictok/api/routes/sessions.py`(`/api/sessions/{id}/battle-series/{battle_id}`) |
| 画面 | `static/index.html`(`#collab-vs`), `static/app.js`, `static/style.css`(`.cvs-*`) |
| test | `tests/js/app.collabvs.test.js`, `tests/test_collect.py`, `tests/test_storage.py`, `tests/test_server.py` |
