# AWS移行の構成とminimum cost

TicTokをAWSへ載せ替える場合の構成案と月額見積りです。単価は AWS Price List API
(`pricing.us-east-1.amazonaws.com/offers/v1.0/aws/...`) から **ap-northeast-1 (Tokyo) の
実値**を取得しています。Spot価格だけは変動するため推定です。

## 1. 何を載せるのか — 現行の実測値

負荷の性質が component ごとに全く違うため、まず実測を並べます。数値の出所は
`doc/CAPACITY_FORECAST.md` と `doc/MEDIA_PIPELINE_PERF.md` です。

| 項目 | 実測 | 出所 |
|---|---|---|
| 録画の増加 | **8.69 GB/日**(直近14日平均) | CAPACITY_FORECAST |
| 34日間の総量 | 285本 / 183.2 GB | CAPACITY_FORECAST |
| 実bitrate | 318MB / 46分 = **0.92 Mbps** | MEDIA_PIPELINE_PERF |
| 上記から逆算した録画時間 | **約21.5時間/日** | 8.69GB ÷ 6.91MB/分 |
| 同時進行sessionの最大 | **4** | STORAGE_SPLIT |
| DB本体 | 506 MB (WAL 19MB) | CAPACITY_FORECAST |
| 再mp4化 | 46分の録画に138.3秒 = **3.0秒/分** | MEDIA_PIPELINE_PERF |
| 焼き込み | 31分の録画に308.8秒 = **10.0秒/分** | MEDIA_PIPELINE_PERF |
| 文字起こし完了率 / 焼き込み完了率 | 58.2% / 1.8% | CAPACITY_FORECAST |

ここから読める重要な非対称が2つあります。

1. **常時動く部分は極めて軽い。** 録画は `-c copy` のstream copy(`recorder.py`)で、
   4本同時でも 0.92Mbps × 4 = 3.7Mbps、書き込みは 0.1 MB/s です。CPUもdiskも要りません。
   重いのは常駐headless Chromium(LIVE検出)とSQLiteの集計readだけです。
2. **重い部分は間欠。** 焼き込み・再mp4化・超解像・文字起こしはすべてbatchで、
   GPUが要るのはその時間だけです。**この2つを同じ instance に置くと、月の97%を遊ばせた
   GPUに払うことになります。**

構成の分割点はここに置きます。

## 2. 構成案

```
                 [利用者のbrowser]
                        |  HTTPS
        +---------------+------------------+
        | 常時稼働node (小)                 |
        |  FastAPI + static UI (156 route) |
        |  collector (TikTokLive WS)       |
        |  live_resolver (headless Chromium)|
        |  recorder (ffmpeg stream copy)   |
        |  SQLite (single instance lock)   |
        +----+--------------------+--------+
             | 直近N日 (hot)      | job投入
        [block storage]           |
             |                    v
             | 退避          [GPU worker (間欠起動)]
             v                 焼き込み / 再mp4化 / 超解像 / STT
        [S3 + lifecycle]  <-----+
         Standard -> Glacier IR
```

* **常時node は1台固定。** `tictok/core/process_lock.py` が単一instanceを強制し、
  Storage は `_lock -> _buf_lock` の一方向lock契約(`doc/STORAGE_SPLIT.md`)の上に
  組まれています。**水平分散は設計上できませんし、する必要もありません。**
* **RDSへは移しません。** SQLite前提のlock契約を壊す改修が大きい上、
  db.t4g.micro でも月$20超で、常時nodeそのものより高くつきます。
* **S3への退避は既存の `TICTOK_RECORD_DIR_FINAL`(退避先) が接ぎ木点です。**
  `doc/RETENTION.md` の資産序列(transient → derived → source)がそのまま
  lifecycle ruleの設計になります。

## 3. 取得した実価格 (ap-northeast-1 / On-Demand)

| 資源 | 単価 | 取得元 |
|---|---:|---|
| t4g.small (2vCPU/2GB) | $0.0216 /h | EC2 pricing |
| **t4g.medium (2vCPU/4GB)** | **$0.0432 /h** | EC2 pricing |
| t4g.large (2vCPU/8GB) | $0.0864 /h | EC2 pricing |
| c7g.large (2vCPU/4GB) | $0.0910 /h | EC2 pricing |
| m7g.large (2vCPU/8GB) | $0.1054 /h | EC2 pricing |
| g4dn.xlarge (T4) | $0.7100 /h | EC2 pricing |
| **g6.xlarge (L4)** | **$1.1672 /h** | EC2 pricing |
| g6e.xlarge (L40S) | $2.6990 /h | EC2 pricing |
| EBS gp3 | $0.096 /GB-月 | EC2 pricing |
| EBS snapshot | $0.050 /GB-月 | EC2 pricing |
| S3 Standard | $0.0230 /GB-月 | S3 pricing |
| S3 Standard-IA | $0.0138 /GB-月 | S3 pricing |
| **S3 Glacier Instant Retrieval** | **$0.0050 /GB-月** | S3 pricing |
| S3 Glacier Deep Archive | $0.0020 /GB-月 | S3 pricing |
| S3 PUT (Tier1) | $0.0047 /1,000 req | S3 pricing |
| S3 GET (Tier2) | $0.00037 /1,000 req | S3 pricing |
| 内→外 転送 (最初の10TB) | $0.114 /GB | DataTransfer pricing |
| Public IPv4 | $0.005 /h (= $3.65/月) | AWS公表値 |
| Lightsail 4GB/2vCPU/80GB (IPv4付) | $0.03225 /h (= **$24/月**) | Lightsail pricing |
| Lightsail 8GB/2vCPU/160GB (IPv4付) | $0.05913 /h (= $44/月) | Lightsail pricing |

内→外転送は **月100GBまで無料枠**があります。Lightsailはplanに4TBの転送量が含まれます。

## 4. 見積り

### 前提

| 変数 | 値 | 根拠 |
|---|---|---|
| 録画増加 | 261 GB/月 (3.10 TB/年) | 8.69GB/日 |
| hot保持 | 直近14日 = 122GB + DB/OS/venv | 焼き込み・切り出しの作業窓 |
| GPU時間 | **約65 h/月** | STT 32h + 再mp4化 32h + 焼き込み少量 |
| 画面視聴による転送 | 月100GB以内 | 0.92Mbpsなら約30時間ぶん |

GPU時間の内訳は、文字起こしを20倍速と仮定して 1,287分/日 ÷ 20 = 64分/日 (32h/月)、
再mp4化が実測3.0秒/分で 64分/日 (32h/月) です。**焼き込みを全録画に掛けると
実測10.0秒/分 = +107h/月**になるので、ここは運用方針で線形に増えます(現在の完了率1.8%を
前提に少量としています)。

### Plan A — EC2構成

| 項目 | 数量 | 月額 |
|---|---|---:|
| t4g.medium 常時 | 730 h × $0.0432 | $31.54 |
| gp3 (hot) | 150 GB × $0.096 | $14.40 |
| Public IPv4 | 1個 | $3.65 |
| g6.xlarge **Spot** | 65 h × $0.40(推定) | $26.00 |
| GPU用 gp3 | 200GB × 65/730h | $1.71 |
| GPU用 AMI snapshot | 30 GB × $0.05 | $1.50 |
| S3 Glacier IR | 1.5 TB(1年目平均) | $7.68 |
| S3 request / lifecycle transition | | $1.00 |
| 内→外転送 | 無料枠内 | $0.00 |
| **合計** | | **約 $87 / 月** |

### Plan B — Lightsail構成 (**minimum**)

常時nodeをLightsailにすると、instance・block storage・IPv4・転送量が1つのplanに
まとまり、同形状のEC2構成より安くなります。

| 項目 | 数量 | 月額 |
|---|---|---:|
| Lightsail 4GB/2vCPU/80GB SSD (IPv4・4TB転送込) | 1 | $24.00 |
| g6.xlarge **Spot** | 65 h × $0.40(推定) | $26.00 |
| GPU用 gp3 + AMI snapshot | | $3.21 |
| S3 Glacier IR | 1.5 TB | $7.68 |
| S3 request / transition | | $1.00 |
| **合計** | | **約 $62 / 月 (約 ¥9,300)** |

同形状のEC2側 (t4g.medium + gp3 80GB + IPv4 = $42.87) に対し、Lightsailは$24で
**転送4TBまで込み**です。ただしSSDは80GB固定で、録画の hot 保持は **約8日ぶん**しか
ありません。毎日S3へ退避する運用が前提になります。17日ぶん欲しければ8GB/160GB plan
($44/月) で、合計は約$82/月です。

### Plan C — Phase 1 (GPU機能を切った lift & shift)

文字起こし・焼き込み・超解像・BGM除去を無効(既定はすべて `0`)のまま移すなら、
GPUの行が丸ごと消えます。

| 項目 | 月額 |
|---|---:|
| Lightsail 4GB | $24.00 |
| S3 Glacier IR (1年目平均 1.5TB) | $7.68 |
| S3 request | $1.00 |
| **合計** | **約 $33 / 月 (約 ¥4,900)** |

録画・comment収集・LIVE検出・検索・解析・切り出し候補までは動きます。
**これが移行の実質的な下限**で、GPU系は後から足せます。

### Plan D — GPU常時(採ってはいけない例)

g6.xlarge を 730h 回すと **$852/月**。上記に足して約 **$890/月 (¥133,000)** です。
GPUの実稼働は月65hなので、**91%を遊休に払うことになります**。GPUは必ず間欠にします。

## 5. storage費用の時間推移

録画は消さない限り単調増加します。tier別の月額(Tokyo実価格):

| 経過 | 累積量 | Standard | Standard-IA | Glacier IR | Deep Archive |
|---|---:|---:|---:|---:|---:|
| 3ヶ月 | 0.77 TB | $18.2 | $10.9 | $4.0 | $1.6 |
| 6ヶ月 | 1.55 TB | $36.5 | $21.9 | $7.9 | $3.2 |
| 12ヶ月 | 3.10 TB | $72.9 | $43.7 | $15.9 | $6.3 |
| 24ヶ月 | 6.19 TB | $145.8 | $87.5 | $31.7 | $12.7 |
| 36ヶ月 | 9.29 TB | $218.7 | $131.2 | $47.6 | $19.0 |

**3年目にはstorageが他の全費用を超えます。** ここが長期の主戦場で、
`doc/RETENTION.md` の資産序列がそのままlifecycle ruleになります。

推奨する lifecycle:

| 対象 | 置き場 | 理由 |
|---|---|---|
| 直近14日の素材(.ts)とmp4 | node の block storage | 焼き込み・切り出しの作業窓 |
| 15日〜90日 | S3 Standard-IA | 画面から再生しに行く可能性が残る |
| 90日〜 の素材(.ts) | S3 Glacier IR | 再取得不能な原本。取り出しは即時 |
| 派生mp4で素材が残るもの | **消す** | `RETENTION.md` の②。再mp4化で戻る |

**Deep Archive は原本には使えません。** 取り出しに最大12時間かかり、再mp4化も再生も
その場では成立しません。Glacier IR ($0.005/GB-月、取り出し$0.03/GB) が上限です。

### segmentを束ねずにS3へ置いてはいけない

HLS素材は6秒segmentなので、46分の録画で約460 file になります。日8.4本なら
**月11.6万object**です。Glacier系は1objectあたり32KB+8KBのmetadata課金が乗るため、
月4.6GBぶんの「中身のない容量」と、transition requestが $2〜6/月 増えます。
`tictok/record/hls_pack.py` の束ね(`pack*.ts`)を通してから上げれば、
object数は録画あたり数個に落ち、この費用は消えます。

## 6. 文字起こしをmanaged serviceにしない理由

Amazon Transcribeへ出すと、1,287分/日 × 30日 × $0.024/分 = **約$927/月**です。
Spot GPUの$26と比べて **36倍**なので、`faster-whisper` の自前実行を維持します。
`doc/STT_PROCESS_ISOLATION.md` にある通り既に別processへ隔離済みなので、
別instanceへ移す改修とは方向が一致しています。

## 7. 移行の障害 — 費用より先に確かめること

### (1) TikTok WAF と datacenter IP ★go/no-go

`doc/LIVE_DETECTION.md` は「ゲートはIPではなくJS challengeを解けるbrowserかを見る」
「browserは未log inのまま匿名で通過する」と記録しています。**この記述通りなら
AWS上のChromiumでも通ります。**ただし同じ文書は「VPN(特にdatacenter IP)では解決しない」
とも書いており、AWSのIP帯に対する挙動は**実測されていません**。

**最初にやるべきはこの1点のPoCです。** t4g.medium を1台立て、`live_resolver` だけを
動かして `SIGI_STATE` が取れるかを見ます。取れなければ他の全ての見積りが無意味になります。

もし塞がれていた場合の回避は、**解決経路(navigation)だけをresidential proxyへ通し、
録画のCDN取得はAWSのIPのまま**にします。解決の通信量は月数百MBなので proxy 費用は
$3〜15/GBでも月$2〜10ですが、**録画の261GB/月を proxy へ流すと月$800〜4,000**になり
成立しません。CDN側も塞がれていたら、AWS化そのものを見送る判断になります。

### (2) GPU workerを別instanceにする改修

現在、映像jobのqueueは `tictok/api/media_jobs.py` の `media_job_queue` が
**同一process内のworker**として消化し、`claim_next_pending_media_job` が
SQLiteを直接見ています。別instanceへ出すには、

* GPU worker から job を claim する口(HTTP)
* 素材とmp4の受け渡し(S3経由)
* GPU instance の起動・停止の制御

が要ります。**これが移行で一番大きい実装です。**Phase 1(Plan C)ではこれを作らず、
GPU機能を無効のまま移すのが順当です。

### (3) AV1 NVENC が使えるGPUは限られる

`TICTOK_NORMALIZE_CODEC` の既定は `av1` です。AV1のhardware encoderは Ada 世代
(L4 = g6 / L40S = g6e) 以降にしかなく、**最安のGPUである g4dn (T4) では使えません**。

| 選択 | 単価 | AV1 |
|---|---:|---|
| g4dn.xlarge (T4) | $0.71/h | 不可 → `hevc`/`h264` へ設定変更 |
| g6.xlarge (L4) | $1.1672/h | 可 |

codec は環境変数なので設定変更で済みます(hard-codeされていません)。ただしT4はL4より
NVENCもwhisperも遅く、単価差(1.64倍)を時間増で相殺してしまう可能性があります。
**実測してから決める項目**です。

### (4) Linux対応は概ね済んでいる

`.github/workflows/ci.yml` が `ubuntu-latest` と `windows-latest` の両方でlintとtestを
回しており、`run.sh` も揃っています。Windows固有なのは `transcription.py` のDLL loader
登録と `orphan_capture.py` / `process_lock.py` の分岐だけで、いずれも `sys.platform` で
切ってあります。**移行の障害にはなりません。**

### (5) 画面応答は現行機より遅くなる

現行の計測環境は12coreです。t4g.medium は 2 vCPU の burstable で、baseline を超えると
CPU creditを消費します。`doc/API_PERF.md` が扱う集計read(`db.read` / `analytics.reduce`)は
そのまま遅くなります。応答を優先するなら c7g.large ($0.091/h = $66/月) ですが、
**Plan B の合計が $62 → $104 に跳ねます**。まず t4g.medium で始め、
`GET /api/perf` の実測を見てから上げるのが妥当です。

### (6) 可用性は上がらない

単一instance・単一AZ・SQLiteなので、AZ障害では止まります(dataはEBSに残ります)。
**AWS化の価値は可用性ではなく「PCを24時間点けておかなくてよくなること」**です。

## 8. 現行(自宅PC)との比較

RTX 4070 Ti搭載機を24時間点けた場合、idle 100W 前後として月73kWh、
¥31/kWh なら **月約¥2,300 ($15)** です。

| | 月額 | 備考 |
|---|---:|---|
| 自宅PC 24時間稼働 | 約 ¥2,300 | 電気代のみ。機材は償却済み前提 |
| Plan C (GPU機能なし) | 約 ¥4,900 | 録画・収集・解析のみ |
| Plan B (minimum構成) | 約 ¥9,300 | GPU系も動く |
| Plan A (EC2構成) | 約 ¥13,100 | |
| Plan D (GPU常時) | 約 ¥133,000 | 採らない |

**費用だけならAWSが不利です。**AWS化が正当化されるのは、PCを常時稼働させたくない・
自宅回線と電源の障害で録画を落としたくない、といった要件がある場合です。

なお、**自宅の常時稼働機を省電力機へ置き換えると月¥226**まで落ちます
(現状の¥2,489より安い)。cost最優先ならこちらが答えです。
検討は [COST_ALTERNATIVES.md](COST_ALTERNATIVES.md) にあります。

## 9. 進め方

| Phase | 内容 | 月額 | 判定 |
|---|---|---:|---|
| 0 | t4g.medium 1台で `live_resolver` のみ動かし、WAF通過を実測 | 約$1(数日) | **通らなければ中止** |
| 1 | GPU機能を無効のまま Lightsail 4GB へ lift & shift。S3 lifecycle を設定 | 約$33 | 録画・収集・解析が回るか |
| 2 | `hls_pack` を通した束ね上げをS3退避経路に組み込む | +$1 | object数が録画あたり数個か |
| 3 | GPU worker の分離(claim API + S3受け渡し + 起動制御)を実装 | +$29 | 実装が最大の山 |
| 4 | Savings Plan / Spot の適用、instance sizeの実測調整 | -10〜30% | |

Phase 0 を通さずに他を始めないでください。
