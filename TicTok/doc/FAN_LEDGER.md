# Fan台帳

視聴者(fan)を主語に、誰がどの配信者へいつ幾ら投じたかを横断で見る画面。
`/fans` (`static/fans.html` / `fans.js`)、API は `GET /api/fans` と `GET /api/fans/{identity_key}`。

従来、視聴者を見る手段は「Session内のgifter順位」と「配信者内のgifter分析」だけで、
どちらも配信者の中に閉じていた。data上は `events.identity_key` で横断できるのに入口が無かった。

## 名寄せの前提

`identity_key` は不変user_id優先(user_id -> @unique_id -> nickname)で採番され、
session・配信者を跨いで同一視聴者を一意に指す。

### 台帳に載せない identity_key

`storage.NON_IDENTITY_KEYS = ("", "(unknown)")`

- `''` … 身元を採れなかったeventの現行表現。
- `'(unknown)'` … 表示用リテラルを名寄せkeyに使っていた時期の畳み込み跡。
  収集側は commit 022b2e0 で修正済みだが、**既存DBに残る行は別人が1 identityへ潰れたもので、
  分離に要る情報は失われており復元できない**。

どちらも「1人の視聴者」ではないため台帳から外す。ただし**黙って落とさない**:
除外したgiftの件数と額を `unidentified` として返し、画面の見出しに必ず出す。
そうしないと「台帳の合計がSessionのコイン合計と合わない」理由を画面から辿れなくなる。

実測(2026-07-20時点の本番DB): `(unknown)` は users 1行 / events 27件 / **gift 0件・0コイン**、
`''` は events 2,922件で gift 0件。gift集計への影響は現時点で無いが、
将来の収集分で発生し得るため除外と開示は常時行う。

## 集計方法

一覧は `events` を `kind='gift'` で絞り、**`(identity_key, 配信者)` で GROUP BY** して
Python側で畳む。1度の走査で通算と配信者別内訳の両方が出るので、内訳のために引き直さない。
queryの形は既存の配信者別gifter集計(`streamer_profile`)と同じで、配信者での絞りを外しただけ。

### 対象を gift送信者に限る理由

全kindを横断すると視聴者は**35,430人**規模になり(実測)、一覧として使えないうえ走査も一桁遅い。
gift eventを持つ視聴者は**1,134人**で、台帳の主題(誰が幾ら投じたか)と一致する。
commentのみの視聴者は含めない旨を画面に明記している。

### 表示handleは users 表を優先する

`COALESCE(NULLIF(u.unique_id, ''), MAX(e.user_unique_id))` の順。

`MAX(e.user_unique_id)` は辞書順の最大を拾うだけで「最新のhandle」ではない。実測では
改名前の自動生成handle `user5037930325926` が現handle `harehare12345` を押しのけ、
`user9487377432719` が `chikudenchi0807` を押しのけた。`users` 表は毎eventで最新へ
upsertされる唯一の真実なので、eventの値は users 側が空のときだけ使う。

> 既存の `streamer_profile` のgifter集計は `COALESCE(NULLIF(MAX(e.user_unique_id),''), u.unique_id)`
> の順(event優先)のままで、同じ理由で古いhandleを表示し得る。本台帳の範囲外のため未変更。

## 性能

`events` 437,698行に対する横断query。既存indexで足り、**index追加は行っていない**
(収集中の437k行tableへの書き込みcostを増やさないため)。

| query | 実測 |
|---|---|
| `GET /api/fans` | **0.24s** |
| `GET /api/dashboard`(既存・比較用) | 2.70s |
| `fan_profile` 1人ぶん | 0.15s |

`idx_events_kind_identity (kind, identity_key, diamonds, session_id, time)` が効き、
`sessions`(110行)とのJOINは実質無視できる。

検討して**捨てた案**: 「JOINを避けて session_id -> 配信者 をPython側で引く」。
実測で 91ms となり、素直にJOINする案(20ms)より**遅かった**。SQLiteは110行のtableとの
JOINを苦にせず、2列GROUP BYのtemp b-treeとPythonへの行数増加のほうが高くつく。

明細(`fan_profile`)は**生eventを返さない**。実測で最上位のfanは47,068行(大半がlike)を持ち、
明細として読めないうえ転送も走査も無駄になる。Session粒度まで畳んだものが台帳の単位である。

## 表示上の約束

### 配信者別の内訳は必ず額を併記する

実測では **286,946 対 3 コイン** のような極端な偏りが普通にある。「2人へ投げた」とだけ出すと
両方のファンであるかのように読める。一覧・明細とも額の降順で全内訳を出す。

なお複数配信者へ投げた視聴者は **gifter 1,134名中10名** しかいない。監視配信者が3名
(sessionを持つもの)しかいない以上、「配信者を跨ぐ動き」はこの範囲でしか観測できない。

### 「離脱」は判定しない

観測期間が約1か月しかなく、**「離れた」のか「たまたま来ていない」のかを分離する材料が無い**。
経過列は最終観測からの日数(`25 日前` / `24時間以内`)という事実だけを出し、
「離脱」「休眠」等の判定labelは付けない。並替で「最終観測が古い順」を選べば、
判断はoperatorが行える。

## 設定

設定画面「Fan台帳」

| key | 既定 | 内容 |
|---|---|---|
| `fan_min_diamonds` | 0 | 台帳に載せる最小のcoin額。0でgift送信者を全員 |
| `fan_limit` | 100 | 表示する最大件数 |

実測の絞り込み: 閾値 0 -> 1,134名 / 100 -> 198名 / 1,000 -> 97名 / 10,000 -> 23名。
