# LIVE検出をどう調達するか — 他社(SaaS)のやり方

「WAFは他のSaaSだとどうやっているのか」への回答です。

**結論: 誰も回避していません。買っています。**
そして**この projectが今Chromiumで自前でやっている処理は、既にこの appが契約している
vendorが商品として売っています。**

## 1. 商用の3つの層

| 層 | 中身 | WAFとの関係 |
|---|---|---|
| **A. 公式のauthorized path** | creator/agencyからOAuthを受け、**本人のdata**を読む | scrapingではないのでWAFの外側 |
| **B. 専門vendorから買う** | 検出・signing・room解決を、それを本業とする事業者に委ねる | vendorが負う |
| C. 自前で回避し続ける | proxy・CAPTCHA・fingerprint | **これが「他社もやっている」の実態ではない** |

Cを商品化している事業者は実在します(EulerStreamの製品ラインにも
"Captcha API — High fidelity CAPTCHA solving service" があります)。
ただし**それは選択肢の1つであって、標準的なやり方ではありません。**
本文書ではAとBだけを扱います。

## 2. この appは既にBの入口に立っています

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
