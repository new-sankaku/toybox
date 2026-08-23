# vup — 動画AI高画質化

`realesrgan-ncnn-vulkan-v0.2.0-windows/movie_upscale.py` の置き換え。
サンプル.mp4（720x480、16分34秒）を 1440x960 へ拡大する時間が

| 実装 | 時間 |
|---|---|
| 旧実装（ncnn-vulkan 4並列 + 中間JPEG + libsvtav1） | **18分45秒** |
| vup（本実装） | **1分13秒** |

になります。計測の詳細は `../doc/高速化_計測結果.md` にあります。

## 使い方

**bat は一つ上（`AI_Video_up/`）に置いてあります。**
動画file か、**動画の入った folder** を drag & drop するだけです。
複数まとめて放り込めます（file と folder を混ぜても構いません）。

folder は**下位 folder まで辿って** path 順に処理します。出力は元の動画と同じ場所
（下位 folder の物はその folder の中）へ出ます。
自分が出した `_up` 付きの file は対象から外すので、同じ folder へ何度落としても
出力を二度掛けしません。folder とその中の file を同時に落としても1回だけ処理します。
1本失敗しても残りは続行し、最後に失敗した物を並べます。

| bat | model | 用途 |
|---|---|---|
| `1_動画_アニメ_規定_x2_fast.bat` | `sd-fast` | 既定。SD anime向けで最速 |
| `4_動画_実写_規定_x2.bat` | `photo` | 実写の動画 |
| `7_漫画_規定_x2.bat` | MangaJaNai 1500p + IllustrationJaNai | 漫画の画像。白黒と カラーで model を分ける |
| `8_画像_実写_規定_x2.bat` | `photo` | 実写の画像 |

`models_registry.py` には他の model も残してありますが、重みは置いていません。
名前で呼べば URL のある物は自動でdownloadします（`sd-janai` と漫画系は URL が無いので手動）。

出力は入力と同じ folder に `<元の名前>_up.mp4` として出ます。
model の重みは初回実行時に自動でdownloadします。

folder を落とした時、model の読み込みと TensorRT engine の用意は**最初の1本でだけ**
起きます（同じ process で回すため）。2本目以降の起動は0.4秒程度です。

CLI から使う場合:

```
venv\Scripts\python.exe vup.py 入力.mp4 --scale 2
venv\Scripts\python.exe vup.py 動画folder 別の動画.mp4 --model sd-fast
```

主な option:

| option | 既定 | 説明 |
|---|---|---|
| `--model` | `sd-fast` | model名または `.pth` path。`--list` で一覧 |
| `--scale` | model倍率 | 最終倍率。model倍率より小さければGPU側で縮小 |
| `--dedup` | `balanced` | frame使い回しの判定。`strict` / `balanced` / `aggressive` |
| `--dedup-thresh` | 自動 | 使い回し判定の閾値を直接指定（素材ごとの較正用） |
| `--no-trt` | OFF | TensorRTを使わず torch で推論する |
| `--trt-batch` | 2 | TensorRTのbatch数 |
| `--trt-dynamic` | off | 解像度可変のengineを1本だけ作る。容量が3桁減り(2.6GB→3MB)、速度は同等〜−5% |
| `--encoder` | `hevc_nvenc` | 出力encoder |
| `--encoder-args` | `-preset p4 -cq 24` | encoderへの引数 |
| `--out-pix` | `nv12` | 出力pipeの画素形式。`bgr24` にすると帯域が倍になる |
| `--fps` | 自動 | 出力fps（例 `24000/1001`） |
| `--fps-mode` | `max` | VFR素材の出力fps決定則。`max`=frameを落とさない |
| `--compile` | `auto` | `torch.compile` の使用（`--no-trt` の時だけ効く） |
| `--no-fuse` | OFF | 前後処理を compile graph へ畳まない |
| `--tile-diff` | OFF | 変化した領域だけSRする（既定OFF。後述） |
| `--limit` | 0 | 先頭N秒だけ処理（検証用） |
| `--gpu-prof` | OFF | SRのGPU占有時間をCUDA eventで測る（検証用） |
| `--gpu-share` | 100 | GPU稼働率の上限(%)。他の仕事と同居させる時に下げる。静止画のみ |
| `--img-format` | `webp` | 静止画の出力形式。`webp` / `jpeg` / `png` |
| `--img-gray` | `auto` | 白黒判定。`auto` は画素を見て決める |
| `--img-mono-model` | OFF | `--model` が白黒専用である事を明示。color画像は原本のまま置く |
| `--img-color-model` | なし | color画像だけ別modelで処理する |

### GPUを他の仕事へ譲る（静止画）

`--gpu-share N` は、SRに使った累計時間が経過時間の N% を超えた時だけ待ちます。
1回ごとに固定で休む方式だと、CPU側のdecode/encodeで既に空いている間を数えないため
休み過ぎます。白黒とcolorでbackendが2つでも、上限は1つを分け合います。

640x1280 を60枚、**録画を走らせたまま**の実測（RTX 4070 Ti）:

| 上限 | 実時間 | GPU利用率 中央 | 同 最大 | 電力 最大 |
|---|---|---|---|---|
| なし | 13.8秒 | 35% | 95% | 145W |
| **50**（bat 8 の既定） | 15.0秒 | 24% | 76% | 148W |
| 25 | 28.2秒 | 1% | 64% | 105W |

50 は実時間 +9% で山を95%→76%へ下げます。25 まで絞ると実時間が2倍になります。

## 使える model

720x480 → 1440x960 の実測（RTX 4070 Ti、他のprocessがGPUを使っていない状態）。
「SR単体」は前処理・nv12化・pinned転送まで含めた1 frameあたりの逆数です。

| 名前 | arch | param | torch.compile | TensorRT bs2 |
|---|---|---|---|---|
| **`sd-fast`**（既定） | Compact | 0.30M | 213.4 fps | **333.0 fps** |
| `sd` | Compact | 0.60M | 118.2 fps | 209.5 fps |
| `sd-janai` | Compact | 0.60M | 118 fps | 210 fps |
| `sd-span` | SPAN | 2.22M | 99.6 fps | 157.7 fps |
| `anime`（x4出力） | Compact x4 | 0.62M | 101.6 fps | — |
| `photo`（x4出力） | Compact x4 | 1.20M | 47.0 fps | — |
| `anime-hq`（x4出力） | RRDB 6block | 4.47M | 9.5 fps | — |
| `sd-hq` | RealPLKSR | 7.37M | 8.0 fps | — |
| `photo-hq`（x4出力） | RRDB 23block | 16.7M | 2.8 fps | — |
| `sd-max` | DAT2 | 11.06M | 0.4 fps | — |

`sd-fast` は `--trt-batch 4` にすると 357.3 fps まで伸びますが、
end-to-end では encoder 側が先に詰まるため既定は 2 にしています。

arch は重みの形から自動判定するので、同系統の別の重みも
`--model <path.pth>` で直接渡せます。
全modelが TensorRT で動くことを確認しています。
`sd-max`（DAT2）だけは engine の build に 2GB を超える workspace が要るため、
空きVRAMの半分（上限6GB）を割り当てています。

**`sd` と `sd-fast` の差**: openmodeldb の全671件を調べ、20個以上の重みを実際に
試しましたが、この2つを超える物はありませんでした。`sd-fast` は param が半分で
1.8倍速く、60秒の素材1798 frameで**差が30/255を超えた画素は最悪frameでも0.006%**、
2倍拡大で並べても判別できません（`../doc/model_worst.png`）。
差は線画の輪郭にだけ乗り、平坦部には出ません。

## 何を変えたか

### 1. runtime を ncnn-vulkan から torch fp16 + channels_last、さらに TensorRT へ

同じ model・同じ重みで、出力画素あたりの throughput が桁で変わります。

| 実装 | 実測（`sd`、720x480→1440x960） |
|---|---|
| ncnn-vulkan（旧実装の4並列、全長実測） | 46.6 fps |
| torch fp16 + `channels_last` + `cudnn.benchmark` | 71.5 fps |
| ＋ `torch.compile` | 118.2 fps |
| ＋ **TensorRT fp16 batch 2** | **209.5 fps** |

`channels_last` が効くのは NHWC が Tensor Core の native layout だからです。

TensorRT が torch.compile より速いのは、**epilogue融合と fp16累積**を使えるためです。
torch.compile の 8.54ms の内訳は conv 5.61ms と bias+PReLU の triton kernel 2.68ms で、
conv 単体は既に理論値の84%（72.7 TFLOPS）出ており、torch 側に伸びしろは残っていません。
TensorRT bs=2 は 91.8 TFLOPS で fp32累積の理論値を超えています。

`--trt-batch 2` が要点です。**torch では batch を積むと遅くなりますが
（bs2 で0.92倍、bs4 で0.88倍）、TensorRT だけ batch で伸びます。**
`sd-fast` の実測は bs1 159.2 / bs2 333.0 / bs4 357.3 fps で、bs2 で大半を取り切ります。

int8 と fp8 も試しましたが、**速度が出ないうえに明確に劣化**します
（int8 は PSNR最悪 34.1dB・画素差最大134/255）。fp16 で止めています。

### 2. 中間 JPEG の廃止

旧実装は全frameを JPEG に展開し、`realesrgan-ncnn-vulkan.exe` を directory 単位で
4並列起動し、結果の JPEG を読み直して再encodeしていました。
本実装は decode → GPU → encode を pipe で直結し、中間 file を一切作りません。
16分34秒の素材で約 15GB の一時 file と、JPEG 2回分の劣化が消えます。

### 3. 出力pipeを nv12 にする

SR結果を bgr24（3 bytes/px）ではなく、GPU上で BT.601 limited range の nv12
（1.5 bytes/px）にしてから流します。pipe の帯域が半分になり、nvenc の native 形式
なので ffmpeg 側の色変換も消えます。

色は **swscale より正確**です。float64 の真値からのズレを測ると、
swscale は切り捨てのため Y が系統的に −0.51 暗く出るのに対し、本実装は −0.0015 です。

### 4. frame の使い回し

前回SRした frame と十分近ければ、SR を省いて前回の結果を使い回します。
比較相手は「直前の frame」ではなく「最後に実際にSRした frame」に固定しています。

判定は `|diff|` を **4x4 の box平均へ畳んでから最大**を取ります。h264 の encode noise は
面に薄く広がるので平均で潰れ、瞬きや口のような局所的で濃い変化だけが残ります。

全長16分34秒（出力に使う23,103枚）の実測。欠落画素は使い回した frame と本来の frame で
`|d|>48` の画素数で、判定基準とは独立な指標です。

| `--dedup` | SR回数 | 削減 | 欠落最大 | >100画素のframe |
|---|---|---|---|---|
| `strict`（厳密一致） | 22,818 | 1.01倍 | 0 | 0 |
| `balanced`（既定、box4<16） | 18,559 | **1.24倍** | 13 | 0 |
| `aggressive`（box4<20） | 18,070 | **1.28倍** | 70 | 0 |

実際に動いている frame の `|d|>48` 画素数は p5=268・p10=680・中央9,206なので、
`aggressive` の最悪70画素でも本物の動きの最小規模の1/4以下です。

**この素材の時間方向の余地は元々小さい**ことが判りました。真の source frame の
完全一致率は3.1%です。VFRの段階で既に2コマ打ちが畳まれた後の列
（41.7ms=24fps が79.9%）なので、frame の使い回しで稼げる分は限られます。

閾値は素材の h264 noise 水準に対して選んだ値です。別素材では `--dedup-thresh` で
較正してください。

### 5. VFR 素材の時刻軸

旧実装は `r_frame_rate` を出力 fps として使っていました。
サンプル.mp4 は VFR（41.7ms が79.9%、33.4ms が14.4%、50.0ms が5.6%）で、
`r_frame_rate` は 119.88 と報告されるため、**映像だけが4倍速になります**。

本実装は全 frame の PTS を読み、出力 frame 時刻から表示すべき source frame を引く
対応表を作ります。出力に一度も使われない source frame は SR しません。

decoder には **`-fps_mode passthrough` が必須**です。これが無いと rawvideo muxer に
timestamp が無いため ffmpeg が既定の cfr で VFR入力をCFRへ複製展開し
（24,279 packet の素材が 29,819 frame になる）、自前の複製と二重に掛かって
**映像が徐々に遅れ、末尾が丸ごと欠けます**。

`ffmpeg -ss ... -c copy` で切った素材は先頭GOPの前置きが負のPTSで残っており、
decoder はこれを捨てます。PTS 側でも捨てないと時刻がずれます。

PTS は packet 走査（0.25秒）で引きますが、**1つでも欠けたら frame 走査へ切り替えます**。
AVI の MPEG-4 は packet の PTS が飛び飛びで（実測: 5,815 packet 中 1,056 個しか無く、
間隔も 3〜175 unit とばらばら）、そのまま使うと 59.94fps の素材が **19.98fps** と判定され
**frame が 1/3 に間引かれた上に映像が5.5倍に引き延ばされます**。

frame 走査でも末尾の1枚だけ `best_effort_timestamp` が N/A で出ることがあります
（AVI の MPEG-4 packed bitstream。実測: 5,813 frame 中の最後の1枚）。
decoder はこの frame も出すので捨てられません。容器は全 frame に `duration` を
書いているので、直前の時刻へ足して埋めます。

stream 開始より前の frame を捨てる境目は、`start_time`（秒）ではなく
**`start_pts`（time_base 単位の整数）**で切ります。`start_time` も小数6桁の丸めで、
MPEG-PS の実素材は `start_pts` 30607 / time_base 1/90000 に対し `start_time` が
0.340078 と報告されました。実値 0.34007777… より 2.2e-9 大きいため、
**先頭 frame が自分の開始時刻より前だと判定されて捨てられ**、decoder はその frame も
出すので以降が全部1枚ずつずれていました。

これらは「読み違えても尺も fps も正しく見える」種類の事故なので、
**decode loop の最後に、decoder に frame が余っていないかを確かめます**。
余りがあれば PTS 数が足りなかったということで、出力は先頭 n 枚を全長へ引き延ばした
別物になっています。ここは警告ではなく `RuntimeError` で止めます。
`nb_frames` との突き合わせでは代用できません（AVI の `nb_frames` は index の
entry 数で、実測の R.O.D は 9,448 に対し decoder が出すのは 8,960 枚でした）。

### 6. encoder

**`-preset` は画質だけでなく速度に効きます。** nvenc は別engineですが、
別processの CUDA context として SR kernel と時分割され、SR を待たせるためです。

| 出力 | `-preset p7` | `-preset p4` |
|---|---|---|
| 1440x960（`sd`） | 12.8s | **12.0s** |
| 2880x1920（`anime` x4） | 27.4s | **15.5s** |

x4 では preset を変えるだけで **1.77倍**になります。SR側は何も変えていないのに、
SRのGPU stream占有が 19.7ms → 12.0ms へ落ちます。

`-cq` は品質目標型の rate control なので、速い preset は同じ品質をやや大きい file で
達成します（実測 +3.5%）。既定を `-preset p4 -cq 24` にしています。

### 7. 画素の縦横比（SAR）の引き継ぎ

サンプル.mp4 は anamorphic（SAR 853:720 / DAR 853:480）です。rawvideo で渡すと
SAR が失われて表示 3:2 に潰れるため、入力のSARからDARを計算して `-aspect` で
引き継ぎます。

### 8. decode の読み取りを thread へ

pipe の read を main loop でやると、SR している間 decode が空回りします。
reader thread と buffer pool に分けて、読み取り待ちを 1.84ms/frame → 0.01ms/frame に
しました。

## 採用しなかった手

いずれも実測して棄却しています。理由は `../doc/高速化_計測結果.md` に詳細があります。

| 手段 | 実測 |
|---|---|
| batch化（torchのまま） | bs2 で0.92倍、bs4 で0.88倍。720x480 1枚でSMが埋まる |
| CUDA Graph / `reduce-overhead` | 1.00倍 |
| `max-autotune` | 0.98倍。4070 Tiは60 SMで inductor の閾値68 SM未満 |
| TensorRT int8 / fp8 | 0.86倍 / 0.85倍。遅いうえに劣化 |
| ONNX Runtime CUDA EP | 0.45倍 |
| GPU常駐 pipeline（PyNvVideoCodec） | Windowsで encode が torch tensor を受け付けない。効果も2.6% |
| NVDEC hardware decode | CPUへ戻すぶん CPU decode より遅い |
| encoder の画質knob（multipass/lookahead/b-frame/AQ） | ΔVMAF ±0.04以内。size は最大1.48倍 |
| `-split_encode_mode 3` | 全長で1% |
| tile差分（`--tile-diff`） | 1.01〜1.03倍 |
| h264 の skip macroblock 活用 | 変化macroblock率が中央80.6%で切り出せる形が無い |
| 低解像度SR + 差分補正 | 高周波量が通常の29%（bicubicは21%） |
| optical flow で中間frame生成 | PSNR 32.8（そのまま保持は40.3）。何もしないより悪い |
| 整数画素 pan の再利用 | 該当0 frame |
| 最終convへ縮小を畳み込む | 1.00倍。最終convはFLOPの4.5% |

### tile 差分について

`--tile-diff` として実装は残していますが、**この素材では逆に遅くなります**。
81 frame 中79 frame が全画面SRへ落ち、実効計算量比 0.975 でした。

README の旧版は理由を「h264 の encode noise でほとんどの tile が変化ありになる」と
していましたが、**これは誤りです**。h264 の skip macroblock を使えば noise の影響を
一切受けない完全一致判定ができますが、それでも変化macroblock率は中央80.6%で、
切り出せる形がありません（矩形1個97.2% / 横帯97.9% / tile128 98.6% の面積）。
真因は **変化が画面全体に散っていること**です。

静止背景が長く続く素材では効く可能性があるので option として残しています。

## 構成

```
vup.py             本体
trt_backend.py     TensorRT engine の生成と実行
models_registry.py model一覧と重みの自動download
srvgg.py           SRVGGNetCompact の実装（basicsr非依存）
rrdb.py            RRDBNet の実装（basicsr非依存）
tilediff.py        tile差分（既定OFF）+ 受容野の実測
models/            model の重み
trt_engines/       TensorRT engine の cache（1つ400〜650MB）
exp_*.py           数値を測った実験script
venv/              Python環境（--system-site-packages で作成）
```

`trt_engines/` は (重みfile, 入力解像度, 倍率, batch, 画素形式, TensorRT版, GPU名) ごとに
1つ作られます。初回だけ20〜45秒掛かり、以降は0.75秒で読み込みます。
disk を空けたい場合は folder ごと消して構いません（次回作り直します）。

## 環境

Windows 11 / RTX 4070 Ti 12GB / Python 3.10 / torch 2.10+cu126 / TensorRT 11.2 /
ffmpeg full build。`torch.compile` のために `triton-windows` を入れています。

venv は `AI_Video_up/0_環境を作る.bat` で作ります（`AI_Video_up/requirements.txt` から
`vup/venv` へ入れます）。1〜8 の bat と `vfi2` も同じ venv を使います。
torch と torchvision は cu126 版が PyPI に無いため、bat が
`--extra-index-url https://download.pytorch.org/whl/cu126` を足しています。

model の重みは git に入れていません。`models_registry.py` に載っている名前（`sd-fast`,
`photo` など）は初回実行時に `models/` へ自動で落とします。漫画用の bat 7 が使う
`2x_MangaJaNai_1500p_V1_ESRGAN_90k.pth` と `2x_IllustrationJaNai_V1_ESRGAN_120k.pth` は
registry に無く、path 直指定なので `models/manga/` と `models/color/` へ自分で置いてください。
`vfi2` の model は `vfi2/models/` へ各 repo を clone してください。

## 起動時間

`import torch` が4.2秒掛かるのは避けられませんが、それ以外は削ってあります。

- `import spandrel` は52 arch すべてを読み込むため単体で3.7秒掛かります。
  SRVGGNetCompact 系は重みの形から自前実装で組む経路を用意し、spandrel を通しません
  （spandrel版と出力差 0.000000 を確認済み）。一致しない重みは従来通り spandrel へ落とします
- `torch.compile` は約4.5秒掛かり、1 SR回あたり3.2ms速くなります。損益分岐は約1400 SR回で、
  短い素材では元が取れないため `--compile auto` が素材の長さで判断します
- TensorRT を使う場合は `torch.compile` が不要になるため、起動は3.5秒です
