# Gifterの表示handle解決

gift集計が返す `unique_id` / `nickname` / `avatar` をどちらの値で出すか。

## 何が壊れていたか

通算集計のgifter一覧が **`COALESCE(NULLIF(MAX(e.user_unique_id), ''), u.unique_id)`** と
event側を優先していた。**`MAX()` は辞書順の最大を返すだけで「最新のhandle」ではない。**

実DBで踏んだ例:

| 表示されていた値 | 実際の現handle | 誤った理由 |
|---|---|---|
| `user5037930325926` | `harehare12345` | `u` > `h` で自動生成handleが勝つ |
| `user9487377432719` | `chikudenchi0807` | 同上 |

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
user5037930325926  -> harehare12345      coin=80958  (19 sessions)
user9487377432719  -> chikudenchi0807    coin=64921  ( 9 sessions)
user7686532416008  -> kent.d710          coin= 4548  ( 7 sessions)
dm08786581         -> jk08786583         coin= 1112
yami_topaichi      -> mochi_sokkin       coin=  309
Enigma SUMATA      -> Enigma JKSEX       coin=   15
sairuiu07          -> suikadayo0         coin=    2
mamacha1503        -> ochoolllee2        coin=    1
dunio.galo7        -> xinnwee            coin=    1
```

nickname の変化(71人)の方が件数は多い。最大は
「僕はよい、コインはもう無い。」→「┗┻(よい)┻┛ 3代目ガーディアン」(289,352 coin)で、
これは配信者側の改名が反映されていなかったもの。

avatar が855人と最多なのは、avatar URLが署名付きで頻繁に変わるため。`MAX()` の辞書順に
意味は無く、users表の「最後に観測した値」の方が意味を持つ。

## 影響の確認

- **consumer**: gifterの `unique_id` / `nickname` / `avatar` は全consumerで**表示専用**。
  `streamers.js` / `app.js` で `unique_id` を突合に使っている箇所はあるが、いずれも
  **配信者**や**Battle対戦相手**の識別で、gifterのそれではない
- **既存test**: `test_session_summary_aggregates_gifts_and_hides_missing_levels` と
  `test_battle_gift_contributions_uses_server_time_window` は、1人のuserが全eventで同じ
  handle/nicknameを使う組み方なので両方式で結果が一致する。**「壊れた挙動を固定していた
  test」は無く**、更新も不要だった
