# Gift 演出 (animation) asset の取得可否

「TikTok の gift 演出 (画面全体に出る animation) を取得できるか。暗号化されていないか」
を実測で確認した記録。結論と、その根拠になった生 data を残す。

調査日: 2026-08-18 / 対象: `TikTokLive==6.6.5` の protobuf 定義と `webcast.tiktok.com` の実応答。

## 結論

**暗号化はされていない。** gift 関連の応答は素の JSON / protobuf で、asset は署名なしの
平 CDN URL (`UrlDataStruct` = uri + url_list + md5) として表現される。

取れないのは暗号化のためではなく、**演出 asset が gift panel の API に載っていない**ため。
gift panel が持つのは静止画と effect の id だけで、演出の実体は別 service が配る。

| 対象 | 現状 |
| --- | --- |
| gift の静止画 (icon / image / preview / label) | **取得可**。既に `tictok/media/gift_icons.py` が保存している |
| gift の演出 (全画面 animation) | **未取得**。gift list には URL も binary も含まれない |

## 実測: `/webcast/gift/list/` が返すもの

匿名 (未 login) の web client として取得した結果。

- gift 件数: 678
- `is_full_gift_data`: **false**
- gift 1件が持つ image field と出現数: `icon` 678 / `image` 678 / `gift_label_icon` 217 / `preview_image` 35
- 応答全体で `is_animated: true` の image: **0 件**
- `primary_effect_id` を持つ gift: 566 件
- `resource_id` を持つ gift: 599 件
- `gift_resources` が非空の gift: **0 件**
- top level の `gift_resource_group_map`: **空 dict**
- `gift_skins` (`animated_image` を持つ構造) が非空の gift: **0 件**

最高額 gift (id=9101 "TikTok Universe", type=2, `primary_effect_id=7305`) の icon を実際に
download しても、`~tplv-obj.webp` は静止 WebP (20,712 bytes, `ANMF` chunk 無し)、
`~tplv-obj.image` は静止 PNG (67,082 bytes)。**animation ではない。**

### request 条件を変えても変わらない

`device_platform` / `app_name` / `aid` を app 側の値に変えても、`is_full_gift_data=true` や
`fetch_giftlist_from` を足しても、結果は上と同一 (gifts=678 / gift_resources=0 / is_full=false)。

| 条件 | gifts | is_full | gift_resources 非空 |
| --- | --- | --- | --- |
| web_pc (既定) | 678 | false | 0 |
| android / musical_ly / aid=1233 | 678 | false | 0 |
| webcast_sdk | 678 | false | 0 |
| `is_full_gift_data=true` 付き | 678 | false | 0 |

なお `TikTokLive` の `fetch_gift_list(room_id=...)` は引数を受け取るが request に載せていない
(library 側の実装漏れ)。room 文脈を渡したい場合は `client.web.params` 側へ入れる必要がある。

## protobuf 上の構造 — 演出はどこにあるか

`Gift` message (`TikTokLive/proto/tiktok_proto.py`) に animation の実体を指す field は無い。

```
Gift.image / icon / preview_image / left_logo : ImageModel   # 静止画
Gift.primary_effect_id : int64                               # 演出の id のみ
Gift.gift_skins[].animated_image : ImageModel                # skin 付き gift のみ。実測 0 件
Gift.cross_screen_effect_info : 各種 effect_id の map        # id のみ
```

実体側は別 message にある。

```
AssetsModel.resource_uri / resource_model.url_list / md5 / size / download_type
ResourceModel.url_list : List[str]      # 平の CDN URL
EffectStruct.file_url : UrlDataStruct   # effect package の URL
ResourceAttr.gecko_attr.gecko_channel   # gecko (ByteDance の資材配布) channel 名
```

そして live の WebSocket には次が流れてくる。

```
WebcastEffectPreloadingMessage { gift_id: [int64], effect_id: [int64] }
WebcastAssetMessage { asset_id, assets: AssetsModel }
```

つまり **本家 client は「room に入る → 事前 load すべき effect_id を push で受け取る →
asset service から package を download する」**という流れで演出を得ている。
gift panel の API 単体では完結しない。

## asset service 側の実測

`webcast.tiktok.com` の path を総当たりした結果、asset 系で存在するのは 1 本だけ。

| path | 結果 |
| --- | --- |
| `/webcast/assets/list/` | HTTP 404 |
| `/webcast/asset/list/` | HTTP 404 |
| `/webcast/effect/list/` | HTTP 404 |
| `/webcast/gift/effect/` | HTTP 404 |
| **`/webcast/room/asset/list/`** | **HTTP 200 / `status_code=10013` / `data=null`** |

`/webcast/room/asset/list/` は実在する。ただし `room_id` / `asset_ids` / `resource_ids` /
`asset_type` を足しても `status_code` は 10013 のまま変化しない。**param 不足ではなく
session (msToken / sessionid) か署名を要求している**と読める。ここは推定で、確定していない。

## 取れない理由の分解

1. gift panel の API に演出 asset が載っていない (上の実測)
2. asset を配る `/webcast/room/asset/list/` が room 文脈と署名付き request を要求する
3. 仮に package を得ても、`AssetsModel.download_type` / `EffectStruct.file_url` が指すのは
   effect SDK 用の package であり、再生には対応する render engine が要る。
   **形式は未確認** — 実物を 1 件も取得できていないため、ここは断定しない。

暗号化は 1〜3 のどこにも出てこない。

## 演出を得たい場合の選択肢

いずれも未検証。採用時は user 承認が必要。

- **A. browser を実 room に接続して network を観測する。** 本 project は既に playwright を
  持っている。実 room を開いて gift 演出が再生される瞬間の request を記録すれば、
  asset の実 URL と形式が 1 回で確定する。**最も確実で、次にやるならこれ。**
- **B. WebSocket の `WebcastEffectPreloadingMessage` を購読する。** どの effect_id が
  その room で使われるかは取れる。asset の実体は取れないが、A の入口になる。
- **C. 演出を諦めて静止画で代替する。** 現状の burn-in は既にこの方針
  (`gift_icons.py` が gift_id 別に icon を disk へ持つ)。`preview_image` (35 件) は
  未取得なので、演出の代わりに使える余地がある。

## 現状 code が持っているもの

`tictok/media/gift_icons.py` は `persist_gift_list()` で `gift["image"]["url_list"][0]` だけを
`<gift_id>.img` として保存し、`names.json` に gift 名 → id の index を持つ。
CDN URL は後から 403 になり得るため、収集時 (URL が新鮮なうち) に落とす方針。
演出を扱うなら、この cache の隣に置く形になる。
