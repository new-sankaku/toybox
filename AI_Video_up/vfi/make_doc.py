"""doc/フレーム補完_計測結果.md を組み立てる。表の数字は results.jsonl から引く。"""
import report as RP
import vfilib as V

MODELS_FOR_BINS = ["hold", "blend", "v4.6", "v4.4", "v4.25_lite", "v4.26",
                   "v4.26_heavy", "GMFSS_Fortuna_b"]

DOC = f"""# フレーム補完(VFI)の計測結果

anime を x2(23.976 -> 47.952 fps)で滑らかにする前提で、**model・速度・品質**を
実測した記録です。環境は Windows 11 / RTX 4070 Ti 12GB / TensorRT 11.2.1.2 /
torch 2.10+cu126。script は `vfi/`、生の記録は `vfi/results/results.jsonl` に
1件ずつ追記してあります。

---

## 0. 結論

1. **素材で全部変わります。** 同じ話数の中でも、OP は補間対象の 42.5%、
   本編の会話場面は 8.7% しか model を呼ぶ必要がありません。5倍違います。
   「どの model が速いか」より先に「何回呼ぶか」を決める話です。

2. **一番効いた高速化は model ではなく pipe の読み方でした。**
   `subprocess.Popen(..., bufsize=w*h*3*8)` を外すだけで 1080p の decode 読み取りが
   **31.4 fps → 223.7 fps (7.1倍)** になります。直す前は「補間を一切しない」場合でも
   60 fps 頭打ちで、model の速さが一切見えていませんでした。
   **`vup/vup.py` も同じ書き方をしています**(720x480 で 943 → 1851 fps、1.96倍)。

3. **`lite` は 1080p では速くありません。** 一番速いのは古い `v4.4` / `v4.6` で
   5.2ms(190 fps)、`*_lite` はどれも 10.3〜12.3ms(81〜97 fps)です。約2倍違います。

4. **model 間の品質差は小さく、baseline との差の方が大きい**です。
   会話場面の LPIPS は最良 0.0153 〜 最悪 0.0190(24%の幅)に対し、
   補間しない hold は 0.0234、単純平均は 0.0261 です。

5. **跨ぐ変位が 32px を超えると、model は「何もしない」に負けます。**
   OP は隣接pairの 51% がこの領域に入ります。会話場面は 0% です。
   speed も quality も、**動きが大きすぎる所では呼ばない**のが正解です。
   ご指摘の「動きの激しい部分を中心に」は、**節約になるのは逆側(静止)**で、
   激しい側は「やらない」側に倒れます。

6. **出力側(nvenc)は天井ではありません。** 1080p の hevc_nvenc p4 が 402 fps、
   `-split_encode_mode 3` で 572 fps 出ます。x2 でも詰まりません。

7. 実効値。30秒の素材を 48fps へ書き出すまで、**会話場面 5.5秒 / OP 6.6秒**
   (`v4.6`、実時間の 5.5倍 / 4.6倍速)。

---

## 1. 素材

指定の 1:30-2:00 は OP でした。OP は cut と effect が多く 1コマ打ちで、
anime としては最も辛い部類です。判断を誤らないよう、対照として本編の会話場面
(4:00-4:30)も同じ長さで切り出し、両方で測っています。
どちらも lossless(x264 -qp 0)で切ってあるので、以降の実験はすべて同じ画素の上を
走ります。

{RP.section_cadence()}

- **A_op**: 720 frame すべてが別の絵(1コマ打ち)。cut 37回(0.8秒に1回)。
- **B_talk**: 絵は 132枚しかなく、**1枚が 5.45 frame 保持**されます。
  つまり実質 4.4 枚/秒。隣接pairの 81.8% は絵が変わっていません。

この差が、以降のすべての数字の効き方を決めています。

---

## 2. 測り方（2回作り直しています）

生成した中間frameには正解がありません。実測できるのは **1枚落として復元** だけです。

**最初の版(破棄)**: 連続する3 frame (i-1, i, i+1) の真ん中を両端から作る。
B_talk では 120組中 **117組**が片側 box4<16、つまり「i-1 と i がほぼ同じ絵」でした。
2コマ打ちの中を抜いているので hold が自動的に満点を取り、model の巧拙が消えます。
条件を「3枚とも別の絵」に絞ると、**B_talk で有効な組は 718組中 8組**しか
残りませんでした。frame単位の試験は anime では成立しません。

**現在の版**: **絵の列**で組みます。box4 が閾値未満なら同じ絵として run へ畳み、
連続する3つの絵 D0, D1, D2 の真ん中を、両端と実際の時間比 tau から作ります。

    tau = (r1 - r0) / (r2 - r0)      r* は各絵の最初のframe番号

これは x2 補間が実際にやること(隣り合う絵の間を作る)と同じ問題です。
ただし **跨ぐ間隔は1段広い**ので、出る数字は本番より辛い側に出ます。

cut を跨ぐ組と、1秒近く止まった後の組(span > 8 frame)は除いています。
cut は補間せず hold するのが正解で、model の優劣と無関係だからです。

cut の判定は自前の閾値ではなく **ffmpeg の `scdet`** を使いました
(A_op 37件 / B_talk 6件、検出結果を並べて目視確認済み。`results/cuts_*.png`)。
A_op では閃光や炎の effect が cut として拾われますが、そこは補間しても破綻する
領域なので、試験集合から外れる方が正しく働きます。

metric は PSNR・LPIPS(AlexNet)・GMSD・|d|>48 の画素数の4つを取りました。
**anime では PSNR が判断を誤らせます**。後述の通り、単純平均は PSNR で model に
勝つのに、絵は二重像です。順位は LPIPS で見てください。

---

## 3. model: 速度

### 単位について

**「補間1枚」は、2枚の frame から中間の1枚を作る推論1回**のことです。
x2 の出力 fps とは別物なので、混同しないでください。

- `engineのみ` … TensorRT engine の実行だけ。入力は既に GPU 上にあり、
  H2D / D2H も前処理も含みません(CUDA event の中央値)
- `前後処理込み` … 上に pack(uint8 BGR → RGB fp16 正規化)と
  unpack(→ uint8 BGR)を足したもの。GPU 上で完結します

**出力 fps との関係**: x2 の出力 2N-1 frame のうち、偶数番は元の frame
そのままで推論は要りません。奇数番の中でも、前後が同じ絵なら写すだけです。
実際に呼ぶ回数は素材で変わります。

| 素材 | 出力 frame | model 呼び出し | 所要 | 出力 fps |
|---|---|---|---|---|
| 本編の会話場面 | 1,437 | **125回** | 5.5秒 | 262.1 |
| OP | 1,439 | **453回** | 6.6秒 | 219.3 |

`v4.6` は 188枚/秒ですが、会話場面では 125回しか呼ばないので、
出力 262 fps のうち model が占めるのは 0.5秒(全体の1割)です。

### 実測

1920x1080、fp16、batch 1。

{RP.section_speed()}

- **`v4.4` / `v4.6` が 5.2ms で突出**しています。`*_lite` は 10.3〜12.3ms。
  重みの大きさ(lite 10MB / 通常 20MB)と速度は対応しません。
- run 間のばらつきは ±10% あります(同じ engine を測り直して 10.51ms と 11.72ms)。
  **10%以内の差は分解できていません。** 5.2 / 10.4 / 14.5 / 26.3 の4つの段は確かです。
- engine の build は 20〜32秒、engine file は 102〜346MB です。

---

## 4. model: 品質

上の試験集合(A_op 120組 / B_talk 102組)。`hold` は前の絵をそのまま出す、
`blend` は時間比で重み付けした単純平均です。**LPIPS の低い順**に並べています。

### B_talk（本編の会話場面。典型的な anime）

{RP.section_quality("B_talk")}

**全 model が hold と blend に勝ちます。** 差が出るのは「LPIPS 大」の列
(動きの大きい層)で、model 0.035 に対し hold 0.060 / blend 0.063 です。
model 同士は 0.0153〜0.0190 の幅しかありません。

### A_op（OP。cut と effect が多く、動きが極端）

{RP.section_quality("A_op")}

ここでは **blend が総合 LPIPS で1位**です。ただし内訳を見ると、
「LPIPS 小」では model(0.082)が hold(0.097)・blend(0.099)に勝っており、
負けているのは動きの大きい層だけです。次章で分けます。

### RIFE 以外

最初に RIFE ばかり測ったのは、TensorRT へそのまま載る ONNX が RIFE しか
配られていないからでした(vs-mlrt の配布物に VFI は RIFE だけ)。
**これは測らない理由になりません**。PyTorch の実装 code と重みを繋いで測りました。

{RP.section_other()}

- **GMFSS_Fortuna**(anime向けとして定評がある): 499.4ms。`v4.6` の **94倍遅く**、
  LPIPS も会話場面 0.0175 対 0.0174、OP 0.2081 対 0.2052 で並びか下。
  GMSD(線画の崩れに効く軸)は 0.0508 対 0.0468 で明確に負けます
- **IFRNet**: 65.7ms で **12倍遅く**、LPIPS は会話場面 0.0399 対 0.0174 と
  倍以上悪い。GoPro(実写・motion blur あり)で学習した重みなので anime には
  向いていません

条件を付けておきます。

- **どちらも TensorRT に載せていません**(torch fp16 autocast)。
  GMFlow は transformer を含み ONNX 化に手が要り、GMFSS は CuPy 版の softsplat が
  使えず pure-torch 版に落ちています。RIFE 側(TensorRT)より不利な条件です
- GMFSS は 1 pair から複数枚作る時 flow を使い回せて 180.4ms まで下がりますが、
  x2 は 1 pair 1枚なので効きません
- GMFSS の重みは `base` 版です。`union` 版は `rife.pkl` が要りますが配布元に無く、
  base より重い構成です
- **IFRNet の Vimeo90K 重みは tau を無視します**。Vimeo90K の三つ組は常に真ん中で、
  学習中 t=0.5 しか見ておらず embt が信号になっていません
  (実測: tau=0 と tau=1 の出力の最大差 2.2e-6)。任意時刻が要るので
  GoPro(8x学習、同 0.54)を使いました

仮に TensorRT で3倍速くなったとしても GMFSS 6 fps / IFRNet 46 fps で、
`v4.6` の 188 fps には届きません。**品質でも上回らないので採る理由がありません。**

まだ測っていない物: FILM(TensorFlow SavedModel で ONNX への変換に手が要る。
大変位に強いとされるので、5章の 32px の壁に対しては試す価値があります)、
EMA-VFI、SoftSplat 系。

---

## 5. 跨ぐ変位で見る（本番の作動点）

model が実際に跨ぐ変位(D0 から D2 への optical flow の p95、原寸px)で刻みます。
括弧内は組数です。

### A_op

{RP.section_lpips_vs_motion("A_op", MODELS_FOR_BINS)}

### B_talk

{RP.section_lpips_vs_motion("B_talk", MODELS_FOR_BINS)}

**境目は 32px 付近**です。それ以下では model が hold/blend に明確に勝ち
(16-32px で A_op 0.059 対 0.077/0.072、B_talk 0.039 対 0.056/0.058)、
64px を超えると blend に負けます。

x2 本番で model が跨ぐのは隣接pair1つぶんです。その分布は

- **A_op**: 0-4px 22% / 4-8px 7% / 8-16px 7% / 16-32px 14% / 32-64px 23% /
  64-128px 24% / 128px以上 4% … **51%が32px超**
- **B_talk**: 0-4px **94%** / 4-8px 1% / 8-16px 2% / 16-32px 2% / それ以上 0%

つまり会話場面では model は 6% の場面でだけ働き、そこでは確実に勝ちます。
OP では半分が model の効く範囲の外です。

最悪例を並べた絵が `results/look_A_op_worst.png` にあります。
大変位の frame では全 model が溶けた絵を出し、blend の方がまだ形を保っています。
`results/look_B_talk_worst.png` では逆に、blend が二重像なのに対し model は
輪郭を保っており、**PSNR では blend が勝っているのに絵は model が良い**という
逆転がはっきり見えます。

---

## 5b. 補間は何を変えたのか（frame ごとの数値）

「見ても差が分からない」に対して、推測でなく数値で答えます。
`results/diff_<clip>.csv` に全 frame 分あります。

読み方: **`元の2枚の差` が補間frameの動ける上限**です。元の2枚が同じ絵なら、
どんな model を使っても複製と同じ絵にしかなりません。

{RP.section_diffreport()}

### model のせいか、構造か

上の表は「差が小さい」ことしか言っていません。原因を分けます。

tau=0.5 の補間frameは、元の2枚が違っている画素のうち **およそ半分**を
動かすのが理屈上の目安です。0% に近ければ model が何もしていない、
50% 前後なら model は出せる分を出している、ということになります。

{RP.section_capacity()}

**構造です。**

- **B_talk（会話場面）は、補間位置 712 のうち 587（82.4%）で、
  元の2枚に `|d|>48` の画素が1つもありません。** ここは何を使っても複製と
  同じ絵にしかなりません。model の性能とは無関係です
- 残る 125 箇所では、model は違う画素の **中央 32.6%** を動かしています
  （目安 50%）。動いています
- **A_op（OP）では動かした割合の中央が 49.4%** で、目安そのものです。
  素材が動いていれば model は素直に働きます

つまり「典型的な anime 会話場面で x2 補間の効果が小さい」のは、
model を替えても倍率を上げても変わらない、**素材の側の性質**です。
30秒で目に見える差が出るのは 38 frame（5.3%）、実時間 0.79秒ぶんでした。

---

## 6. 補間を「呼ばない」判定（速度の本体）

x2 の出力 2N-1 frame のうち、偶数番は source そのままで model は要りません。
奇数番(補間対象)の中でも、前後が同じ絵なら前の frame を写すだけで足ります。

{RP.section_gate()}

- **B_talk は閾値8 で 5.70倍**(712回 → 125回)。閾値を12以上に上げても増えません。
  絵が変わる時は box4 が一気に 100 を超えるので、判定は素直に効きます。
- **A_op は 1.12倍**しか減りません。1コマ打ちなので当然です。
- 省いた組で「model を呼んだ絵」と「写した絵」を比べると、B_talk は
  |d|>48 の画素が **1つも出ません**(box4 の最大でも 17)。**ただ取りです。**
- A_op は閾値8以上で最悪 3035画素の差が出ます。1920x1080 の 0.15% ですが、
  1コマ打ちの素材では減る量(1.12倍)に見合いません。**閾値4 で止めるのが妥当**です。

素材によって最適な閾値が違うので、`--gate` として外に出しています。

---

## 7. 解像度と batch

`v4.25_lite`、fp16。

{RP.section_scale()}

- **batch は 1080p では効きません**(bs2 で 0.95倍)。1枚で SM が埋まっています。
  効くのは 960x540 以下(bs2 で 1.9倍)で、SD素材に補間を掛ける時だけの話です。
  vup の SR が TensorRT bs2 で 1.8倍になったのと同じ理屈で、
  **1枚あたりの計算量が足りているかどうか**が分かれ目です。
- 1Mpxあたり 5.7〜6.0ms でほぼ一定です。**3840x2160 は 1920x1080 の 4.1倍**掛かります。
  SR と組み合わせる場合、**補間は SR の前(低い解像度側)でやるべき**です。
  SR 後にやると、1回 47.9ms(20.9 fps)まで落ちます。

---

## 8. flow の解像度（scale）

「動きの激しい所を中心に計算する」を、空間の切り分けではなく **flow の解像度**で
やる手です。vup で tile差分が失敗した理由(変化が画面全体に散っている)を踏みません。
v4.7 以降の重みでは使えないため、v1実装の ONNX に定数手術を掛けて `v4.6` で測りました。

{RP.section_scale05()}

- **scale=0.5 は 1.48倍速く(5.78ms → 3.90ms)、品質はほぼ変わりません。**
  A_op はむしろ僅かに改善(0.20484 → 0.20441、大変位の層で 0.27369 → 0.27033)、
  B_talk は僅かに悪化(0.01624 → 0.01691)。
- **scale=0.25 は速くも良くもなりません**(pad が 1152 に増え、5.63ms)。
- `v4.6` + scale=0.5 の **3.90ms(256 fps)が今回の最速**です。
- 期待していた「大変位の破綻が治る」効果は、**測ると誤差の範囲**でした。
  32px の壁は scale では越えられません。

v1実装は v2実装と別の ONNX ですが、同じ重みで出力を突き合わせると
PSNR 中央 52.4dB / 最小 47.5dB で一致します(pad の埋め方の違い)。

---

## 9. fp16 と fp32

TensorRT 11 は strongly typed network しか作れず `BuilderFlag.FP16` がありません。
精度は ONNX 側で決めるので、fp16 で回すには ONNX を fp16 へ変換します。

{RP.section_prec()}

- **fp16 は 2.0倍速い**(23.7ms → 12.0ms)。
- 品質は A_op で LPIPS 0.19849 → 0.19872(差なし)、B_talk で 0.01445 → 0.01531
  (6%悪化)。
- 出力を直接ぶつけると、B_talk は |d|>48 の画素が最大 **2つ**。
  A_op は最大 3498画素(全体の0.17%)で、大変位の frame に偏ります。
- **fp16 を採ります。** 悪化が乗るのは、そもそも補間を呼ぶべきでない領域です。

理屈の上では、RIFE は flow を GridSample の正規化座標へ直す時に 2/(W-1) 倍します。
1920幅なら 1.04e-3 で、fp16 の 1.0 近傍の分解能 9.8e-4 と同じ桁です。
座標計算だけ fp32 で残す graph 手術も試しましたが、Cast の型が食い違って
engine の build が通りません(`/encode/cnn0/Conv: input=Float kernel=Half`)。
実測の差が小さいので、そこまでやる必要はないと判断しました。

なお `onnxconverter_common` の fp16 変換は **`Cast(to=FLOAT)` と
`ConstantOfShape(value=fp32)` を書き換えません**。attribute の中に型があるため
tensor の走査で見つからず、残すと `Reciprocal → Mul` で fp32 と fp16 が同じ演算に
入って TensorRT の parse が落ちます(`/Mul: ElementWiseOperation PROD must have
same input types`)。後処理で直しています(`rifelib._fix_float_attrs`)。

---

## 10. 出力側の天井と、pipe の読み方

### encoder

rawvideo(nv12)を流し込んで書き出すだけの速度です。入力は乱数(encoder にとって
最悪の絵)なので、実素材ではこれより速く出ます。

{RP.section_encoder()}

- **1080p の hevc_nvenc p4 は 402 fps**。x2 の出力(48fps)に対して8倍以上あり、
  天井ではありません。当初「出力側が先に詰まる」と見立てましたが、**外れです**。
- `-preset p7` は 172 fps まで落ちます。p4 が妥当です。
- **`-split_encode_mode 3` で 572 fps(1.42倍)**。vup の SR では全長で1%でしたが、
  それは SR が律速だったからで、encode 単体では効いています。
- 3840x2160(x2 SR を掛けた後)でも p4 で 103 fps あります。

### pipe の読み取り

**ここが本当の律速でした。**

{RP.section_pipe()}

`subprocess.Popen(..., bufsize=N)` に 1枚ぶんより大きい値を渡すと、Python の
`BufferedReader` は「要求サイズ < buffer サイズ」なので内部 buffer を経由します。
1080p では 6.2MB の `readinto` ごとに 49MB の buffer を相手にすることになり、
**7.1倍遅くなります**。`bufsize` を既定(-1)にすると、1枚ぶんの `readinto` が
raw read へ素通りして直ります。

**`vup/vup.py` の decode も同じ書き方です**(`bufsize=w * h * 3 * 8`)。
720x480 では 943 → 1851 fps(1.96倍)。vup は reader を別threadにしてあるので
end-to-end に効くとは限りませんが、天井は倍になります。

---

## 11. 端から端まで

`decode(ffmpeg) → reader thread → GPU(判定+補間+nv12) → writer thread → nvenc`。
30秒(720 frame)の素材を 47.952fps へ。判定は box4 閾値16、cut は hold。

{RP.section_e2e()}

- 会話場面は **model を入れても入れなくても同じ速度**(262 vs 261 fps)です。
  125回しか呼ばないので、model の costが見えません。
- OP は 453回呼ぶので差が出ます。`v4.6` 219 fps に対し `v4.26_heavy` は 84.6 fps。
- 判定を CPU(`cv2.absdiff` + `resize`)でやると 1080p では 10ms/frame 掛かり、
  model より重くなります。GPU へ移してあります。
- 出力 frame ごとに `torch.cuda.synchronize()` を呼ぶと、補間を一切しなくても
  58.8 fps で頭打ちになります。CUDA event を writer thread へ渡す形にしてあります。

出力の検算: 719 frame → 1437 frame(2n-1)、48000/1001 fps、尺 29.967秒。
実際の絵は `results/seq_B_talk_x2.png`(瞬きの前後10枚)で確認しました。
補間frameが source frame の間に自然に入っており、線画の崩れはありません。

---

## 12. まだ測っていないこと / やらなかったこと

| 項目 | 状態 |
|---|---|
| 24 -> 60fps(割り切れない倍率) | 未測定。model は時刻を入力に取るので任意時刻を作れます(tau=0/0.5/1 で検算済み)。scheduleを書けば足ります |
| VFR素材 | 未測定。同上。vup の PTS 読み取りをそのまま持ってくる必要があります |
| SR との連結 | 未測定。7章の通り「補間 → SR」の順が有利なはずですが、通した実測はまだです |
| ensemble 版の重み | 未測定。cost が2倍になるので、速度優先の方針から外しました |
| GMFSS / FILM など RIFE 以外 | 未測定。いずれも RIFE より1桁遅い部類です |
| cut 判定の実装 | `a8_e2e.py` の中は `mad > 18` という粗い判定で、A_op で 195回発火します(scdet は37回)。試験集合の側は scdet を使っています。**製品版では scdet 相当を通すべきです** |
| 「動きが大きすぎるので呼ばない」判定 | 5章で境目(32px)は出しましたが、実装には入れていません。flow を測る cost が要るので、box4 など安い量で代用できるかを測る必要があります |
| 座標計算だけ fp32 に残す graph 手術 | 9章の通り build が通らず、実測の差も小さいので見送りました |
| 2コマ打ちを畳んでから補間する | 未検討。B_talk は 5.45 frame に1枚しか絵が無いので、「絵の列」に対して補間して時刻を張り直す方が筋が良い可能性があります |

---

## 13. 目で確かめる物 (`vfi/out/`)

数字だけでは判断できないので、実際に見る物を置いてあります。

| file | 中身 |
|---|---|
| `<素材>_元.mkv` | 切り出した原本(補間なし) |
| `<素材>_x2_<model>_等倍.mp4` | x2 出力。そのまま再生して滑らかさを見る |
| `<素材>_比較_4分の1速_<場面>.mp4` | 左=元(補間なし) / 右=x2。1/4速で並べたもの |
| `<素材>_model比較_4分の1速_<場面>.mp4` | 元 / `v4.6` / `v4.25_lite` / `v4.26_heavy` の2x2 |
| `<素材>_静止比較_<場面>.png` | 元の前後frameと補間frameを原寸で横並び |

1/4速にしてあるのは、47.952fps のままでは人の目で差が判らないためです。
左の「元」は frame を複製して尺を合わせるので、**補間しない場合そのもの**が映ります。

場面は3つ選んであります。

- `動く所`(B_talk): 絵の変化が一番多い6秒。補間が効く典型
- `変位小`(A_op): 隣接変位の中央 30.9px の6秒。境目付近
- `変位大`(A_op): 隣接変位の中央 84.0px の3秒。**model が負ける領域**

`results/look_*_worst.png` は各 model が一番落としている組で、
`results/seq_B_talk_x2.png` は x2 出力の連番(瞬きの前後10枚)です。

---

## 14. 計測基盤の速度

計測そのものが遅かったので直しました。model は GPU で 5.7ms なのに、
その周りの metric が CPU で 218ms 掛かっており、**待ち時間の 97% が metric**
という状態でした。

| | CPU (旧) | GPU (新) | |
|---|---|---|---|
| `psnr` | 80.17 ms | 0.835 ms | 96.0倍 |
| `box4_max` | 3.61 ms | 0.550 ms | 6.6倍 |
| `bad_pixels` | 73.43 ms | 0.620 ms | 118.4倍 |
| `gmsd` | 61.01 ms | 1.445 ms | 42.2倍 |
| **合計** | **218.22 ms** | **3.449 ms** | **63.3倍** |

値が変わっていないことを検算してあります（`box4` と `bad_pixels` は完全一致、
`psnr` は相対 1e-7、`gmsd` は 3e-4）。CPU 版は `vfilib.*_cpu` に残してあります。

効いた所:

| | 前 | 後 |
|---|---|---|
| model 1件の品質計測（B_talk 102組） | 25.0秒 | **2.4秒** |
| 同（A_op 120組） | 29.0秒 | **3.2秒** |
| 比較動画の生成（x4 slowmo + 差分map） | 31秒 | **13秒**（libx264 → hevc_nvenc） |
| `rifelib.unpack` | 0.276 ms | 0.197 ms（出力は完全一致） |

`unpack` は permute してから fp32 化すると 25MB の中間を strided access で
書くことになるので、CHW のまま uint8 まで落として最後に1回だけ転置します。

---

## 15. script

```
vfi/
  vfilib.py        素材の読み込み・記録・metric
  rifelib.py       RIFE v2実装 + fp16変換 + TensorRT engine
  rifev1.py        RIFE v1実装(scale を掛けるため)
  a1_cadence.py    コマ打ち・動き量の実測
  a1b_cuts.py      cut の確定(ffmpeg scdet)
  a2_testset.py    試験集合(絵の列で組む)
  a2b_spanmv.py    試験組が実際に跨ぐ変位
  a3_bench.py      model ごとの速度と品質
  a4_gate.py       呼ばない判定の節約と誤差
  a5_encoder.py    出力側の天井
  a6_visual.py     出力を並べて目で見る
  a7_scale.py      解像度と batch
  a8_e2e.py        端から端まで(実際に file を作る)
  a9_compare.py    比較動画と静止比較を作る
  a10_slowmo.py    倍率を上げた slow motion と差分map
  a11_diffreport.py 補間が何を変えたのかを frame ごとに数値で出す
  a12_capacity.py  model のせいか構造かを分ける
  gpumetric.py     metric の GPU 実装(CPU版と一致を検算済み)
  exp_prec.py      fp16 と fp32
  exp_scale05.py   flow の解像度
  exp_pipe.py      pipe の読み取り速度
  report.py        results.jsonl から表を組む
  make_doc.py      この文書を組み立てる
  results/         results.jsonl(生の記録) と検証用の画像
  onnx/            RIFE の ONNX(vs-mlrt 配布)
  engines/         TensorRT engine の cache
  work/            切り出した素材と memmap
```

`work/*.bgr24.npy` は素材を展開した memmap で 4.5GB ずつあります。
消しても `a1_cadence.py` が作り直します。
"""


if __name__ == "__main__":
    RP.OUT.parent.mkdir(exist_ok=True)
    RP.OUT.write_text(DOC, encoding="utf-8")
    print(f"書きました: {RP.OUT}  ({len(DOC)} 文字)")
