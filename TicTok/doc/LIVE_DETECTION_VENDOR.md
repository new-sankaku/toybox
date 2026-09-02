# LIVE検出をどう調達するか — 他社(SaaS)のやり方

「WAFは他のSaaSだとどうやっているのか」への回答です。

> **訂正 (2026-09-01)**: 初版でこれを「誰も回避していません。買っています」と
> 書きましたが、**整理が綺麗すぎました。**vendor自身の公開docを読むと、
> 実態は**「分散したagent fleet」+「署名生成のreverse engineering」**であり、
> ByteDanceのanti-crawler措置を迂回する行為そのものは含まれています。
> 「回避していない」のではなく、**回避の実装と運用リスクをvendorが引き受けている**、
> が正確です。下の §1 に一次情報を置きます。

**この projectが今Chromiumで自前でやっている処理は、既にこの appが契約している
vendorが商品として売っています。**ただし買う前に、その中身を知っておく必要があります。

## 1. EulerStreamは実際に何をしているのか（vendorの公開docより）

### (a) 分散agent fleet — 「複数IPで見に行っている」は概ね当たり

`docs/sign-server/preferred-agents` に明記があります。

> Our API uses **cloud microservices called "agents"** to generate WebSocket URLs &
> return the responses to you. ... we have **tons of agents running in different
> regions around the world**. ... the sign API will first try your chosen agent
> before picking a **random public agent**

agent IDは `rn-dal-1-a` / `rn-nyc-1-a` / `rn-chi-1-a` のような**地域code付き**で、
既定は**公開agentへのround-robin**です。有料planでは `preferred_agent_ids` で
指定できますが、**最低3つ以上を並べることが必須**とされています
(「requestsをランダムに分散させられるように」)。

**つまりご指摘のとおり、地理的に分散した多数のnodeへ振り分けています。**
「1 requestで複数人ぶん」のbulkも、内部では複数のagentへ散っていると考えるのが自然です。

### (b) しかし本体は署名生成の方です

`docs/sign-server/custom-sign-servers` が、より重要なことを書いています。

> you need to provide a valid **`X-Bogus`, `X-Gnarly`, and `msToken`** signature.
> These are ... created with **complicated obfuscated JavaScript**, based on your
> browser information. This is part of something called the **"ByteDance
> Anti-Crawler"**, which is ... to prevent crawlers from harvesting data en masse
> from TikTok.
>
> ... **What we can't do is tell you how to generate signatures.**

さらに、

> the signature parameters **encode your browser details**, which must match the
> `browser_version` and `browser_name` query parameters. These must also match your
> `User-Agent` header.

**IPを分散させるだけでは通りません。**署名は browser の素性を符号化しており、
それが User-Agent と整合していなければ拒否されます。
`doc/LIVE_DETECTION.md` が実測した
「`_waftokenid` をHTTP clientへ移植しても403」と同じ構造です。

**vendorの中核資産はIP fleetではなく、この署名生成です。**
「教えられない」と明言しているのがそこだけであることが、その証拠になっています。

### (c) 「resource-heavy」の意味

rate limitsのpageにこうあります。

> We've opted for a sort of **"heavy-handed"** way of generating this URLs that ...
> is robust and **automatically handles updates to TikTok's API**. On the other hand,
> **it's resource-heavy**, and so we've got rate limits in place for fair use.

署名algorithmを静的に再実装するのではなく、**実browserを走らせて生成している**と
読むのが自然です。無料枠が2,500 requests/日と控えめなのも、
CAPTCHA solvingを別商品として売っているのも、この読みと整合します。

## 1b. だから、これは「合法な調達」ではなく「リスクの移転」です

**正直に言うと、買っても行為の性質は変わりません。**変わるのは次の点です。

| | 自前でやる | vendorから買う |
|---|---|---|
| 署名生成の追随 | TikTokが変えるたび自分で直す | vendorが直す |
| IPの分散 | 自分で用意する(=本文書が扱わない領域) | vendorのfleet |
| 自宅/自社IPの露出 | **する** | しない |
| ToS上の位置づけ | **変わらない** | **変わらない** |
| 止まったとき | 自分で直せる | **待つしかない** |

**TikTokの利用規約は、誰が取得したかに関わらずdataの利用側にも及びます。**
「vendor経由だから問題ない」とは言えません。判断する材料としてここに書いておきます。

### 唯一、性質が違う道

**公式のauthorized path**(creator本人からOAuthを受けて、その人のdataを読む)だけは
anti-crawlerの外側にあります。EulerStreamも `OAuth Tokens` 系のendpoint
(Exchange / Refresh / Revoke / Introspect / Get user info)を持っています。

ただし**この用途には使えません。**監視対象は自分が権限を持たない他人の配信であり、
本人の認可を取れないためです。**「他人の公開配信を継続的に監視する」という
要求そのものが、公式APIの想定外**である、というのが実際のところです。

## 2. この appは既に半分だけ委託しています

`tictok/core/config.py` に `TICTOK_EULER_API_KEY` があり、
WebSocket接続の**signingは既にEulerStreamへ委託済み**です。

```python
def get_sign_api_key() -> str:
    """EulerStream sign server API key. Empty string means anonymous tier."""
```

**委託していないのはLIVE検出だけ**で、そこだけを自前のheadless Chromiumで
公開pageに当てています。**WAFに当たっているのは、まさにその1点です。**

## 3. 自前でやっている処理は、そのまま商品として売られています

EulerStreamのAPI Reference(公開doc)に、この appがChromiumでやっている処理と
同じものが並んでいます。

| appの現状 | 相当するAPI |
|---|---|
| Chromiumで `/@user/live` を開き `SIGI_STATE` を読む | **`POST Retrieve bulk live check`** |
| そこから `roomId` を取る | **`GET Retrieve Room ID`** / `GET Retrieve room info` |
| (無い) | **`PUT Create alert`** + Alert Targets = **webhook push** |

### 決定的な差は2つ

**(1) bulk — 1 requestで複数人を確認できる**

現在は **1 request = 1配信者**です(Chromiumで1 page開く)。
bulk live checkなら **1 request = 監視全件**になります。

**(2) push — そもそもpollingしない**

`TikTok LIVE Alerts` は配信者(`unique_id`)を登録しておくと、
LIVE開始を**HTTP webhookで通知**します。署名は `x-webhook-signature`
(bodyのHMAC SHA256、secretはDashboard)で検証します。

## 4. 料金（公開pricing pageの実値）

| plan | 月額 | requests/日 | Cloud WebSocket | **LIVE Alerts** |
|---|---:|---:|---:|---:|
| **Community** | **$0 /forever** | 2,500 | 25 | **5** |
| Business | $50 | 10,000 | 100 | 50 |
| Enterprise | 応相談 | 250,000+ | 1,500+ | 1,000+ |

## 5. 効果の試算

現在の自前polling予算は **2.0回/分 = 2,880回/日**です。
Community(無料)の 2,500 requests/日 と**ほぼ同じorder**ですが、
**1 requestで何人ぶん確認できるかが違います。**

### bulk live checkに置き換えた場合

signing用に500回/日を残し、2,000回/日をbulk checkへ回すと **1.39回/分 = 約43秒間隔**。
**監視数に関わらず全員を43秒ごとに確認できます。**

| 監視数 | 現状の平均検出遅延 | bulk化後 | 改善 |
|---:|---:|---:|---:|
| 4 | 1.0分 | 約22秒 | 2.8倍 |
| 10 | 2.5分 | 約22秒 | 6.8倍 |
| **20** | **5.0分** | **約22秒** | **13.6倍** |
| 50 | 12.5分 | 約22秒 | 34倍 |

**監視数を増やしても検出遅延が悪化しません。**`doc/MONITOR_SCALING.md` で
「監視数の上限は検出遅延で決まる」と書いた制約が、丸ごと消えます。

### Alertsを使った場合

登録した配信者は**遅延ほぼゼロ・polling回数ゼロ**。ただし**無料枠は5件**です。
50件にするには $50/月(¥7,500)で、¥1,000の予算を大きく超えます。

**現実的な組み合わせ**は、
**重要な5件をAlerts(無料枠) + 残り全部をbulk live check**です。
`doc/MONITOR_SCALING.md` で提案した「gateの重み付け」を、
**実装せずに料金体系側で実現できます。**

## 6. 構成への波及 — ここが一番大きい

headless Chromiumが不要になると、これまでの検討の前提が変わります。

| | 現状 | vendor調達後 |
|---|---|---|
| **WAFのgo/no-go PoC** | **必須**(datacenter IPで通るか未実測) | **不要**。公開pageを叩かない |
| RAM | Chromium 350〜700MB が固定費 | **削減**。4GB → 2GBで足りる可能性 |
| VPSの月額 | 4GB級が必要 | 2GB級で済む |
| `playwright` 依存 | 必須(arm64確認が要る) | **不要**。Oracle A1のarm64懸念も消える |
| 検出の失敗modeb | browserのcrash・driverの無応答・WAF stub | HTTP APIの失敗のみ |

**`doc/COST_ALTERNATIVES.md` の最大のriskだった「TikTok WAFのgo/no-go」が
消えます。**これが実務上いちばん効きます。

ただし **§1b のとおり、riskは消えるのではなくvendorへ移ります。**
vendorがTikTok側の変更に追随できなくなれば、検出は止まります。
**「自分では直せない停止」を受け入れられるかが判断の分かれ目**です。

`doc/LIVE_DETECTION.md` に記録された障害
(browserが死なずに固まり、**229回連続失敗・5時間**検出が止まった)も、
原因のcomponentごと無くなります。

## 7. 確認が必要な点

**未検証のまま採用しないでください。**

| 項目 | 状態 |
|---|---|
| `Retrieve bulk live check` が **Community(無料)に含まれるか** | **未確認。**pricing pageは "Premium Webcast Routes" をadd-on扱いにしており、ここに入る可能性がある |
| 1 requestあたりの配信者数の上限 | 未確認 |
| Alertsの通知遅延の実測 | 未確認 |
| 応答の内容が `SIGI_STATE` 相当か(status・roomIdが揃うか) | 未確認 |
| SDKはNode.js(`tiktok-live-api-sdk`) | このappはPython。**REST直叩き**になる |

いずれも**無料枠でAPI keyを取れば試せます。**先にそこを通してください。

### 引き換えに増えるもの

**vendorへの依存が「signing」から「検出」まで広がります。**
現在はEulerStreamが落ちても検出だけは自前で回りますが、移行後は止まります。

対策は、**Chromium経路をfallbackとして残すことではありません**
(CLAUDE.mdの「Fallback処理は禁止」に反しますし、二重の検出経路は
どちらが真かを分からなくします)。**vendor障害を検出して明示的に停止・通知する**のが筋で、
`sign_server_outage()` が sign server 向けに既に持っている扱いをそのまま広げます。

## 8. 進め方

```
1. Community(無料)でAPI keyを取り、bulk live check の
   可用性・件数上限・応答内容を実測する                       ¥0 / 半日
2. 重要な5件を LIVE Alerts へ登録し、webhook受けを作る        ¥0 / 1〜2人日
3. 残りを bulk live check の定期呼び出しへ置き換える           1〜2人日
4. live_resolver(Chromium)と ProbeGate を撤去               1人日
   -> playwright 依存が消え、RAM要件とVPS費用が下がる
```

**`doc/MONITOR_SCALING.md` の「ProbeGateの重み付け(2〜4人日)」は、
1〜3が通れば不要になります。**先にこちらを試す方が、実装量も少なく効果も大きいはずです。
