# 履歴: 下部dockの詳細と、複数Sessionのマージ表示

対象: `static/history.html` / `static/history.js` / `static/style.css`、
`tictok/api/routes/sessions.py`、`tictok/store/sessions.py`。

## 詳細は画面下部にdockする

Session詳細はfloating window(`.modal-overlay`)ではなく、一覧と同じ`app-shell`の中の
`#detail-dock`に置く。開いている間だけ`body.detail-docked`が付き、一覧は画面比15%の帯へ
畳まれ、残りを詳細が使う。閉じれば一覧が全高へ戻る。

floating windowでは一覧が覆われるため、詳細を読みながら次のSessionへ移れなかった。
dockは一覧と同時に見えている前提の作りで、次の3つが揃って初めて意味を持つ。

- 開いているSessionの行に`.sel`が付き、15%の帯の中へ`scrollIntoView`で連れ戻される
- 行そのものをclickしても開く(操作Button・Memo欄はclickを行へ伝えない)
- 閉じるとURLの`?session=`も戻る

## 入れ子scrollを作らない

規則は1つ。**1つの領域に対してscrollerは1つ。入れ子にするなら外側は絶対に転がさない。**

以前は詳細を段(Gift / Battle / コラボ / 録画 …)で縦に積み、各段の表に `max-height` の
内側scrollerを置いていた。この形は85%の領域がほぼ内側scrollerで覆われるため、wheelを
**始める**位置がまず内側になり、外側(`.modal-body`)へ手が届かない。`common.js`の入れ子
latch(`SCROLL_LATCH_MS`)は「動かし始めた後にpointerが内側へ入った」場合しか助けられず、
この状態は救えない。

今の形:

- 左の縦pane(`.dk-rail`)でカテゴリを選び、表示するのは常に1カテゴリだけ(`.dk-pane.on`)
- `.x-dock-panel > .modal-body` は `overflow: hidden` の固定高。**外側は転がらない**
- 転がるのは表示中のcard(`.dk-block`)の中の1枚だけ(`.table-wrap` / `.bcards` / `.dk-body`)

カテゴリは `DETAIL_CATEGORIES`(gift / battle / collab / rec / memo / ai / timeline)。
縦paneには件数を出す(`setRailCount`) — 0件も「0」で出す。空欄は「まだ読んでいない」と
見分けが付かない。選んだカテゴリは `tictok.history.detailcat` に残し、Sessionを渡り歩いても
同じ区画を見続けられるようにする。

`display: none` のcanvasは幅0のまま組まれる。カテゴリを表に出した瞬間に
`resizeChartsIn` が layout を確定させてから `chart.resize()` を呼ぶ。**rAFへ逃がしては
ならない** — 背面tabではrAFが回らず、戻ってきた時にchartが0×0のまま残る。

カテゴリの境は面と見出し帯(`.dk-block`)で示す。`■ 見出し` を地の上に置いただけでは
区画の切れ目が読めなかった。

## 一覧とdockの境

地の明度差(`--sand-bg` → `--sand-panel`)だけでは表の続きに見えたので、暗い構造線
(`--invert-bg`)を1本引き、dock側へ内側の影を落とす。見出し行は他の帯(topbar / KPI帯 /
toolbar)と同じ `--sand-bg-deep` の帯にする。区切りに `--accent` は使わない — あれは
「押せる」の色で、流用すると1色の意味が二重になる。

`@media (max-width: 60rem)`では`app-shell`が`height: auto`になりpage scrollへ移るため、
%のflex-basisが拠り所を失う。この幅では一覧を畳まず、詳細はその下へ流す。

## マージ表示

一覧の行頭のcheckで選び、「選択をマージ表示」でまとめて1つの詳細として開く。
URLは`?merge=1,2,3`で、共有・再読込・戻るButtonが効く。

### 合算はserver側でしか行わない

`Storage.sessions_summary(session_ids)`が`WHERE session_id IN (...)`＋`GROUP BY
identity_key`で畳む。**clientで各Sessionの結果を足してはならない**。理由は2つある。

1. 貢献rankingは`LIMIT 100`で切ってある。どのSessionでも101位のギフターは、Sessionごとの
   結果を足しても現れない。
2. 名寄せの鍵`identity_key`はAPIへ出していない。`@handle`で突き合わせると、改名したuserが
   別人に割れる。

`session_summary(session_id)`は`sessions_summary([session_id])`へ委譲するだけで、単体詳細と
マージ表示が同じSQLを通る。

### API

| endpoint | 返す物 |
|---|---|
| `GET /api/sessions/merged?ids=1,2,3` | `sessions` / `stats` / `summary` / `recordings` / `battles` / `collabs` |
| `GET /api/sessions/merged/export.csv?ids=…` | 全Sessionのeventを1本に。先頭2列が`session_id,session_unique_id` |
| `GET /api/sessions/merged/export.json?ids=…` | 合算 + Session別のevent |

`/api/sessions/merged`は**`/api/sessions/{session_id}`より前に宣言する**。後ろに置くと
`merged`が`session_id: int`に食われて422になる(`test_merged_sessions_route_is_not_shadowed_by_the_session_id_route`)。

一度に選べるSessionは`MERGE_MAX_SESSIONS`(500)まで。存在しないidが混ざっていれば404を返し、
黙って捨てない — 選んだ物と出た物が食い違うと合算を検算できない。

### 合算するもの / しないもの

`stats`のうち、`gifts` `diamonds` `comments` `likes_total` `follows` `shares` `joins`
`battles` `battle_points`は合算。`viewers_peak`だけは**最大値**を採る — 同時に居た人数は
足し算にならない。画面のchipも「最大同接(最大のSession)」と名乗る。収集時間は各Sessionの
長さの合算。

Battleは自陣がどちらかを`owner`で決めるが、配信者を跨いだ選択では1つに決まらない。
serverがBattleごとに`session_id`と`owner`を添え、`renderBattleCards`はowner解決関数も
受ける。カードの保持キーも`session_id:battle_id`にしてある(session跨ぎで`battle_id`が
衝突すると、並べ直しで1戦ぶん黙って消えるため)。

### マージ中に出さない区画

`#detail-dock.merged`で畳む。

`MERGED_HIDDEN_CATEGORIES`(history.js)がその可否の唯一の根拠で、縦paneのtabはJSが
`.hidden` を付けて畳む。CSSの見え方から判定すると、畳んだはずのカテゴリを開いたままに
できてしまう。

- **Session Timeline** — bucketは絶対時刻を持つ。別日のSessionを1本の軸へ並べても大半が
  空白になる。
- **平均同接** — 階段保持積分で宝箱窓を除いて出す値で、Session跨ぎでは積分をやり直さないと
  出せない。各Sessionの平均を平均すると、長さの違うSessionが同じ重みで混ざった別物になる。
- **AIコメント分析** — 保存済みの結果は文章なので足せない。選択分のコメントで回し直すなら
  別のjobになる。
- **Memo** — どのSessionへ書くか決まらない。

マージへ移った時に畳んだカテゴリを開いたままにしない(`openDock`がGiftへ戻す)。閉じた時も
同じ経路で戻す — でないと次に単体詳細を開くまでtabが消えたままになる。

## test

- `tests/js/history.dock.test.js` — dockの開閉・行click・選択の印・URL、カテゴリの件数と
  畳み、マージ表示の見出し・合算値・出力link・消えたSessionの掃除
- `tests/test_server.py`(`_merged_fixture`以下) — 合算・`viewers_peak`のMAX・route順序・
  入力checkと404・Battleのowner・merged CSVの列
