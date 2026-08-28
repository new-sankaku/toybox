# ギフト演出(animation)を取得しない理由

TikTokのgiftには、iconとは別に**画面へ流れるanimation(演出)**がある。これを録画へ入れる、
あるいはasset単体で取得する道を一通り当たった記録。**結論として、asset経路は制度的に閉じて
おり、採るなら「描かれた結果を画面から採る」しかない。**

同じ問いが再燃したときに、同じ調査を繰り返さないための記録である。「未検証」と書いた項目は
本当に未検証であり、埋めた項目は実測値を併記した。

## 結論

| 経路 | 可否 | 理由 |
|---|---|---|
| 録画に写り込ませる | **不可** | 演出はclient側で合成される。録画はstream copy |
| eventからasset URLを得る | **不可(実測)** | eventが持つのはIDのみ。gift listにresourceは1件も無い |
| IDからasset URLを引く | 未特定 | 引く口が公開libに無い。endpointの存在は判るが未到達 |
| assetを再生する | **不可** | engineが商用license制で、licenseは自分の素材にしか効かない |
| 画面から採る | **これだけが残る** | 差分マッティング。Webを第一候補、Androidを代替 |

**asset経路は追わない。** endpointを突き止めても、暗号化されていなくても、再生する手段が
無い。以下はその各段の根拠である。

## 1. 録画には映らない

録画は配信のHLSを**stream copy**している(`record/recorder.py`)。演出は視聴client側で合成
される層なので、原理的に入らない。`record/video_overlay.py` が自前でGift演出を焼いているのは
この帰結であって、好みの問題ではない。

音だけは例外で、gift SEはTikTok側でmix済みの1 trackに入っている(`doc/AUDIO_NORMALIZE.md`)。
「音は録れているのに絵が無い」のはこのためで、収集の欠落ではない。

## 2. eventが持つのはIDだけ (実測)

`TikTokLive==6.6.5` のprotoを展開した結果、`Gift` messageが演出について持つのは全てIDである。

| field | 型 | 中身 |
|---|---|---|
| `primary_effect_id` | `int` | 演出のID。URLではない |
| `is_effect_b_e_f_view` | `bool` | 端末側effect engineで描く印 |
| `cross_screen_effect_info` | `Dict[int,int]` ×3 | effect IDの対応表 |
| `random_effect_info.effect_ids` | `List[int]` | 同上 |

`collect/collector.py` は `m_gift`(Gift message)自体を `_EXTRA_FIELDS` から除外しているので、
**`primary_effect_id` は保存すらしていない**。列に昇格させる価値が出たときは、ここを開ける。

唯一の例外が `WebcastGiftMessage.asset`(`AssetsModel`)で、これは `_EXTRA_FIELDS["gift"]` に
入っているため **`events.extra` へJSONで残っている**。`resource_model.url_list` /
`video_resource_list[].video_url` / `md5` / `size` を持つ。実DBでの被覆は未検証:

```sql
SELECT COUNT(*) AS gifts,
       SUM(json_extract(extra,'$.asset') IS NOT NULL) AS with_asset,
       SUM(json_extract(extra,'$.asset.resource_model.url_list[0]') IS NOT NULL) AS with_url
FROM events WHERE kind='gift';
```

## 3. gift listにresourceは入っていない (実測)

本番の `/webcast/gift/list/` を実際に叩いた結果(2026-08-28、gift 722件):

| 確認項目 | 結果 |
|---|---|
| `primary_effect_id` が非0 | **608 / 722** |
| `gift_resources` | **722 / 722 が空 `{}`** |
| `gold_effect` / `cross_screen_effect_info` | 空文字 / null |
| `image`・`icon` が `is_animated` | **0 / 722**(全て静止webp) |

**IDは配るが、解決したresourceは同じ応答に一切入っていない。** icon側にanimationがある訳でも
ないので、代替にもならない。

ID→URLを引く口については:

- `TikTokLive` のweb routeは13本で、effectを引くrouteは無い(`client/web/routes/`)
- 一方protoには `EffectListResponseData`(`effects` / `url_prefix`) と
  `EffectStruct`(`file_url` / `package_size` / `sdk_version` / `model_names` / `requirements`)
  が定義されている。**endpoint自体は存在するが、公開libがその口を持っていない**
- 当て推量で4本叩いたが全滅(`webcast/effect/list/` 404 / `webcast/gift/effect/` 404 /
  `effect.tiktokv.com` 到達不可 / `effect.tiktok.com` 502)

`url_prefix` が `List[str]`、`file_url` がURL、`package_size` が整数であることから、実体は
**catalog API + CDN上のpackage file**という構造だと読める。gift iconと同じ形で、置いてある物が
packageという違いである。

## 4. 仮にassetを取れても再生できない

ここが決定打で、**上の3を解いても無駄になる**理由。

packageを解釈するのはByteDanceの **Effects SDK**(海外はBytePlus、中国は火山引擎)。
隠蔽されてはおらず、docもSDKも公開されている。ただし:

- **年額licenseの商用製品**で、価格は非公開の個別見積り
- license fileは **ApplicationID / BundleID と有効期限を検証**し、合わなければSDKはfailする
- そして、

  > The license **only takes effect** **for its matched materials**.

**licenseは「そのlicenseに紐付いた素材」にしか効かない。** TikTokのgift packageはTikTok自身の
licenseに紐付いた素材なので、こちらがlicenseを買っても再生できない。

暗号化の有無はこの件では関係がない。仮に平文のZIPでも、中身は動画ではなくengine向けのbinary
資産(texture / mesh / shader / scene定義)であり、ffmpegには渡せない。

## 5. 「正解動画」が存在しない演出が有り得る (補強材料。確度は低い)

**この章は4章の補強でしかない。** 荷重を持つのは4章であり、ここが崩れても結論は変わらない。
確度が低いことを承知の上で読むこと。

TikTokのEffect House(効果制作用の無料desktop app)で、**LIVE Interactive Gift Effect Challenge**
というコンテストが開催された実績がある。効果をZIP(デザイン + 動作録画)で提出させるもので、
募集categoryが4つあった:

| 種別 | 内容 |
|---|---|
| Style Gift | 見た目を良くする |
| Appreciation Gift | 感謝を表現する |
| **Performance-Amplifying Gift** | **配信者の動きに同期する** |
| LIVE Stream-Enhancing Gift | 没入感を上げる |

3つ目のような、**実行時入力に依存して絵が変わる**演出が求められている。もし稼働中のgiftに
この種別が含まれるなら、その演出には「正解動画」が存在せず、asset経路が仮に全部通っても
動画にはならない。

**ただし以下は確認できていない:**

- **入賞作が実際に販売中のgiftになるのか。** コンテストの要項には賞金(11名 / $100〜$2,000)しか
  書かれておらず、採用経路には触れていない
- **稼働中の722種を誰が作っているのか。** 「TikTok純正とサード製の区別が無い」と読める材料は
  無い
- `effecthouse.tiktok.com/live-gift` の本文。JS描画で3回試してtitleしか取れなかった

つまり「動きに同期する演出が存在する」ではなく、「**そういうcategoryで募集された実績がある**」
までが確認できたことである。ここを根拠に方針を決めてはいけない。

## 6. 採るなら画面から (差分マッティング)

静止画配信(動きの無い配信)を選べば、背景が既知の定数になる。clientがその上に描いた層だけが
差分として残るので、演出をalpha付きで取り出せる。

**背景は黒っぽい静止画を選ぶ。** 背景が黒なら観測値がそのままpremultiplied alpha(α·F)になり、
加算合成でそのまま焼ける。半透明のグローや粒子まで出る。緑や白だと半透明部のαと色を分離
しきれず、縁に背景色が残る。

### WebとAndroidの比較 — Webを先に試す

| | Web (Chromium) | Android app |
|---|---|---|
| 演出を描くか | **未検証(唯一の弱点)** | 確実に描く |
| 無人運用 | containerで長時間・並列可 | 端末占有 / `screenrecord` は1回3分 |
| **UIの除去** | **CSSでcomment層等を消せる** | 消せない。差分に全部乗る |
| **背景の正解** | **`<video>` を別取得できる** | 画面から推定するしかない |
| secure surfaceでの黒抜け | 無関係 | リスクあり |

差分マッティングの最大の敵は「演出以外のclient UIが差分に乗る」ことで、browserならCSSで消せる。
さらに演出が独立したcanvas / DOM層に描かれているなら、**その層だけを透過で取れてマッティング
自体が要らなくなる**。

よって順序は、**Webで「描くか」だけ確認 → 描けばWebで採取、描かなければAndroidへ退避**。

Androidへ退避する場合、Root無しで通るのは画面録画だけである:

| やりたいこと | Root無しで | 手段 |
|---|---|---|
| 画面の録画(演出込み) | できる | `adb shell screenrecord` / scrcpy |
| 差分マッティング | できる | 上の録画を処理するだけ |
| HTTPS傍受(URL採取) | **できない** | cert pinning + Android 7以降のuser CA不信任 |
| app内部cacheの直読み | 原則不可 | `/data/data/...` はroot必須 |
| 外部cacheの覗き見 | 試す価値あり | `adb shell ls /sdcard/Android/data/com.zhiliaoapp.musically/` |

「URLを取る」路線はAndroidでもRoot無しでは詰むが、目的が焼き込み用の絵なら画面録画で足りる。

### 集まる範囲

安価なgiftは自分で送れば任意に発火するので待たずに集まる。高額の演出だけは、実際に飛ぶのを
待つか実費を払うかの二択になる。**全722種は集まらない**前提で設計する。

## 未検証で残っていること

1. **web版TikTok LIVEがinteractive gift演出を描くか。** 6章の分岐が全部ここに乗っている
2. `events.extra.asset` の実DBでの被覆と中身(2章のSQL)
3. 稼働中の722種の演出を誰が作っているか、Effect Houseのコンテスト入賞作が販売中のgiftへ
   採用されるのか(5章)。結論には影響しないので、追う価値は薄い
4. effect endpointの実URL。4章により価値が無いので追わない

## 参考

- BytePlus Effects: [About License](https://docs.byteplus.com/en/docs/effects/docs-about-license) /
  [FAQ SDKs](https://docs.byteplus.com/en/docs/effects/docs-faq-sdks)
- Effect House: [LIVE Interactive Gift Effect](https://effecthouse.tiktok.com/latest/live-interactive-gift-effect-challenge)
- 関連: `doc/AUDIO_NORMALIZE.md`(gift SEがmix済み) / `doc/PK_GIFT_PANEL.md`(相手陣giftの扱い) /
  `record/video_overlay.py`(自前のGift演出焼き込み)
