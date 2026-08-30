# Android実機によるギフト演出capture — 実測記録と方針

TikTokのギフト演出(gift 演出)を録画へ焼き込むための素材を、**実機のApp画面録画**から採る経路の
実測記録。2026-08-29に測った値を全て残す。次に触るときはここから読む。

関連: `doc/OVERLAY_OUTPUT_INTEGRITY.md`、`tictok/record/video_overlay.py`、`tictok/media/gift_icons.py`

## なぜ画面録画一択なのか

演出の入手経路は3つ考えられ、実機で測った結果それぞれ次の状態にある。

| 経路 | 状態 | 根拠 |
|---|---|---|
| 通信の傍受 | 実質不可 | 演出本体は `POST /webcast/assets/effects/` 経由。Web版で落ちてくるfaas zipは Content-Type がzipでも実体は暗号化binaryでEffect SDKが実行時復号する。実機Appはcert pinning付きで、傍受にroot+Fridaが要る |
| App内fileの吸い出し | **非rootでは不可(実測)** | `/data/data/<pkg>` はPermission denied。外部領域は読めるが演出packageは無い(後述) |
| **App画面録画** | **成立(実測)** | `LivePlayActivity` に FLAG_SECURE が無く、`screencap`/`screenrecord` とも映像がそのまま取れる |

過去にWeb版で検証した際、premium全画面ギフトはWeb playerでは描画されないことが判っている。
全演出(premium/AR含む)を取れるのは実機App画面録画だけ。

## 環境

- 端末: **ASUS Zenfone 9** (`ro.product.model=ASUS_AI2202`)。ROG Phone 6 は AI2201 で別物
- Android 14 (SDK 34) / 1080x2400 / 440dpi / **非root**(`su` 無し)
- TikTok: `com.ss.android.ugc.trill` (JP build)、live画面は `com.ss.android.ugc.aweme.live.LivePlayActivity`
- adb: 公式platform-toolsを `C:\Users\sanka\tools\platform-tools\` へzip展開(v1.0.41 / 37.0.1)。user PATH追加済

### Git Bashでの必須事項

`/sdcard/...` がWindows pathへ変換されて全滅するため、**`export MSYS_NO_PATHCONV=1` が必要**。

```bash
export PATH="$PATH:/c/Users/sanka/tools/platform-tools"
export MSYS_NO_PATHCONV=1
```

### USBが不安定

連続して `adb exec-out` を叩くと数回に一度 device が消える(`no devices/emulators found`)。
`screenrecord` は端末側に書いてから pull する方式なので録画中のblipでは失われないが、
`settings` の書き換えなど一発ものは失敗を検知して再実行すること。
長時間回すなら `adb tcpip 5555` で無線debuggingへ逃がす。

## 画面の構成(実測)

`dumpsys window displays` の `mAppBounds=Rect(0, 114 - 1080, 2295)` と、
2 frameの画素差分による不変領域検出が完全に一致した。

| 領域 | 座標 | 扱い |
|---|---|---|
| status bar | y 0–113 (114px) | 不透明。演出が隠れる |
| **App領域** | **y 114–2294 (1080x2181)** | ここが使える |
| navigation bar | y 2295–2399 (105px) | 不透明。演出が隠れる |

**クリア表示(フレーム系の非表示)にするとApp側UIはほぼ消える。** 残るのは3つだけ。

- 配信者名chip(左上) / ×(右上) / クリア解除ボタン(左下)

いずれも**半透明**で、映像と混ざるため画素差分では不変領域として出てこない。
matting時はこの3箇所を明示的に除外する必要がある。

### system barは消せない

`settings put global policy_control immersive.full=<pkg>` はAndroid 14で廃止されており**効かない**。
試した後 `settings delete global policy_control` で `null` に戻してある。
上下219pxは欠損として受け入れるか、別手段(root等)が要る。

### 映像surfaceは1080x1920

`dumpsys SurfaceFlinger` のBLAST Consumerが `w/h:1080x1920`(と2枚目 `960x1920`)。
表示領域は1080x2181なので、**Appは9:16の映像を約1.136倍に拡大して縦を埋め、横を約12%切り落としている**。
画面録画の映像部分は源より甘く左右も欠けるので、**映像そのものの採取には使えない**。
演出は画面空間に描かれるため演出抽出には影響しない。

## capture手段の実測

### screenrecord

```
1080x2400 / H.264 High / yuv420p / color_range=tv(limited) / BT.709 / VFR
実効 8.1Mbps  ※ --bit-rate 24000000 を指定しても上がらない
pts差は 16–18ms が主体。cleanな録画での最大gapは 52–53ms
平均fpsは時間帯で 44.6–54.0fps と変動する(配信内容・端末状態による)
```

- `screenrecord v1.3` に**raw出力optionは無い**
- `--time-limit 0` で無制限録画。既定は600秒
- **`pkill -INT screenrecord` で正常にmp4が閉じる**ことを実測確認済

### screencap(可逆)は使えない

PNGで1枚3.0–3.2MB、連射の実測が**約0.9 fps**。3–5秒の演出のframe列には到底足りない。
**mattingはlossy H.264 + 4:2:0 chroma subsampleの上でやるしかない。**

### dumpsys SurfaceFlingerのコスト

| 呼び方 | 実測 |
|---|---|
| adb経由 `--list` | 約350ms ※接続確立が支配的 |
| adb経由 全体 | 約350ms (268KB) |
| **端末内 `--list`** | **19ms** |
| **端末内 全体** | **108ms** |

`adb shell` の起動コストが支配するので、**polling は端末内のloopで回す**こと。

#### 録画への影響 — 対照実験(連続実行)

| run | polling | 平均 | 30ms超 | 最大gap |
|---|---|---|---|---|
| A_clean1 | 無し | 44.8fps | 26.1% | **53ms** |
| B_5hz | `--list` 5Hz | 44.6fps | 27.3% | **146ms** |
| C_clean2 | 無し | 44.7fps | 26.3% | **52ms** |
| D_1hz | `--list` 1Hz | 45.4fps | 22.4% | **116ms** |

**結論: `--list` の polling 自体は無害**(平均fpsもgap分布もcleanと差が無い)。
悪いのは layer変化時に撃っている**全体dump(108ms)**で、単発で116–146msのstall = 約5–7 frameの欠落を生む。
1Hzでも5Hzでも同じく跳ねているのが証拠。

**そしてこのstallが起きるのは「layerが現れた瞬間」= 演出の開始点**という最悪の位置になる。
よって**録画runと全体dump runは分ける**。

通常再生15秒でlayer listが変化したのは2回だけで、noiseは少ない。

## 非rootで見えるfile system(実測)

`/data/data/<pkg>` は Permission denied。一方 shell は `ext_data_rw`(gid 1078) を持つので
`/sdcard/Android/data/<pkg>/` は**読める**(合計113MB)。

| path | 実測 |
|---|---|
| `cache/picture` | 97MB |
| `cache/ttlive` | 14MB。`share_effect/*` の実体はmagic `89 50 4e 47` = **ただのPNG**(共有画像) |
| `cache/newpendant` | magic `50 4b 03 04` = **素のzip** + 展開済みLottie JSON |
| その他 | 各1MB未満 |

**演出packageは外部領域に無い。** ただし `newpendant` が素のzipだったことから、
**全アセットが暗号化されているわけではなく種別による**。

## alpha抽出のalgorithm

合成は各channelで `C = αF + (1−α)B`。C=画面録画、B=背景(配信映像)、F=演出の色、α=不透明度。

### 単一背景では厳密解が無い

未知数が α と F の RGB で計4、観測はRGBの3本。1本足りない。ただし実務上は次が使える。

- **α=0 の判定は厳密**。C == B なら透明で、演出の外形(matte輪郭)は完全に取れる
- **不透明部(α=1)は C がそのまま F**。多くの演出は「不透明な絵 + 加算合成の粒子」なので、
  曖昧になるのは輪郭のアンチエイリアス帯と半透明の発光だけ
- 背景に**textureがあると局所的に解ける**。`C − B = α(F − B)` なので、近傍でαとFがほぼ一定と
  仮定すればBが空間的に変化する分だけ式が増えαが分離できる。**単色背景(特に黒)は最悪**で、
  αとFが完全に縮退する

### 動く背景では原理的に不可能

**演出中のBが未知になるため。** 演出に隠れた瞬間の背景を復元する手段が無い。
`B(演出中) = B(演出前)` が成り立つのは**背景が時間的に不変** = **静止画配信**の場合だけ。

**したがって静止画配信者の確保が素材採取の絶対条件。** 動きのある配信で投げても診断にしかならない。

### 2背景法(triangulation matting)が本命

既知で異なる背景 B1/B2 で同じ演出を捉えれば、観測6本 > 未知4本となり**厳密に解ける**。
静止画配信は「背景が時間的に不変 = 2回の捕捉をframe単位で突き合わせられる」ので相性が良い。
成立には次の2つが前提で、どちらも先に実測で潰す。

1. **演出が決定論的か** — 粒子に乱数が入っていて毎回frame列が変わるなら2背景法は破綻する
2. **全画面演出時にAppが背景を暗転/blurしないか** — していればBが既知でなくなる

### capture由来の制約を設計に織り込む

- **4:2:0で色差が2x2平均される** → 輪郭・細い粒子で色が滲む。
  **αの推定はfull解像度のY主体で行い、色は不透明部からのみ採る**
- **limited range(16-235)** の展開ずれは引き算全体をずらす。
  **BもCも同じscreenrecord経路から取る**(HLS録画側からBを取らない)
- **VFR** → frameの対応付けはpts一致ではなく「**演出開始frameからの経過時間**」で行う。
  落ちたframeは補間せず捨てる

## 明日の手順

### 0. 事前

- USBが不安定なら `adb tcpip 5555` へ
- App側で**クリア表示**にしておく
- **誤タップで課金される。私(Claude)はApp画面を操作しない**

### 1. 無料で済む可能性を先に潰す

ギフトpanelでギフトを選んだときに**送信せずpreviewが出るか**を手で確認する。
出るなら任意の演出を無料で何度でも出せるので、以降のコストが激減する。

### 2. 診断run(安いギフトで可)

確かめるのは3点。**高額ギフトを投げる意味は無い。**

1. 演出発火時に背景が暗転/blurされるか
2. 演出が独自layerとして出るか、その buffer format(RGBAか)と blend mode
3. capture pipelineが演出を取り切れるか(fps・欠落)

録画側:

```bash
adb shell 'screenrecord --bit-rate 24000000 --time-limit 0 /sdcard/rec.mp4' &
# 10秒ほど何もせず置く(背景Bの取得に要る)
# → ギフトを投げる
# → 演出が完全に終わってさらに数秒待つ
adb shell pkill -INT screenrecord
adb pull /sdcard/rec.mp4
```

**180秒の競争ではない。** 無制限で回して投げ終わってから止める。8Mbps ≒ 60MB/分。

layer監視は `watch_layers.sh` を端末へpushして併走させる(`--list` のみなので無害)。
**format/blend確認用の全体dumpは別の発火で撃つ**こと。同じrunで撃つと演出の立ち上がりを失う。

### 3. 決定論性の確認

同じギフトを2回投げ、演出開始frameを揃えてframe列が一致するかを見る。
一致しなければ2背景法は使えないので、そこで方針を組み直す。

### 4. 素材採取

**静止画配信者を見つけてから。** 背景画像の異なる2人が理想。
背景は単色でなくtextureのあるものを選ぶ。

## 未解決

- 演出発火時の背景暗転の有無 — **未測定**
- 演出の決定論性 — **未測定**
- 演出layerのformatとblend mode — **未測定**
- ギフトpanelのpreviewが無料で使えるか — **未確認**
- **静止画配信者の確保** — 素材採取の可否を決める分岐点
- system bar下 219px の欠損をどう扱うか — 全画面演出が上下端まで伸びる型だとそこだけ落ちる
- 既存collectorで同roomを同時に捕捉すれば、gift eventのtimestampから録画中の演出区間を自動で切り出せる。長時間録画路線を採るなら併用の価値あり

## 同梱物

- `watch_layers.sh` — 端末側で回すlayer監視。`adb push` して `sh /sdcard/watch_layers.sh` で起動、
  `adb shell rm /sdcard/gfx/RUN` で停止。既定は `--list` のみで録画に無害。
  引数 `full` を渡すと変化時に全体dumpも撃つが、録画runでは使わないこと。

**時刻の対応付けについて。** watcherのtimestampは壁時計で、screenrecordの起動latencyとpolling間隔
(200ms)の分だけ録画のptsとずれる。**演出区間の正確な時刻は録画のframeから直接読む**こと。
watcherの役目はlayerの構造(名前・出現の有無)を知ることであって、frame精度の時刻源ではない。
