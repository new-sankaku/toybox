# VFI model 比較（RIFE 以外を含む）

素材は Arknights 24話(1080p, 24000/1001 fps)から切った lossless clip 3本。
試験集合の作り方・metric・記録の規則は本 folder の `m1_testset.py` 〜 `m5_report.py`
に置いてあります。数値はすべて実測で、出典は `results/results.jsonl`。

- 共通 interface: `vfi2/vfimodels.py`（`predict(f0, f1, tau) -> uint8 BGR HWC cuda tensor`）
- 試験集合: `vfi2/m1_testset.py`
- 速度と品質: `vfi2/m3_bench.py`（`m3_run.py` が model ごとに別 process で回す）
- 任意 tau: `vfi2/m4_tau.py`

（本 file は作業中に随時更新しています。最終の表は「結論」節を見てください）

---

## 1. 候補 model の調査

「任意 tau 対応」は **signature に t があるか** ではなく **t を振ると出力が変わるか**
で判定しています。IFRNet の Vimeo90K 重みは signature に embt を取りながら
tau=0 と tau=1 の出力差が 2.2e-6 しかありませんでした（前回の実測）。

### 実際に動かした物

| model | 素性 | 入手 | 任意 tau | anime 適性の根拠 | cost |
|---|---|---|---|---|---|
| RIFE v4.26 / v4.26_heavy / v4.25_lite | 中間 flow 直接推定。t が入力 ch | vs-mlrt の ONNX（取得済み） | 設計上あり | v4.25/v4.26 の release note が anime 改善を明記 | 最小。TensorRT 済み |
| RIFE v4.26_heavy (torch) | 同上の torch 実装 | DRBA 同梱 `weights/train_log_rife_426_heavy` | あり | 同上 | 小 |
| GMFSS_Fortuna_b | GMFlow + MetricNet + softsplat + GridNet | vfi/gmfss（取得済み） | あり（flow は pair で1回、合成だけ t 依存） | 作者が「anime 専用」と明記 | 中。TensorRT 未 |
| **GMFSS_union** | 上に RIFE を合流させた版 | **DRBA 同梱** `weights/train_log_gmfss_union` | あり | SVFI の quality 既定 | 中 |
| **GIMM-VFI-R-P / F-P** | 双方向 flow から時空間 motion latent を作り、座標入力の INR が **任意時刻の flow を直接吐く** | HF `GSean/GIMM-VFI` | **設計の中心** | 汎用だが LPIPS 学習版あり | 大。1080p は ds_factor 0.5 が上限 |
| **EMA-VFI (ours_t)** | frame 間 attention。任意時刻専用の重み | HF `xmanifold/emavfi` | あり（`ours_t` が任意時刻学習） | 汎用 | 中 |
| **FILM** | 大変位に強い。scale-agnostic な特徴 pyramid | dajes の torchscript 移植 release | signature にあり（**学習は t=0.5 のみ**。実測で判定） | 汎用 | 中 |
| IFRNet_GoPro | 直接 warp + refine | vfi/ifrnet（取得済み） | GoPro 重みはあり | anime 向きでない（前回実測） | 小 |

### 調べたが動かさなかった物と、その理由

| model | 入手可能性 | 任意 tau | anime 適性 | 見送りの理由 |
|---|---|---|---|---|
| **DRBA** (routineLife1) | ○ code+重み一式が repo 同梱 | **model ではなく時刻を決める側** | anime のコマ打ち専用に作られた | model ではないので同じ表に載らない。別項で扱う（→ 5節） |
| MultiPassDedup (routineLife1) | ○ | 同上（前処理） | 同上 | 同上。DRBA の姉妹。「重複を消す」のではなく「元 frame を繰り返し更新する」方針 |
| VFIMamba (NeurIPS 2024) | 重みは HF `MCG-NJU/VFIMamba` | あり | 汎用 | `mamba-ssm` の CUDA 拡張が Windows で build できない。CUDA toolkit は v11.3 しか無く torch は cu126 で、拡張の compile 環境が無い |
| EISAI (ECCV2022, anime 専用) | ○ | **中間 1枚のみ**（t 固定） | anime 学習 | tau を取れないので今回の用途では使えない |
| AnimeInterp (CVPR2021) | ○ | **中間 1枚のみ** | anime 学習 | 同上 |
| ToonCrafter (SIGGRAPH2024) | ○ | 出力は固定長の系列で tau 問い合わせではない | anime 生成 | 512x320 級の生成 model で 1080p を通せない。中身を作り出すので線が別物になる |
| sudo_rife4 (styler00dollar) | ncnn/onnx が VSGAN docker 経由 | RIFE 4.x 系なのであり | anime finetune | v4.0 世代の finetune で、v4.25/v4.26 の anime 改善より前。優先度が低い |
| SGM-VFI (CVPR2024) / PerVFI | ○ | 実装依存 | 汎用 | 大変位向けだが FILM と役割が重なる。FILM を先に測って判断 |
| SVFI（実運用 tool） | 商用(Steam) | - | - | 中身は GMFSS + 独自 dedup。**参照すべきは「何を使っているか」で、GMFSS と dedup がそれ**。GMFSS_union を測るのが実質同じこと |

---

## 2. 試験集合

「絵の列」で組みます。連続する3枚の絵 D0, D1, D2 の真ん中を、両端と実際の
時間比 `tau = (r1-r0)/(r2-r0)` から作って本物と比べます。cut を跨ぐ組と
D0→D2 が 12 frame を超える組は除きます。

| clip | frame | 絵 | 1枚あたり frame | 候補の組 | 採った組 | 跨ぎ変位 p50 | 同 max |
|---|---:|---:|---:|---:|---:|---:|---:|
| A_op (OP) | 720 | 649 | 1.11 | 574 | 135 | 61.1 px | 232.8 px |
| B_talk (会話) | 719 | 132 | 5.45 | 106 | 72 | 3.4 px | 56.0 px |
| C_act (戦闘) | 719 | 263 | 2.73 | 226 | 121 | 26.5 px | 285.5 px |

層は D0→D2 の optical flow p95（1080p 画素）で 7つに分けます。各層から同数まで
取るので、**全体平均は層の母数で重み付けし直しています**（素の平均は稀な難所を
過大評価する）。層ごとの母数:

| clip | 0-4 px | 4-8 | 8-16 | 16-32 | 32-64 | 64-128 | 128- |
|---|---:|---:|---:|---:|---:|---:|---:|
| A_op | 17 | 9 | 16 | 33 | 230 | 248 | 21 |
| B_talk | 58 | 14 | 4 | 20 | 10 | 0 | 0 |
| C_act | 74 | 12 | 7 | 23 | 62 | 41 | 7 |

A_op は 1コマ打ちなのに跨ぎ変位の中央値が 61 px あります。**OP は frame 間で
既に model の破綻域に入っている**ということで、ここは補間で得をする場面では
ありません。B_talk は逆に中央値 3.4 px で、5.45 frame 保持されているぶん
「絵と絵の間」は近い。

### 任意 tau の試験集合（3節の tau 検証で使う）

絵が3枚だと真ん中の tau が 0.5 に張り付きます（|tau-0.5|>=0.15 の組は
A_op 574中49 / B_talk 106中12 しかありません）。そこで tau の検証だけは
**絵4枚 D0,D1,D2,D3 を取り、両端 D0,D3 から内側の2枚を作ります**。
内側は tau≒1/3, 2/3 に落ちるので、tau を無視する model とそうでない model が
はっきり割れます。しかも「絵を等間隔でない時刻へ置き直す」という本番の
使い方そのものです。

| clip | 4枚組の母数 | 試験に採った数 | tau の p5 / p50 / p95 | 跨ぎ変位 p50 |
|---|---:|---:|---|---:|
| A_op | 543 | 80 | 0.333 / 0.333 / 0.667 | 61.5 px |
| B_talk | 96 | 80 | 0.329 / 0.500 / 0.750 | 5.7 px |
| C_act | 212 | 80 | 0.250 / 0.586 / 0.801 | 34.8 px |

---

（3節・4節は計測が終わり次第）


---

## 5. DRBA（Distance Ratio Based Adjuster）— 設計の参考

**model ではなく「時刻を決める側」です。** RIFE / GMFSS / GMFSS_union を包んで、
timestep 引数へ scalar ではなく **画素ごとの時刻 map** を渡します。

### 仕組み（`models/DRBA/models/drm.py` を読んだ結果）

連続する3枚 I0, I1, I2 について flow(I1→I0) と flow(I1→I2) を取り、その長さ
d10, d12 から画素ごとに

    drm10 = d10 / (d10 + d12)

を作ります。**動いた距離を時間の代わりに使う**発想で、「I1 から I0 へ2倍
動いていれば I1 は I2 寄りの時刻に居る」と読みます。これは我々が
`tau = (r1-r0)/(r2-r0)` と書いている量の、frame 番号を使わない推定版です。

`get_drm_t(drm, t)` は「map 全体の代表時刻を 0.5 から t へ寄せる。ただし
画素間の比は保つ」変換で、二分法で t へ近づけながら各画素を同じ割合だけ
端へ寄せます。出力側の等間隔な時刻を、素材側の不均等な時刻へ写す部分です。

要するに DRBA は **チームの中心仮説とほぼ同じことを、frame 番号を使わずに
画素から推定してやっている**設計です。

### この素材で成立するか（実測）

#### (a) 絵の列の上（= 我々の試験集合と同じ土俵）

| clip | n | DRM推定 と 真tau の MAE | 「常に0.5」と真tau の MAE | 相関 | 画面内のばらつき(p90-p10) |
|---|---:|---:|---:|---:|---:|
| A_op | 135 | 0.367 | **0.016** | -0.04 | 0.412 |
| B_talk | 72 | 0.209 | **0.028** | 0.08 | 0.278 |
| C_act | 118 | 0.289 | **0.060** | 0.24 | 0.370 |

絵へ畳んだ後は、**絵と絵はほぼ等間隔に並んでいます**（「常に 0.5」の誤差が
0.016〜0.060）。直すべき時刻がほとんど無い所へ DRM を当てると、推定誤差
（0.21〜0.37）のぶんだけ悪くなります。

#### (b) 生の frame 列（= DRBA が本来相手にする土俵）

frame i, i+1, i+2 が属する絵の番号 k0, k1, k2 から真値 `(k1-k0)/(k2-k0)` を作り、
DRM がそれを当てられるかを見ます。2コマ打ちなら真値は 0 か 1 の二択です。

| clip | 1枚あたり frame | n | DRM推定 の MAE | 「常に0.5」の MAE | 相関 | 真値の内訳 |
|---|---:|---:|---:|---:|---:|---|
| A_op | 1.11 | 150 | 0.280 | **0.090** | 0.50 | 0が16 / 0.5が123 / 1が11 |
| B_talk | 5.45 | 150 | **0.109** | 0.483 | 0.89 | 0が78 / 0.5が5 / 1が67 |
| C_act | 2.73 | 135 | **0.209** | 0.237 | 0.71 | 0が36 / 0.5が71 / 1が28 |

**DRBA の効き目は素材の保持量に正比例します。** 5.45 frame 保持される会話場面では
相関 0.89 で「常に0.5」の 4.4倍正確。1コマ打ちの OP では逆に効かない（真値が
既にほぼ 0.5 だから）。

### この Project にとっての結論

1. **DRBA の推定段は要りません。** 我々は `lib.drawing_runs()` で絵の切り替わり
   frame を持っており、tau は frame 番号から**正確に**出ます。DRM の推定誤差は
   0.11〜0.28 で、ただで得られる正解より悪い。
2. **DRBA の per-pixel は、少なくともこの素材では根拠が薄い。** 画面内の
   ばらつき（p90-p10）は **全編1コマ打ちの A_op で最大の 0.412** でした。
   領域ごとに cadence が違うなら A_op でこそ 0 に近いはずで、逆に最大という
   ことは、**このばらつきは cadence の差ではなく flow の雑音**です。
3. 採るべきは DRBA の**問題設定**（絵の時刻を測って張り直す）であって、
   実装（動きから時刻を推定する）ではありません。
