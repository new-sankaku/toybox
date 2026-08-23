# vfi — フレーム補完(VFI)の検証

anime を x2(23.976 → 47.952 fps)で滑らかにするための、model の選定と
高速化の実測です。**まだ検証段階で、`vup` のような完成した tool ではありません。**

計測結果の全文は `../doc/フレーム補完_計測結果.md` にあります。
生の記録は `results/results.jsonl`(1件ずつ追記)です。

## 今わかっていること（要点だけ）

| | |
|---|---|
| 一番速い構成 | `v4.6` + v1実装 + scale=0.5 + fp16 TensorRT … **3.90ms/回 (256 fps)** @1920x1080 |
| 素直な既定 | `v4.6` v2実装 fp16 … 5.32ms (188 fps)。`*_lite` はどれも 10ms 超で**2倍遅い** |
| 品質が一番良い | `v4.25_lite`(会話場面 LPIPS 0.0153)。ただし model 間の差は 24% しかない |
| 一番効いた高速化 | **model ではなく pipe の読み方**。`bufsize` を外して 1080p で 7.1倍 |
| 呼ばずに済む割合 | 本編の会話場面 **5.70倍**(絵が 5.45 frame 保持されるため)。OP は 1.12倍 |
| 補間してはいけない所 | cut と、**跨ぐ変位が 32px を超える所**(model が単純平均に負ける) |
| 出力側 | 1080p hevc_nvenc p4 で 402 fps。天井ではない |
| 実効 | 30秒の素材を 48fps へ: 会話場面 5.5秒 / OP 6.6秒(`v4.6`) |

## 動かす

```
cd vfi
..\vup\venv\Scripts\python.exe a8_e2e.py work\B_talk.mkv --model v4.6
```

主な option:

| option | 既定 | 説明 |
|---|---|---|
| `--model` | `v4.25_lite` | `onnx/rife_v2/` にある名前。`v4.6` が速い |
| `--gate` | `16` | box4 がこれ未満なら model を呼ばず前の frame を写す |
| `--encoder-args` | `-preset p4 -cq 24` | |
| `--no-model` | OFF | 補間せず複製する(出力側の天井を測る) |
| `--limit` | 0 | 先頭N frameだけ |

engine は初回だけ 20〜32秒掛けて作り、`engines/` に置きます。

## 計測をやり直す

順番に依存があります。`results.jsonl` に済んだ物は残るので、
途中で止めても測り直しにはなりません。

```
a1_cadence.py     素材を memmap へ展開し、コマ打ちと動き量を測る
a1b_cuts.py       cut を確定する(先に ffmpeg scdet の score が要る。doc参照)
a2_testset.py     試験集合を作る
a2b_spanmv.py     試験組が実際に跨ぐ変位を測る
a3_bench.py       model ごとの速度と品質
a4_gate.py  a5_encoder.py  a7_scale.py  exp_prec.py  exp_scale05.py  exp_pipe.py
a6_visual.py      出力を並べて目で見る
a8_e2e.py         端から端まで
make_doc.py       doc を組み立てる
```

`a1b_cuts.py` の前に scdet の score が要ります:

```
ffmpeg -v error -i work\A_op.mkv -vf "scdet=threshold=0,metadata=print:file=results/scene_A_op.txt" -an -f null -
```

## model の入手

vs-mlrt が配っている ONNX を使っています(TensorRT 向けに作られています)。

- `https://github.com/AmusementClub/vs-mlrt/releases/tag/external-models`
  の `rife_v2_v4.7z` と `rife_v4.*.7z`
- 古い版(v4.0〜v4.6)の **v1実装**は `models.v16.2.test1.7z`(852MB)の
  `models/rife/` にしかありません。scale を掛けるにはこちらが要ります

`onnx/rife_v2/`(v2実装、pad が graph の中)と `onnx/rife/`(v1実装、pad は自前)の
2系統があります。既定は v2実装です。

## 注意点

- **1080p の pipe 読みで `bufsize` を指定しないでください。** Python の
  `BufferedReader` が内部buffer を経由して 7.1倍遅くなります
  (`vup/vup.py` も同じ書き方をしているので、そちらも直す価値があります)
- TensorRT 11 は `BuilderFlag.FP16` が無く strongly typed のみです。
  fp16 は ONNX 側で作ります(`rifelib.to_fp16`)。
  `onnxconverter_common` は `Cast(to=FLOAT)` と `ConstantOfShape` を
  書き換えないので、後処理で直しています
- engine の実行と入力を組む kernel は**同じ stream に載せてください**。
  別 stream にすると engine が前回の入力を読み、**前の frame が返ります**
- `work/*.bgr24.npy` は 4.5GB ずつあります。消しても作り直せます

## 環境

Windows 11 / RTX 4070 Ti 12GB / Python 3.10 / torch 2.10+cu126 /
TensorRT 11.2.1.2。venv は `vup/venv` を共用しています
(`onnxconverter-common` だけ追加で入れました)。
