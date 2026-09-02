# 月額¥1,000で成立する構成（cloud完結）

`doc/AWS_MIGRATION_COST.md` の続きです。AWSのminimum($33/月 = ¥4,900)を
目標の**¥1,000**へ落とせるかを検討しました。**自宅に機材を置かない前提**です。

**結論: ¥1,000で成立します。ただし「録画を永久に持つ」ことは諦めます。**
¥1,000は**保持期間を買う予算**として使うのが正しい読み方です。

## 0. 訂正 — `$18.7/月` は米ドルです

前回の表の「264GB/月を自宅へ送る費用 **$18.7/月**」は**米ドル**で、
**約¥2,804/月**です。¥18.7ではありません。誤解を招く書き方でした。

```
(264GB - 無料枠100GB) x $0.114/GB = $18.70 = 約¥2,804/月
```

AWSの内→外転送は **$0.114/GB**(ap-northeast-1実価格、Price List APIで取得)で、
264GB/月を動かすと¥2,800級になります。**AWSで「cloudに録画して自宅へ落とす」は
成立しません。**そもそも自宅を使わない方針なので、この案は消えます。

## 1. 何が予算を食っているのか

| 項目 | 性質 | 削り方 |
|---|---|---|
| 常時compute | 24時間必要。Chromium + collector + recorder | **provider選択**で¥3,600 → ¥0〜750 |
| **storage** | **264GB/月ずつ増え続ける** | **保持期間を決めて定数化する** |
| GPU | 間欠 | **¥1,000には入りません**(後述) |
| 転送 | 画面での再生ぶん | VPS系はplanに込み。AWSのみ従量 |

前回「cloudでは¥1,000に届かない」と書いたのは、**録画を永久保存する前提**で
計算していたためです。**保持期間を決めれば storage は増え続けない定数**になり、
話が変わります。

## 2. 保持期間 × 単価 = storage費用

保持期間を決めると、必要容量は `8.69GB/日 × 保持日数` で頭打ちになります。

| 保持 | 必要容量 | S3 Glacier IR<br>($0.005/GB) | B2級<br>($0.006/GB) | 最安級<br>($0.0042/GB) |
|---:|---:|---:|---:|---:|
| 14日 | 122 GB | ¥91 | ¥109 | ¥77 |
| 30日 | 261 GB | ¥196 | ¥235 | ¥164 |
| 60日 | 521 GB | ¥391 | ¥469 | ¥328 |
| 90日 | 782 GB | ¥587 | ¥704 | ¥493 |
| 180日 | 1,564 GB | ¥1,173 | ¥1,408 | ¥985 |
| 365日 | 3,172 GB | ¥2,379 | ¥2,855 | ¥1,998 |

Glacier IR の単価はPrice List APIで確認済みの実値です。他の2列は公表価格からの
概算で、**契約前にご確認ください**。

### ¥1,000で買える保持期間

| compute | + storage | 保持できる期間 |
|---|---|---|
| **Oracle Always Free (¥0)** | 最安級 | **約6ヶ月** |
| Oracle Always Free (¥0) | Glacier IR | 約5ヶ月 |
| Oracle Always Free (¥0) | B2級 | 約4.2ヶ月 |
| 格安VPS (¥750) | 最安級 | 約45日 |
| 格安VPS (¥750) | Glacier IR | 約38日 |

**computeを無料にできるかで、保持期間が4倍変わります。**

## 3. 案の比較（すべてcloud完結）

| 案 | compute | 録画の置き場 | 保持 | 月額 | GPU |
|---|---|---|---:|---:|---|
| **X** | Oracle Always Free 単体 | 同じ無料block volume | **約17日** | **¥0** | ✗ |
| **Y** ★ | Oracle Always Free | 外部の格安object storage | **約6ヶ月** | **約¥1,000** | ✗ |
| Z | x86 VPS + object storage | object storage | 約38日 | 約¥1,000 | ✗ |
| D | AWS Plan C | S3 Glacier IR | 永久 | ¥4,900 | ✗ |
| D+ | AWS + Spot GPU | S3 Glacier IR | 永久 | ¥9,300 | ✅ |

### 案X — Oracle Cloud Always Free 単体（¥0）

公式doc(`docs.oracle.com` / Always Free Resources)で確認した無料枠:

| 資源 | 無料枠 |
|---|---|
| Ampere A1 Compute (arm64) | **2 OCPU** まで(1〜2 instance) |
| Block Volume | **合計200GB**(boot volume込み)。boot最小47GB |
| Object / Archive Storage | 合計 **20GB** のみ |
| 外向き転送 | **10TB/月** |

boot 47GB を引くと録画に使えるのは約150GB = **約17日ぶん**です。
Object Storageの無料枠は20GBしかないので、**録画の置き場にはなりません**。

**転送10TB/月**が無料なのは効きます。画面で録画を再生しても転送料がかかりません
(AWSは100GB超過ぶんが$0.114/GB)。

### 案Y — Oracle Always Free + 外部の格安object storage（約¥1,000）★推奨

案XのcomputeはそのままIC、録画だけを外部の安いobject storageへ逃がします。
Oracleの外向き転送が10TB/月無料なので、**録画を外部storageへ送る費用は¥0**です。

```
[Oracle Ampere A1 / Always Free / ¥0]
   live検出 + collector + recorder + FastAPI + SQLite
   block volume 150GB = 直近17日ぶんのhot領域
        |  転送は無料枠(10TB/月)の内側
        v
[格安object storage]  約1.5TB = 保持6ヶ月ぶん   ¥1,000
```

**予算のほぼ全額をstorageに使えるので、保持期間が最大化されます。**

### 案Z — x86 VPS + object storage（約¥1,000 / 保持約38日）

**arm64とcapacity確保の両方を避けたい場合の選択肢**です。

> **訂正**: 初版でこの案を「大容量diskのVPS 1台で保持45日 / ¥750〜1,300」と
> 書きましたが**誤りです**。その価格帯のVPSのdiskは20〜50GBで、
> **録画2.3〜5.8日ぶんにしかなりません**(下表)。1台完結では保持45日は買えません。

Lightsailの実価格(Price List API取得)で価格とdiskの関係を確かめました。

| 月額 | RAM | disk | 録画の日数 | このappが動くか |
|---:|---:|---:|---:|---|
| ¥525 | 0.5GB | 20GB | 2.3日 | ✗ RAM不足 |
| ¥750 | 1GB | 40GB | 4.6日 | ✗ **Chromiumだけで約1GB** |
| ¥1,500 | 2GB | 60GB | 6.9日 | △ 厳しい |
| **¥3,600** | **4GB** | **80GB** | 9.2日 | ✅ |
| ¥6,600 | 8GB | 160GB | 18.4日 | ✅ |

**diskは価格に対して線形にしか増えません。**録画8.69GB/日に対して、
月額を10倍にしても保持は2倍にしかならない — だから**録画をobject storageへ
逃がす構成が必要**になります。

そして重要な点として、**AWS/Lightsailでは¥1,000は不可能です**。
このappが動く最小構成(4GB RAM)が**¥3,600**だからです。
¥750で4GB級を出せるのはAWS以外のprovider(Hetzner / Contabo / 国内VPS等)で、
**これらの価格は私の側で未検証です。契約前に必ずご確認ください。**

構成:

```
[x86 VPS 4GB / 40〜80GB disk]  ¥750前後(要確認)
   live検出 + collector + recorder + FastAPI + SQLite
   disk は 5〜9日ぶんの hot buffer のみ
        |  完了した録画を継続的に送出
        v
[object storage 約330GB]  ¥250   -> 合計 保持 約38日
```

#### hot bufferが薄いことへの注意

40GBのdiskは録画**4.6日ぶん**しかありません。**送出が数日止まればdiskが埋まり、
録画が落ちます。**

`doc/CAPACITY_FORECAST.md` の容量予測と `capacity.forecast_low` 通知が
そのまま監視に使えますが、**既定の `capacity_alert_days`(14日)では一度も鳴りません** —
diskの全容量が4.6日ぶんしか無いためです。**2日程度へ下げてください。**

## 4. GPU機能は¥1,000には入りません

焼き込み・超解像・文字起こし・BGM除去はGPUが要り、Spot g6.xlarge を月65時間で
**約¥3,900**です。¥1,000の予算では**必ずOFF**になります。

| 動くもの | 動かないもの |
|---|---|
| LIVE検出・collector・**録画** | 焼き込み(`overlay`) |
| 画面・検索・解析・切り出し**候補** | 超解像(`upscale`) |
| `pack`(ts束ね)・`waveform` | 文字起こし(`stt`) |
| fan台帳・ranking・battle集計 | BGM除去・笑い声検出・smile |

**GPU機能は既定がすべて `False` なので、設定変更もcode修正も要りません。**
(`TICTOK_STT_ENABLED` / `TICTOK_UPSCALE_ENABLED` / `TICTOK_BGM_REMOVE_ENABLED` /
`TICTOK_SMILE_ENABLED` / `TICTOK_LAUGH_AUDIO_ENABLED` は全部既定OFF)

後からGPUを足すなら、案Dの構成へ +¥3,900/月です。

## 5. 保持期間の実装 — 既存機能と provider 機能のどちらでも

### provider側のlifecycleで消す（推奨・実装0行）

S3互換のobject storageなら、bucketに**有効期限rule**を1つ設定するだけです。
appは一切関知しません。

**appはfileが消えた録画に既に耐えます。** `doc/RELOCATE_TO_FINAL.md` の実測では、
「mp4も素材(.ts)も無い」録画が**132本中82本(retention削除済み)**あり、
画面はそれを「移すものが無い」として正しく除外していました。
`recordings` の行は残るので、**いつ誰の配信を録ったかという記録は消えません**。
消えるのは映像の実体だけです。

### appのretentionを使う（既存機能）

`doc/RETENTION.md` の3段の資産序列(① transient → ② derived → ③ source)が
そのまま使えます。**ただし現状は自動実行されません** — dry-run → `apply` + `confirm`
の2段で、人が押す必要があります。予算の上限として自動で効かせたいなら
provider側のlifecycleの方が確実です。

> 前回このdocで「保持期間を短くする案は採らない(容量のために原本を消すのは順序が逆)」
> と書きました。**diskが満杯という文脈での話**で、**予算という制約を先に置く今回は
> 当てはまりません。**保持期間の決定は正当なpolicy選択で、appにもその機能があります。

## 6. 採用前に確かめること

### (1) TikTok WAF ★go/no-go（全cloud案に共通）

`doc/AWS_MIGRATION_COST.md` §7-(1) と同じです。`doc/LIVE_DETECTION.md` は
「ゲートはIPではなくJS challengeを解けるbrowserかを見る」と記録する一方、
「VPN(特にdatacenter IP)では解決しない」とも書いており、**datacenter IPでの挙動は
実測されていません**。

**instance 1台を数日立てて `live_resolver` だけ動かし、`SIGI_STATE` が取れるかを
最初に確かめてください。**取れなければ他の全ての見積りが無意味になります。

安いproviderほどIP帯のevaluationは厳しい傾向があります。塞がれた場合、
国内VPS(さくら/ConoHa/Xserver等)は日本のIP帯でCDNへの経路も短いため、
次に試す価値があります。

### (2) arm64（案X・Yのみ）

Oracle Always Free で Chromium を動かせるのは **Ampere A1 = arm64** だけです
(もう一方の無料枠 VM.Standard.E2.1.Micro は **1GB RAM** で、Chromiumには足りません)。

確認が要るのは `playwright` / `fugashi` / `unidic-lite` / `onnxruntime` の
arm64 wheelです。**GPU系機能はどのみちOFFなので、実害の範囲は限定的**ですが、
避けたいなら案Z(x86 VPS)にします。

### (3) Ampere A1 の capacity — Oracle自身が明記しています

これは伝聞ではなく、**Oracleの公式docに書かれています**
(`docs.oracle.com` / Always Free Resources)。

> If you receive an "out of host capacity" error when trying to create a Compute
> instance, this indicates a **temporary lack of Always Free shapes in your home
> region**. Try creating the instance in a different availability domain, or wait a
> while, then try to create the instance again. You can also choose to **upgrade your
> account to Pay as You Go** ...

つまり **Always Free の shape が不足する事象は仕様として想定されており**、
Oracleが案内する回避策は「別のADで試す」「時間を置いて再試行」「有料account へ上げる」
です。**「取れるまで試す」性質**である点が公式に裏付けられています。

### (5) 確保の容易さの比較

| | 確保 | 根拠 |
|---|---|---|
| **有料VPS(案Z)** | **容易**。購入すれば数分で用意される | 商用製品。在庫切れは例外的 |
| Oracle Always Free(案X・Y) | **不確実**。再試行が要る場合がある | 上記の公式doc |
| AWS(案D) | 容易 | 商用製品 |

**有料VPSは「抽選」ではなく「購入」です。**Oracleの困難は無料枠に特有のもので、
有料accountでは優先度が上がるとOracle自身が案内しています。

ただし**「容易に確保できること」と「¥750で4GB級が買えること」は別の話**です。
後者はprovider次第で、上表のとおりAWSでは¥3,600かかります。

### (4) DBの保護

保持期間を切っても **`tictok.db` は増え続けます**(実測506MB)。
そして録画の実体が消えたあとも、**`recordings` の行だけがその録画の唯一の記録**に
なります。`doc/BACKUP_DUPLICATION.md` のLitestreamによる継続replication
(RPO≈1秒 / app改修0行)は、この構成では**より重要**になります。
複製先はOracleの無料object storage 20GBに収まります。

## 7. 進め方

```
Phase 0  instance 1台で live_resolver だけ動かし WAF通過を実測   数日 / ほぼ¥0
             ↓ 通らなければ中止(または国内VPSで再試行)
Phase 1  案X (Oracle Always Free 単体 / 17日保持) で通しで動かす   ¥0
             ↓ 保持を伸ばしたくなったら
Phase 2  案Y (外部object storage + lifecycle) へ            約¥1,000
             ↓ GPU作業を戻したくなったら
Phase 3  Spot GPU worker を足す                            +¥3,900
```

**Phase 1 まで¥0で、保持17日なら追加費用なしに成立します。**
まずそこまで通してから、保持期間にいくら払うかを決めるのが確実です。

## 8. 参考 — 採らなかった案

| 案 | 理由 |
|---|---|
| AWSで録画して自宅へ落とす | 転送料 **$18.70 = ¥2,804/月**。AWSの料金体系では成立しない |
| 録画をcloudに**永久**保存 | 264GB/月で単調増加。最安単価でも2年目¥2,904/月、3年目¥4,600/月。予算が固定できない |
| Oracleの**paid** block volumeで容量を足す | 約$0.0255/GB-月。外部のobject storage($0.0042〜0.006/GB)の4〜6倍 |
| S3 Deep Archive で保持を伸ばす | $0.002/GBと最安だが**取り出しに最大12時間**。再生も再mp4化もその場で成立しない |
| 解像度・bitrateを落として録画量を減らす | 録画は `-c copy` のstream copy。落とすには再encodeが要り、CPU/GPUを常時使うことになる |
| 自宅に省電力機を置く | 月¥226で最安だが、**ご要望により対象外** |
