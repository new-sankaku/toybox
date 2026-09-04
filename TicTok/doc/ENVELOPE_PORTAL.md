# 宝箱(Envelope)とPortalの取り込み

coinを投じて視聴者を集める施策の実測を残す。`envelopes` 表(新規)。
収集は `collector._on_envelope` / `_on_portal`、参照は `GET /api/sessions/{id}` の `envelopes`。

従来は `_add_driver_marker` で時刻markerを1本落とすだけで、**payloadを1fieldも読んでいなかった**。
`markers` 表は `session_id / time / kind / label` の4列しかなく、投下額の置き場が無い。

## 実payloadで確認した事実(samples/)

`samples/EnvelopeEvent.jsonl`(4件)と `samples/PortalEvent.jsonl`(1件)を読んで確認した。

| business_type | 種別 | diamond_count | people_count | 送信者(実測) |
|---|---|---|---|---|
| 1 | 宝箱 (Treasure Box) | 20 | 16 | 配信者 @streamer_c |
| 4 | **Portal の送信** | 120 | 80 | 配信者 @streamer_c |
| 19 | Super Fan Box | **無し** | 1 | **視聴者** @streamer_f |

### 事前の想定と違った点

1. **`business_type=4` は Portal の「送信」である。** 表示文が
   `{0:user} sent a Portal. More viewers are on the way!`。つまり **Portalの送信は
   EnvelopeEvent で届く**。`PortalEvent` の方は Portal が**閉じた**ときの別messageで、
   `pm_mt_portalNew_liveComments_conversion_2`(「Portalが閉じました。多くの視聴者が
   参加しました」)を伴う。

2. **`business_type=19`(Super Fan Box)は `diamond_count` を持たない。** `people_count` のみ。
   0で埋めると「無料で配った」という観測していない事実になるので **NULL のまま残す**。

3. **送信者は配信者とは限らない。** 実測で bt=19 は視聴者(@streamer_f)が送っていた。
   「配信者が支出した施策」と決めつけられないので、送信者をそのまま保存して解析側が
   判断できるようにする。

4. **同じ `envelope_id` が2回届く。** `display: ENVELOPE_DISPLAY_NEW`(実測値あり)と
   `ENVELOPE_DISPLAY_HIDE`(`business_type`/`envelope_id`/`envelope_idc` のみ)。
   畳まないと1つの宝箱を2回数える。

5. **`create_time` はms文字列、`unpack_at` は秒int**と単位が混在する。既存の
   `_epoch_seconds`(桁で判定)で秒へ正規化する。

## 取得できないもの — Portalの流入元

**`portal_info` に移動元roomの識別子は無い。** payloadを全key走査して確認した結果、
`room_id` は受信側(自室)の1つだけだった:

```
portal_info = {"id": ..., "sender_id": ..., "trans_count": 24}
base_message.room_id = 7300000000000000203   # 自室
```

したがって「**どの配信者から流入したか**」は取得不能で、**「Portal経由で何人動いたか」
(`trans_count`)までが限界**である。ここを推測で補わない。testでも
`source_room_id` / `from_unique_id` のようなfieldを作っていないことを固定している。

## 送信と閉鎖はidで結合できない

実測値:

| | id |
|---|---|
| Portal送信 (EnvelopeEvent, bt=4) | `7300000000000000303` |
| Portal閉鎖 (PortalEvent) | `7300000000000000302` |

**別値**である。一方 `sender_id` は一致する(`7300000000000000101`)。
結合するなら「送信者 + 時刻の近さ」で寄せるしかなく、それは解析側の判断なので
**収集側では結合しない**。2行を別々に残し、`kind` で区別する。

## markerの不応期は残し、payloadは畳まない

`_add_driver_marker` の不応期は**そのまま**にし、payloadの保存は**別のgate**にした。

- 不応期は「1演出 = 1 mask onset」へ畳むためのもので、mask窓としては正しい。ここを外すと
  既存の解析(placebo除外)の窓が変わってしまう
- 一方**測定では1件ずつが別の支出**であり、時間で畳むと投下coinの合計が失われる

重複除外は **`envelope_id`(同一性)** で行う。時間窓より厳密で、実測のNEW/HIDEを正しく1件に
畳める。後から来た非NULL値で既存行を埋めるので、HIDEが先に届いても実測値は失われない。

## data model

```sql
CREATE TABLE envelopes (
    session_id, kind, envelope_id, time, create_time,
    business_type, diamond_count, people_count, trans_count, unpack_at,
    sender_user_id, sender_unique_id, data_json
);
```

`kind` は `'envelope'`(送信)と `'portal_closed'`(閉鎖時の実移動人数)。
保存は `save_envelopes` で **session単位の全置換**(battles / collab_windows と同じ冪等な作法)、
collector の既存 checkpoint(`_persist_progress`)に相乗りするので、収集中でも直近まで読める。

## 実sampleを通した結果

samples の実payloadをそのまま handler へ流した実測:

```
宝箱(Treasure Box)      20 coin  定員16   @streamer_c
Portal送信             120 coin  定員80   @streamer_c
Super Fan Box              —     定員1    @streamer_f   <- coinはNULL
portal_closed              —      —       実移動24人

投下coin合計: 140  (coin不明の宝箱: 1件 — 0で埋めていない)
Portal: 支出120 coin / 定員80 -> 実移動24人
```

4件のEnvelopeが**3行**になっている(NEW/HIDEが1行へ畳まれた)。

## 解析側への引き継ぎ(analytics.py は wave2-dwell 担当)

`_payload_peri` の baseline差分 + placebo窓の枠組みに、treatment を足すだけで載る。
**新しい枠組みは要らない。**

- **treatment時刻**: `envelopes.time`(受信時刻)または `create_time`(source時刻)。
  share/battle と揃えるなら create_time 側が一貫する
- **窓**: 宝箱は `time` 〜 `unpack_at` が「開封待ちで滞留させる」意図の区間なので、
  peri窓の自然な候補。`unpack_at` はNULLになり得る
- **ROIの分母**: `SUM(diamond_count)`。ただし **`diamond_count IS NULL` の行を0として
  合算しないこと**(Super Fan Boxが該当)。分母から除くか、別掲にするかは判断が要る
- **Portalは分けて扱う**: `business_type=4` の送信行が支出、`kind='portal_closed'` の
  `trans_count` が結果。流入元は取得不能なので「どこから来たか」は出せない
- **交絡**: 送信者が視聴者の回(bt=19)は「配信者の施策」ではない。
  `sender_user_id` を session の owner_user_id と突き合わせて分けられる

## 設定について

設定項目は**追加していない**。閾値も上限も無く、届いたものを実測のまま残すだけのため。
