# Gifterの表示handle解決

gift集計が返す `unique_id` / `nickname` / `avatar` をどちらの値で出すか。

## 何が壊れていたか

通算集計のgifter一覧が **`COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id)`** と
event側を優先していた。**`MAX()` は辞書順の最大を返すだけで「最新のhandle」ではない。**

実DBで踏んだ例:

| 表示されていた値 | 実際の現handle | 誤った理由 |
|---|---|---|
| `user0000000000001` | `viewer_01` | `u` > `h` で自動生成handleが勝つ |
| `user0000000000002` | `viewer_02` | 同上 |

改名前の自動生成handle(`userNNNNNNNN`)は `u` で始まるため、**辞書順でほぼ必ず現handleに勝つ**。
改名した視聴者ほど壊れて見える、という性質の悪い壊れ方だった。

## 規則: 集計のscopeで決める

**一つの規則**であり、方式を2つ持っているのではない。

| scope | 優先 | 対象 |
|---|---|---|
| **session を跨ぐ通算集計** | **users表(最新)** | `streamer_profile` / `aggregate_dashboard` / `fan_ledger` |
| **session 単位の表示** | **event(point-in-time)** | `session_summary` / `battle_gift_contributions` |

- 通算集計には「そのSessionでの見え方」という基準が存在しない。数か月ぶんを1行に畳むので、
  **最新の身元で1人を1行に示す**のが正しい。`users` 表は毎eventで最新へupsertされる唯一の真実。
- session単位の表示は逆に**当時の見え方を保つ**のが目的である(`session_summary` の既存コメント
  「表示属性はその時(このSession)のsnapshotを優先し…過去の見え方を保持する」がその設計意図)。
  ここをusers表へ寄せると、過去のSessionを開いたときに当時と違うhandleが出る。

### session単位側は「意図は正しいが実装が弱い」

`MAX()` は point-in-time の実装としても正確ではない(session内で改名すると辞書順で拾う)。
ただし1 session内で改名する頻度は低く、**通算集計とはトレードオフが逆**なので今回は変更しない。
直すなら「そのsessionの最後のeventの値」を取る相関subqueryになり、コストと別の判断が要る。

## Lv / badge は対象外

`fans_level` / `gifter_level` / `gifter_badge` / `member_badge` は `users` 表への
fallbackを**持たない**(`NULLIF(MAX(e.user_...), 0)` のみ)。観測していない過去の値を
捏造しないための既存の設計で、今回の変更で巻き込んでいない。

## user_id は動かさない扱いだが、実測で差が無かった

`battle_gift_contributions` が返す `user_id` は**表示ではなく突合key**である
(`gift_by_id = {g["user_id"]: g}` で armies由来の貢献と数値IDで突き合わせる)。
ここが動くとBattle貢献の集計が変わる。

実測: gift送信者 **1171人**で `MAX(e.user_id)` と `u.user_id` の差は **0件**。
`identity_key` が user_id そのもの(不変ID優先で採番)なので、構造上一致する
(実測でも `identity_key == users.user_id` が 1165/1171)。
したがって通算集計側で `user_id` の解決順を揃えても突合は変わらない。testでも固定した。

## 実dataでの影響(2026-07-21時点)

gift送信者 1171人のうち:

| 項目 | 件数 |
|---|---|
| **@handle が変わる** | **9人** |
| nickname が変わる | 71人 |
| avatar が変わる | 855人 |
| **user_id が変わる** | **0人** |

@handle が変わる全9件:

```
user0000000000001  -> viewer_01   coin=80958  (19 sessions)
user0000000000002  -> viewer_02   coin=64921  ( 9 sessions)
user0000000000003  -> viewer_03   coin= 4548  ( 7 sessions)
oldhandle1         -> viewer_04   coin= 1112
oldhandle2         -> viewer_05   coin=  309
Enigma AAA         -> Enigma BBB  coin=   15
oldhandle3         -> viewer_06   coin=    2
viewer_09          -> viewer_07   coin=    1
oldhandle4         -> viewer_08   coin=    1
```

nickname の変化(71人)の方が件数は多い。最大は
「視聴者Cの旧名」→「┗┻(視聴者C)┻┛ 3代目ガーディアン」(289,352 coin)で、
これは配信者側の改名が反映されていなかったもの。

avatar が855人と最多なのは、avatar URLが署名付きで頻繁に変わるため。`MAX()` の辞書順に
意味は無く、users表の「最後に観測した値」の方が意味を持つ。

## 抜けていた経路: 配信者profileの Battle Gifter (2026-08-12 修正)

上の規則は「集計のscopeで決める」だが、**source のscopeと consumer のscopeが違う経路**が
1つ残っていた。

配信者profileの Battle Gifter は全期間の通算表なのに、値の出どころが session単位の
`battle_gift_contributions`(= point-in-time側)だった。そのうえ集約が `setdefault` なので、
**最初に当たったBattle の値で固定**される。処理順は `s.started_at ASC`(最古のsessionから)
なので、結果は「最新の名前」でも「そのsessionでの名前」でもなく、**その人を最初に観測した
頃の名前**だった。

| | Gifter一覧 | Battle Gifter(修正前) |
|---|---|---|
| 集計単位 | `identity_key` | `identity_key`(同じ) |
| 表示handle | users表(最新) | 最古sessionの `MAX()` |
| Fan台帳への導線 | あり | **`identity_key` を持たず不可** |

数え方(人数・コイン・Battle数)はどちらも `identity_key` 単位で最初から正しく、
**壊れていたのは表示だけ**である。改名した人が2つの表で別名に見え、同じ人なのに片方
からしかFan台帳へ飛べなかった。

修正: 集約後に `gifter_rows`(この配信者の全gift eventが母集合＝Battle Gifterの上位集合)
から最新の身元へ解決し直す。追加queryは無い。`battle_gift_contributions` 自体は
Battle card が point-in-time で使うので**変更していない** — 直したのは consumer 側である。

残る1経路: 収集中の配信では、`gifter_rows`(読取り接続)を読んだ後に届いたgiftが Battle側
(writer接続でflush済みを読む)にだけ現れうる。その1件は観測値のまま出て、次の読み込みで
最新の身元へ揃う。

## 影響の確認

- **consumer**: gifterの `unique_id` / `nickname` / `avatar` は全consumerで**表示専用**。
  `streamers.js` / `app.js` で `unique_id` を突合に使っている箇所はあるが、いずれも
  **配信者**や**Battle対戦相手**の識別で、gifterのそれではない
- **既存test**: `test_session_summary_aggregates_gifts_and_hides_missing_levels` と
  `test_battle_gift_contributions_uses_server_time_window` は、1人のuserが全eventで同じ
  handle/nicknameを使う組み方なので両方式で結果が一致する。**「壊れた挙動を固定していた
  test」は無く**、更新も不要だった
