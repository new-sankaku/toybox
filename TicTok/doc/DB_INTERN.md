# eventsの重複文字列のintern（`event_strings`）

`events` の1行は、そのeventが起きた時点でその人が出していた画像URLとbadge URLを丸ごと
持っていました。同じURLが何度も行に載るので、行数が伸びるほど同じ文字列の複製が積み上がる
構造になっていました。この文書は、それを別表の整数idで持つように変えた記録です。

**point-in-timeの意味は変えていません。** internは「同じ文字列を1度だけ持つ」ことであって、
「最新の1枚に寄せる」ことではありません。どのeventがどの画像を指すかは1行ずつそのままです。

## 直した問題（実測 2026-08-23 / events 1,256,138行 / DB 1,767.6MB）

| 列 | 値のbyte | distinct | 1行あたり |
| --- | --- | --- | --- |
| `user_avatar` | 342.1 MB | 292,114 | 273.8 byte |
| `user_gifter_badge` | 97.2 MB | **14** | 81.9 byte |
| `user_member_badge` | 74.7 MB | **19** | 62.9 byte |
| `contributor_samples.user_avatar` | 39.1 MB | 21,689 | — |

badge類は種類がLv別の固定画像しかありません。**31行の表で172MB**を持っていたことになります。
avatarは同じURLが平均4.3回でした。

### 結果

`1,767.6MB -> 1,262.6MB`（**-505.0MB / -28.6%**）。全1,256,138行 +
contributor_samples 141,708行を突き合わせて不一致0件で確認しています。

## avatarの伸びは止まりません（重要）

TikTokのavatar URLは署名付きで、`x-expires` / `x-signature` / `refresh_token` が回転します。

```
https://p16-common-sign.tiktokcdn.com/tos-alisg-avt-0068/<hash>~tplv-tiktok-shrink:72:72.webp
  ?dr=14561&refresh_token=...&x-expires=1781874000&x-signature=...&idc=my2
```

実在88,678人に対して、**新規のdistinct URLが3,735〜10,540件/日**発生します。したがって
internは伸びを止めるのではなく遅くします。

| | internなし | intern後 |
| --- | --- | --- |
| avatar | 5.11 MB/日 | 1.30 MB/日（うち1.23はintern表の伸び） |
| badge 2本 | 2.72 MB/日 | 約0 MB/日（種類が増えない） |
| 合計 | 7.83 MB/日 | 1.44 MB/日 |

DB全体は55MB/日で伸びており、この作業で削れるのは**6.4MB/日（約12%）**です。events の
値byteは実測14.57MB/日しかないので、残りはevents以外（indexを含む）から来ています。

### 署名を捨てればもっと効きますが、やっていません

保存済みavatar URLの**95.5%（1,190,818 / 1,246,969）は既に `x-expires` 切れ**で、現時点で
死んだlinkです（有効期限は発行から約2日）。`?` より前のpathだけなら全履歴で
distinct 111,444件・13.2MBしかなく、新規も1,529〜3,761件/日・0.18MB/日に落ちます。
path だけを持てば **-324MB / 伸び0.25MB/日** になります。

これは「保存する値を変える」判断であってinternではないので、**行っていません。**
判断が要るときはuserへ確認してください。なお「pathをinternしてqueryを行ごとに残す」
中間案は、queryが1行155byteで高cardinalityのため回収が130MBに下がり、素の全文intern
（-294MB）より**劣ります**。中間はありません。

焼き込み（burn-in）は `AvatarPool` が収集時に画像の実体をdiskへ保存しており、この列を
読んでいません。`events.user_avatar` の唯一の用途は画面のgifter一覧の表示です。

## 表の形

```sql
CREATE TABLE IF NOT EXISTS event_strings (
    id INTEGER PRIMARY KEY,
    hash INTEGER NOT NULL,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_strings_hash ON event_strings(hash);
```

- **`value` に UNIQUE を張っていません。** valueのUNIQUE indexは実測81.5MB（292k件 x
  274 byte）で、回収する294MBの28%をindexが食い潰します。hashのindexなら約4MBです。
  引くときは hash で絞ってから **value を実比較** するので、hashが衝突しても別idとして
  正しく扱われます（確率で無視しているのではありません）。
- **列ごとに表を分けていません。** `kind` 列も持ちません。同じ文字列がavatarとbadgeの
  両方で使われれば1行を共有します。対象列を増やすときは `_common.py` の
  `_INTERNED_EVENT_COLUMNS` / `_INTERNED_CONTRIBUTOR_COLUMNS` に1行足すだけで、DDLは増えません。
- **FKを張っていません。** この表は追記のみで行を消さないので伝播対象が存在せず、
  1 event毎にFK確認を払う理由がありません。
- **hashは `blake2b(value, 8byte)` です。** Pythonの `hash()` はPYTHONHASHSEEDでprocess毎に
  変わるため、保存すると次の起動で引けなくなります。桁数は設定にしていません — 変えると
  保存済みのhashが全て無効になり、「DBの中身と設定が食い違う」状態を作れてしまいます。

## 読み出し：`MAX()` の読み替えに注意

既存の7箇所はすべて `MAX(e.user_avatar)` の形でした。**これは「最新」ではなく文字列の
辞書順最大です。** `streamers.py` にも実例つきのcommentがあります（改名前の自動生成handle
`user5037930325926` が現handle `harehare12345` を押しのけた）。

したがって **`MAX(e.user_avatar_id)` への機械置換は誤りです。** idの最大は「最初に見た順」
であって辞書順ではありません。正しい書き換えは値へJOINしてからMAXを採る形です。

```sql
-- 誤り: idの辞書順ではない最大を採ってしまう
MAX(e.user_avatar_id)

-- 正しい
LEFT JOIN event_strings av ON av.id = e.user_avatar_id
...
MAX(av.value)
```

NULLと空文字の区別もこれで保たれます。NULL（計装前で未計測）の行はid列もNULLでJOIN先も
NULL、空文字（届いたが空）は `event_strings` に1行を持つので、
`NULLIF(MAX(av.value), '')` はinternの前後で同じに働きます。

読み出し側の劣化は軽微です。avatar/badgeを読む箇所はすべて `kind='gift'` で絞っており、
gift eventは30,893件（全体の2.5%）しかありません。実測で全期間のgift集計が46.7ms -> 50.3ms
（+8%）、session_summary相当が0.91ms -> 1.16msでした。

### `events` をVIEW化して読み出しSQLを変えずに済ませる案は採っていません

SQLiteのVIEWはindexが乗らず、`_reverse_link_identities` の `UPDATE events` や
`DELETE FROM events` が動かなくなり、plannerの挙動も静かに劣化します。

## 書き込み：bufferとjournalは生の文字列を運ぶ

```
add_event  --(生の文字列)--> buffer ---.
      `----(生の文字列)--> 耐久journal  |
                                       v
                        _drain（lock区間）で名寄せ -> id へ差し替え -> INSERT
```

`add_event` はDBに触れません（`_buf_lock` しか取りません）。名寄せはDB参照が要るので、
`_drain` の lock 区間の中 — `_write_batch_locked` の直前 — でだけ行います。

**journalに生値を残すのは意図的です。** eventsの行tupleをそのままjournalへ書いていた
既存の作りのまま列をidへ変えると、旧形式のjournal（15日保持・実測568MB）をreplayしたときに
**URL文字列がINTEGER列へ黙って入り**（SQLiteは動的型）、以後JOINが一致せずavatarが静かに
消えます。生値のままなら、今後intern対象の列を増やしてもjournalは無傷です。
`_iter_journal_rows` の行幅の正規化も位置固定のまま変わりません。

dead-letter（`storage_quarantine.jsonl`）へ書き出すのも生値です。人が読んで手で復旧する
fileなので、idだけでは復旧材料になりません。

### lock保持時間への影響

1 batch(50行)あたりのcache未hit値は実測 mean 11.98 / p95 28件です。未hitぶんは
**1 SELECT（hash IN …）+ 1 executemany** に畳んであり、1 event毎の別queryにはなりません。
新しいidは自前で採番します（writerが常に1つだけなので競合しません）。

`_drain` に増えた仕事（`_event_rows_for_insert_locked`）だけを切り出した実測：

```
mean 0.158ms / p50 0.150 / p95 0.235 / p99 0.298 / max 0.832
```

drain周期は最大0.2秒なので、duty cycleにして +0.1% です。

### rollbackでcacheを捨てること

rollbackすると `event_strings` へのINSERTも巻き戻ります。cacheがidを持ち越すと、以後の
eventが**存在しないidを参照する行**になり、JOINが一致せずavatarが消えます。
`_intern_forget_after_rollback()` がcacheと採番を捨てます。どのidが巻き戻ったかを追わずに
丸ごと捨てるのは、rollbackが失敗経路でしか起きず、hit率を惜しむ場面ではないためです。

呼ぶ場所：`_rollback_and_requeue` / `_write_isolating_locked` の入口 / journal復元の
rollback / `add_contributor_samples` の失敗時。

### process内cacheの上限

`_EVENT_STRING_CACHE_MAX = 40000`（`_common.py`）。**hit率のtuningではなくmemoryの天井です。**

| 上限 | 未hit/batch | 最終entry数 | memory |
| --- | --- | --- | --- |
| 5,000 | 12.38 | 4,972 | 2.0 MB |
| 40,000 | 12.33 | 37,986 | 15.3 MB |
| 無制限 | 12.32 | 147,868 | 59.6 MB |

上限を32倍にしても未hitは0.5%しか動きません — avatarのURLは署名が回転するので、未hitの
大半はどの大きさのcacheでも持てない初見の値だからです。cache自体は効いていて、cache無しの
31.46件/batchを12.32件へ61%減らします。効かないのは上限の大小だけなので、環境変数には
していません（`doc/SERVER_CACHE_BOUNDS.md` の `_USER_CACHE_MAX` と同じ扱い、同じ捨て方）。

## migrationは2段階

`_common.py` の `_INTERN_TARGET_PHASE` がどこまで進めるかを決めます。

| 段階 | 中身 |
| --- | --- |
| `EXPAND`(1) | `event_strings` とid列を作り、既存行のidを埋める。**旧列は残し、両方へ書く** |
| `CONTRACT`(2) | 全行の突き合わせを関門にして旧列を落とし、以後はid列だけへ書く |

**EXPANDを経由するのは、読み出し側7箇所の書き換えが1回では終わらないためです。** 両方の
列が同じ真実を持っている間は、書き換え済みの箇所と未着手の箇所が同じ答えを返します。
旧列を残したままでは1 byteも減らないので、EXPANDは通過点であって終点ではありません。

走る場所は `Storage.__init__` の**退避の後**の区間（`merge_cut_list_into_bookmarks` と同じ）
です。破壊的なので退避より前には置けません。

### 冪等・再開可能

id埋めの再開条件は「id列がNULLの行」という述語そのもので、10万行ごとにcommitします。
途中で落ちても次の起動が残りだけを進めます（やり直しではありません）。旧列はCONTRACTの
突き合わせを通るまで残るので、どの時点で止まっても真実は旧列側に在ります。

id埋めのあいだだけ `value` のUNIQUE index（`tmp_event_strings_value`）を張り、必ず落とします。
前回が張ったまま落ちていても、次の起動が `DROP INDEX IF EXISTS` してから張り直します。

### 全行の突き合わせが唯一の安全弁

```sql
SELECT COUNT(*) FROM events e LEFT JOIN event_strings s ON s.id = e.user_avatar_id
 WHERE e.user_avatar IS NOT s.value
```

`IS NOT` で比較します（`!=` はNULL同士でNULLを返して素通りします）。1行でも食い違えば
旧列を落とさずerrorを残して止まります。落としてしまえば元の値はどこにも残りません。
**この関門を外さないでください。**

### 段階は前へしか進みません

CONTRACT済みのDBで `_INTERN_TARGET_PHASE` をEXPANDへ戻しても、`_migrate` は空の旧列を
復活させません。復活させると書き込みはid列だけへ行くので旧列には黙ってNULLが並び、
旧列を読む箇所が「avatarが無い」と報告し始めます。判定は目標ではなく
**DBが実際にどこまで進んだか**（`db_maintenance` の `events_intern_phase`）で行います。

### 退避（`TICTOK_DB_BACKUP_BEFORE_MIGRATION`）

`_backup_before_migrations` の `has_rows` に **`events` を足しました。** 元は
`battles` / `transcripts` / `cut_list` しか見ておらず、この3表が空でeventsだけ在るDBが
**退避を取らないまま旧列を落とす**経路になっていました。

`_migration_versions()` にも `intern=<段階>` を載せてあります。段階が動いた起動で退避が
取られるので、EXPANDで一度止める運用なら2回、一度にCONTRACTまで進めるなら1回です。

### 何回の起動で走るか

**目標が最初からCONTRACTなら、EXPANDとCONTRACTは同じ起動の中で連続して走ります。**
`migrate_event_interning` がEXPANDを終えた後、`target >= _INTERN_PHASE_CONTRACT` を見て
そのままCONTRACTへ進むためです。「上げた次の起動でEXPAND、その次でCONTRACT」ではありません。

2回に分かれるのは、`_INTERN_TARGET_PHASE` をEXPANDに置いたまま先に読み出し側の書き換えを
載せる運用を採ったときだけです。読み出し7箇所を一度に直せない事情があるならそちらを、
既に7箇所とも直っているなら一度に進めて構いません。

### 所要時間

本番（1,256,138行 / 1,767.6MB）での実測です。目標をCONTRACTにして**1回の起動**で通しました。

| | 秒 | DB file | 備考 |
| --- | --- | --- | --- |
| （migration前） | — | 1,767.6 MB | |
| 退避（premigration・1.85GBの複製） | **22.0** | | `has_rows` に events が入っているので必ず走ります |
| EXPAND + CONTRACT（同じ起動の中で連続） | **121.2** | **2,042.4 MB（+274.8）** | 旧列を落としても**断片化のままなので減りません** |
| （起動全体） | 144.9 | | |
| VACUUM（手動・運用画面から） | **19.7** | **1,262.7 MB（-505.0）** | ここで初めて縮みます |

段階を分けた場合の内訳（copy DBでの実測）は EXPAND **70.8秒** / CONTRACT **34.4秒** で、
合計は一度に通した121.2秒とおおむね一致します。

**EXPAND中はWALが約1.1GBまで膨らみます**（実測 db+wal で最大3,170.2MB）。空き容量は
DB本体の2倍強を見ておいてください。WALは起動完了時のcheckpointで0へ戻ります。

つまり **EXPANDだけを走らせた時点では、DBは275MB大きくなり、良いことは何も起きません。**
EXPANDは読み出し側の書き換えを安全に載せるための通過点であって、成果が出るのは
CONTRACT + VACUUMの後です。**VACUUMを忘れると、DBは移行前より275MB大きいまま残ります。**

## VACUUMするまでfileは縮みません

**それどころか一時的に大きくなります。**

```
1,767.6 MB  migration前
2,042.4 MB  旧列を落とした直後（freelistには100.9MBしか載らない）
1,262.6 MB  VACUUM後
```

`DROP COLUMN` は行をその場で書き直すので、空いたのはpage内の隙間（断片化）であって空きpage
ではありません。新しい行は小さくなるので**伸びる速さはCONTRACTの時点で落ちます**が、
大きさが戻るのはVACUUMの後です。

VACUUMは自動では走らせません（`vacuum()` のdocstringの通り、実行中は全ての書き込みが
待たされます）。運用log画面の「Databaseの保守」panelから実行してください。

## 読み出し7箇所（すべて書き換え済み）

| file | 箇所 | 形 |
| --- | --- | --- |
| `store/users.py` | 1 | JOIN |
| `store/sessions.py` | 1 | JOIN（avatar + badge 2本） |
| `store/maintenance.py`（`_backfill_users`） | 1 | 実際に在る列で分岐 |
| `store/streamers.py` | 4 | JOIN x3 + **相関subquery x1** |
| `store/battles.py` | 1 | JOIN（avatar + badge 2本） |

旧列を読む形が残っていないことは、これで確かめられます（0件であること）。

```
grep -rn "MAX(e\.user_avatar)\|MAX(e\.user_gifter_badge)\|MAX(e\.user_member_badge)" tictok/
```

### 書き換えの型

```sql
-- 前
" COALESCE(NULLIF(u.avatar, ''), MAX(e.user_avatar)) AS avatar,"
" FROM events e JOIN sessions s ON s.id = e.session_id"
" LEFT JOIN users u ON u.identity_key = e.identity_key"

-- 後
" COALESCE(NULLIF(u.avatar, ''), MAX(av.value)) AS avatar,"
" FROM events e JOIN sessions s ON s.id = e.session_id"
" LEFT JOIN users u ON u.identity_key = e.identity_key"
" LEFT JOIN event_strings av ON av.id = e.user_avatar_id"
```

badgeも読んでいる箇所（`battles.py`）は3本のJOINが要ります。

```sql
" LEFT JOIN event_strings av  ON av.id  = e.user_avatar_id"
" LEFT JOIN event_strings gbv ON gbv.id = e.user_gifter_badge_id"
" LEFT JOIN event_strings mbv ON mbv.id = e.user_member_badge_id"
...
" NULLIF(MAX(gbv.value), '') AS gifter_badge,"
" NULLIF(MAX(mbv.value), '') AS member_badge"
```

**`streamers.py` の1箇所（top gifters）だけ形が違います。** 相関subqueryなので、
JOINを足すのではなくsubquery側を書き換えます。

```sql
-- 前
" COALESCE(NULLIF(u.avatar, ''), (SELECT MAX(user_avatar) FROM events"
"   WHERE kind = 'gift' AND identity_key = t.key)) AS avatar,"

-- 後
" COALESCE(NULLIF(u.avatar, ''), (SELECT MAX(s.value) FROM events e"
"   JOIN event_strings s ON s.id = e.user_avatar_id"
"   WHERE e.kind = 'gift' AND e.identity_key = t.key)) AS avatar,"
```

なお `streamers.py` の通算集計が読む `gifter_badge` / `member_badge` は `users` 表
（最新値）であってeventsではないので、そちらは触りません。

### CONTRACTへ上げるときの手順

`_INTERN_TARGET_PHASE` を上げることは、**次の再起動で本番のDBから旧列を落とす決定**です。
codeが揃っていることとは別の判断なので、上げる人を決めてください。

1. 旧列を読む形が残っていないことを上のgrepで確かめる（0件）
2. `_common.py` の `_INTERN_TARGET_PHASE` を `_INTERN_PHASE_CONTRACT` にする（1行）
3. `venv/Scripts/python.exe -m pytest tests/ -q -p no:randomly`
4. serverを起動する（退避 + 突き合わせ + DROPで約34秒 + 退避時間）
5. 運用画面からVACUUMを実行する（**これをやるまで縮みません**）

### EXPANDのまま検証する方法

EXPAND段階では旧列とid列の両方が埋まっているので、**同じDBに対して両方の形を流して
突き合わせられます。** CONTRACTへ上げてよいかの根拠はこれです。行ごとの同値が全行で
成り立てば、その上にどんな `MAX()` / `NULLIF()` を被せても答えは変わりません。

```sql
SELECT COUNT(*) FROM events e LEFT JOIN event_strings s ON s.id = e.user_avatar_id
 WHERE e.user_avatar IS NOT s.value        -- 0 であること
```

実測（本番の複製・1,256,138行）では、3列 + `contributor_samples` のすべてで0件でした。

さらに、**読み出し7箇所を旧列形へ戻したpackageの複製**を作り、同じEXPAND段階のDBに対して
新旧両方の**実際の公開method**を流して突き合わせました（SQLを書き写した近似ではなく、
画面が呼ぶ経路そのものです）。

| 対象 | 件数 |
| --- | --- |
| 配信者3名 x `streamer_profile` | 3 |
| 配信者3名 x `streamer_gifter_ranking`（day / week / month） | 9 |
| 配信者3名 x `streamer_history_stats` / `streamer_cohort` | 6 |
| `session_summary`（gift eventの多い順に20 session） | 20 |
| `battle_gift_contributions`（battle窓） | 300 |
| `aggregate_dashboard` / `streamer_index` / `session_rankings` | 3 |

**全44 keyが完全一致**。出力に載っていた空でないavatar/badgeの実値は新旧とも12,271個で、
「両方とも空だから一致した」のではないことも確かめています。

## test

`tests/test_intern.py`（15件）。固定しているのは主に次の4つです。

- 生の値がid経由で元のまま読み戻ること（NULLと空文字の区別を含む）
- bufferとjournalが生の文字列を運び続けること
- 旧列を落とすのは全行の突き合わせが通ったときだけであること
- rollbackで巻き戻ったidをcacheが持ち越さないこと

hash衝突は、同じhashを持つ偽の行を先に置いて確かめます（64bitで292k件に対し実際の衝突
確率は2.3e-9なので、待っていても起きません）。

## avatarの署名を落とす（internとは別の判断）

internは同じ文字列を1度だけ持つ変更で、記録の中身を変えません。こちらは**保存する値そのものを
変えます**。

avatarのCDN URLは「画像を指すpath」と「取得のたびに変わる署名query」でできています。1本301
byteのうち162 byteが署名で、署名の有効期限は約2日。保存済みの95.5%（1,190,818/1,246,969）は
既に切れています。

落として表示が壊れないのは、**表示がこの値を使っていない**からです。画面は必ず
`/api/avatar?u=<URL>&id=<unique_id>` の形で呼び（`static/common.js` の `avatarSrc`）、
`AvatarProxy._load_local` は **user_key(=id)のpoolを先に見ます**。poolは収集時にcollectorが
実体を保存したもので662,315件あり、URLは参照されません。poolに無いときだけURLでCDNへ行きますが、
その経路は95.5%が既に期限切れで機能していません。

badgeは対象外です。Lv別の固定画像で署名が付きません（実測 gifter 14種 / member 19種とも
query無し）。**avatarとbadgeが同じ `event_strings` 行を共有している例が1件ある**ので、行を
書き換えるのではなくavatar側のidを付け替えます。

### 実測（本番・1,256,138行）

| | |
| --- | ---: |
| 付け替え | 309,502値 → 1,388,452行 / **19.3秒** |
| 不要になった行の削除 | 309,502行 |
| `event_strings` | 309,629 → **115,137行** |
| DB file（VACUUM後） | 1,266.9 MB → **1,186.9 MB（−79.9MB）** |

**回収量が小さいのは、internが先に重複の大部分を畳んでいるからです。** intern前の状態から
数えれば署名込みintern −294MB に対し path-only intern −324MB で、差は30MB程度でした。
**この作業の本命は伸びの方**で、avatarの増加が **1.30 → 0.25 MB/日**（年約380MB）になります。

### 付け替えは1回のUPDATEで行う

`user_avatar_id` には**indexがありません**。値ごとに `UPDATE ... WHERE user_avatar_id = ?`
を投げると、29万値それぞれが125万行の全走査になり、実測10分でも終わりませんでした。対応表を
temp表へ置き、表ごとに1回のUPDATEで引き当てます。

