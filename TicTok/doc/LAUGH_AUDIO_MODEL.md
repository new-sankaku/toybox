# 笑い声検出のmodel入手と配置

切り出し候補の指標「笑い声(音声)」(`clip_candidate_laugh_audio`)は、録画の音声をAudioSetの
audio tagging modelへ通して笑い系classの確率列を作る。実装は `tictok/media/laugh_audio.py`、
候補APIへの配線は `tictok/server.py` の `_MATERIAL_METRICS`。

**weightsはこのrepositoryに含めない。** 利用者が入手して置き、pathを設定で指す(AI高画質化の
超解像weightsと同じ方式)。自動downloadは持たない。

> 2026-08-02: 再export・配置・実録画での検証まで完了している。何をどう確かめたかは
> 「再export」「閾値0.35の根拠」の節にある。実行版のexportは `scripts/export_laugh_onnx.py`。

## engineが受け付けるONNXの契約

`laugh_audio._describe` が起動時に検査する。ここを満たさないONNXは例外で弾かれる
(推測で前処理を補うと、学習時と少しでも違えば確率が静かに壊れるため)。

| 項目 | 要求 |
| --- | --- |
| 入力 | **1つだけ**。shapeは2次元 `(batch, samples)` |
| 入力の中身 | 16kHz mono、float32、full scaleが±1.0の**生波形** |
| 出力 | `(batch, classes)`(`(batch, 1, classes)` も可。中央の軸だけ落とす) |
| 活性化 | `TICTOK_LAUGH_AUDIO_ACTIVATION` で明示。logits出力なら `sigmoid`、確率出力なら `none` |
| 実行 | `TICTOK_LAUGH_AUDIO_DEVICE` で選ぶ(既定 `cpu`)。`cuda` は別processで走る |

窓長を固定してexportした場合、`fixed_samples` と
`TICTOK_LAUGH_AUDIO_WINDOW_SECONDS × 16000` が一致しないと例外になる(既定は2.0秒 = 32000)。

### deviceの選び方

| device | 実測(RTX 4070 Ti / ced-tiny 2秒窓) | 備考 |
| --- | --- | --- |
| `cpu`(既定) | 推論 393 window/s。3.5時間の録画で解析 90秒 | 追加installは不要 |
| `cuda` | 推論 **12,733 window/s**(32倍)。同じ録画で **28秒** | `onnxruntime-gpu` が要る |

`cuda` でも全体は3.2倍にしかならない。音声decode(実測 実時間の833倍)が律速に変わるためで、
推論そのものは解析時間の数%まで落ちる。全548時間を一括で回すなら約74分(cpuなら約4時間)。

**`cuda` は必ず別process(`tictok/media/laugh_worker.py`)で走る。** serverのprocessへ
onnxruntime-gpuのCUDA EPを載せてはいけない。このvenvには `cudnn64_9.dll` が3つ在り
(ctranslate2 同梱 9.10.2 / torch 同梱 9.1.0 / nvidia wheel)、WindowsはDLLを名前1つにつき
1個しか載せないため、版の食い違った組で呼ばれたcuDNNが `0xc0000409` でprocessごと即死する
(文字起こしで実測3回、例外にならずlogも残らない)。詳細は `doc/STT_PROCESS_ISOLATION.md`。

**onnxruntimeは要求したproviderを作れないと黙ってCPUへ落ちる。** 実測で、CUDAを指定した
sessionが `CPUExecutionProvider` だけを名乗り、そのまま「GPUで走っている」つもりの計測値が
出た(CUDA EPのDLL依存が1つ欠けていた)。落ちたことは確率を見ても分からないので、
`laugh_audio._get_model` が `get_providers()` を突き合わせて例外にする。

CUDA runtimeのDLLは `laugh_worker.register_cuda_dll_dirs()` が登録する。`nvidia-*-cu12`
wheel群に加えて**torchの同梱lib**も足しているのは、CUDA EPが依存する `cufft64_11.dll` が
nvidia wheel群に無く(`nvidia-cufft-cu12` は未install)、同じDLLがtorch側に既に在るため。
`add_dll_directory` だけでは足りず**PATHにも積む**(onnxruntimeはPATH検索で解決する)。

## 重要: 上流の公開ONNXはそのままでは使えない(確認済み)

CED系の公開ONNXはいずれも**mel入力**で、上記の契約(波形入力)を満たさない。

- `RicherMans/CED` の `export_onnx.py` は入力 `feats` = `(1, n_mels, max_frames)`、出力 `prob`。
  波形は受けない。([export_onnx.py](https://raw.githubusercontent.com/RicherMans/CED/main/export_onnx.py))
- `mispeech/ced-tiny` の `model.onnx` も同様で、`CedForAudioClassification.forward(input_values, ...)`
  はmelを受け取り、mel計算はmodelの外(`CedFeatureExtractor`)で行われる。
  ([modeling_ced.py](https://huggingface.co/mispeech/ced-tiny/raw/main/modeling_ced.py))

したがって手順は「downloadして指す」ではなく、**mel front-endをgraphへ含めて再exportする**の
1手間が入る。melの計算をtictok側に持たせない判断は `laugh_audio._describe` のdocstringのとおり
(mel filter本数・hop・窓関数をこちらが推測することになり、ずれても出力を見て気付けない)。

## 入手元

### 1. weights (どれか1つ)

| 入手元 | 中身 | license | 確認状況 |
| --- | --- | --- | --- |
| [mispeech/ced-tiny](https://huggingface.co/mispeech/ced-tiny) | PyTorch(`model.safetensors`)+ 前処理・modelのpython code、`model.onnx`(mel入力) | **Apache-2.0**(model card記載) | 確認済み。再exportの土台として最も扱いやすい |
| [RicherMans/CED](https://github.com/RicherMans/CED) | 学習・export一式(`audiotransformer_tiny_mAP_4814.pt` をZenodoから取得) | **GPL-3.0**(repository) | 確認済み。codeを取り込む場合はGPLの伝播に注意 |
| [k2-fsa/sherpa-onnx-ced-tiny-audio-tagging-2024-04-19](https://huggingface.co/k2-fsa/sherpa-onnx-ced-tiny-audio-tagging-2024-04-19) | `model.onnx` 22.3MB / `model.int8.onnx` 6.13MB / `class_labels_indices.csv` 14.7kB | **未確認**(pageにlicense表記なし) | fileの存在は確認済み。**入力形式は未検証**(sherpa-onnx側が特徴量をC++で作る構成なのでmel入力と推定) |

CED-tinyは約6M〜10M parameter・16kHz・64次元mel・527 class(AudioSet)。CPUで実時間の数十倍で
流せる規模なので、この用途(後から一括で回す解析)に足りる。

### 2. label file (必須)

出力indexとclass名の対応表。**weightsと対で持つこと**(出力順はweightsごとに違う)。

- AudioSet公式: `http://storage.googleapis.com/us_audioset/youtube_corpus/v1/csv/class_labels_indices.csv`
- license: dataset CSVは **CC BY 4.0**、ontologyは CC BY-SA 4.0
  ([AudioSet download](https://research.google.com/audioset/download.html))
- 確認済み(2026-07-26に実際に取得): header は `index,mid,display_name`、527 class。
  笑い系は index 16〜21 で、`display_name` は既定設定の綴りと完全一致する:

  | index | display_name |
  | --- | --- |
  | 16 | `Laughter` |
  | 17 | `Baby laughter` |
  | 18 | `Giggle` |
  | 19 | `Snicker` |
  | 20 | `Belly laugh` |
  | 21 | `Chuckle, chortle` |

`laugh_audio._load_labels` はこのCSV(index / display_name列)と、JSONのlist(index順)・
dict(index→名前)を読む。indexが連番でないfileは例外にする(対応表がずれると別の音の確率を
「笑い」として読むことになり、出力を見ても気付けない)。

### 3. onnxruntime

```
pip install onnxruntime          # CPUで走らせる場合
pip install onnxruntime-gpu      # TICTOK_LAUGH_AUDIO_DEVICE=cuda の場合
```

**両方を入れてはいけない。** 同じ `onnxruntime` packageを共有するので、後から入れた方が
上書きし、dist-infoだけが2つ残る。片方をuninstallすると共有されている実体ごと消えるため、
入れ替えるときは `pip uninstall -y onnxruntime onnxruntime-gpu` してから入れ直すこと。
`onnxruntime-gpu` はCPU providerも持つ上位互換である。

## 再export(mel front-endを含める) — 実施済み

**`scripts/export_laugh_onnx.py` が実行版である。** 手順の要点はscriptのmodule docstringに
書いてあり、以下は実行して分かった事実の記録。

```
pip install transformers torchaudio onnx     # runtimeには不要。exportのときだけ
python scripts/export_laugh_onnx.py --out models/laugh --window-seconds 2.0
```

実行結果(2026-08-02、`mispeech/ced-tiny`):

| 確認項目 | 結果 |
| --- | --- |
| model cardの経路との最大差 | **9.24e-07**(許容 1e-4) |
| batch sizeを変えたときの差 | **3.87e-07** |
| 出力 | 527 class、mel 201 frame(窓2.0秒 = 32000 sample、上限1012 frame) |

踏んだ落とし穴が4つある。

1. **`torch.stft` はopset 17でexportできない。** `STFT does not currently support complex
   types` で落ちる(torchaudioの `MelSpectrogram` は内部で `return_complex=True` を使う)。
   窓掛けDFTを**固定重みのconv1d**として書き下して回避した。近似ではなく同じ式で、
   等しいことはparity check(上表)が確かめる。窓とmel filterbankは自作せず
   `MelSpectrogram` のbuffer(`spectrogram.window` / `mel_scale.fb`)をそのまま使う。
2. **出力は既に確率である。** `CedForAudioClassification.forward_head` は `pooling="mean"`
   の枝で `.sigmoid()` を掛けて返す。したがって **`TICTOK_LAUGH_AUDIO_ACTIVATION=none`**。
   二重掛けは値が [0.5, 0.73] へ潰れるだけで、結果を見ても気付けない。
3. **labelはrepositoryの `config.json` から作ってはいけない。** そこのid2labelは表記が短く
   (index 21 が `Chuckle`)、`CedConfig.__init__` が読み込み時にAudioSet公式の
   `class_labels_indices.csv` で**上書きする**ため、実際に効くのは公式表記
   (`Chuckle, chortle`)である。並びは同じでも綴りが食い違うと
   `TICTOK_LAUGH_AUDIO_CLASSES` の名前解決が落ちる。scriptは読み込んだmodelの
   `config.id2label` をそのまま `labels.json` へ書く。
4. **窓長は固定してexportする。** CEDは `time_pos_embed[:, :, :, :t]` で位置埋め込みを入力長へ
   切り、mel frameが `target_length`(1012 frame ≒ 10.12秒)を超えると入力を分割する枝を持つ。
   可変長のままtraceするとこれらの分岐がtrace時の値で焼き付く。固定しておけばengineが
   `fixed_samples` と窓長設定を突き合わせ、食い違いを実行前に例外にできる。

窓長2.0秒と10.0秒の両方をexportして実録画で比べた。10秒窓はAUCがわずかに高いが
(0.658 vs 0.612、ただし正解6件)、**笑いが10秒のうちの1〜2秒だと発話に埋もれて確率が下がる**
(同じ笑い声で 2秒窓 0.567 / 10秒窓 0.484、10秒窓では `Speech` が0.875で上に来る)。
解析速度も3.6倍違うため2.0秒を採用した。

## 配置と設定

置き場所は任意(pathで指す)。`models/` はgitignore済みなので、超解像weightsと同じくここが素直。
相対pathはproject root基準で解決される(`laugh_audio._resolve`)。

```
models/laugh/ced_tiny_waveform_2s.onnx    22.2MB
models/laugh/labels.json                  527 class(exportが書き出す)
models/laugh/EXPORT.md                    exportの実測値と設定の写し
```

`.env`:

```
TICTOK_LAUGH_AUDIO_ENABLED=1
TICTOK_LAUGH_AUDIO_MODEL_PATH=models/laugh/ced_tiny_waveform_2s.onnx
TICTOK_LAUGH_AUDIO_LABELS_PATH=models/laugh/labels.json
TICTOK_LAUGH_AUDIO_ACTIVATION=none
TICTOK_LAUGH_AUDIO_WINDOW_SECONDS=2
TICTOK_LAUGH_AUDIO_DEVICE=cuda
TICTOK_LAUGH_AUDIO_BATCH=128
```

`CLASSES` は既定のままでよい(公式表記と一致する)。`BATCH` はGPUで128が頭打ち、CPUなら32〜64。

| env | 既定 | 意味 |
| --- | --- | --- |
| `TICTOK_LAUGH_AUDIO_ENABLED` | 0 | engineの有効化。0のままなら候補側をONにしても失敗する |
| `TICTOK_LAUGH_AUDIO_MODEL_PATH` | (空) | ONNX file |
| `TICTOK_LAUGH_AUDIO_LABELS_PATH` | (空) | label file |
| `TICTOK_LAUGH_AUDIO_CLASSES` | `Laughter\|Giggle\|Snicker\|Belly laugh\|Chuckle, chortle` | 笑いとみなすclass。区切りは `\|`(class名自体がカンマを含むため) |
| `TICTOK_LAUGH_AUDIO_WINDOW_SECONDS` | 2.0 | 1回の推論が見る長さ |
| `TICTOK_LAUGH_AUDIO_HOP_SECONDS` | 1.0 | 確率列の刻み(=時間分解能) |
| `TICTOK_LAUGH_AUDIO_THRESHOLD` | 0.35 | 笑い有りとみなす確率の下限。sidecarは閾値**前**の生確率なので変更に再解析は不要 |
| `TICTOK_LAUGH_AUDIO_BATCH` | 32 | 1回の推論へ渡す窓数 |
| `TICTOK_LAUGH_AUDIO_THREADS` | 0 | onnxruntimeのintra-op thread数(0=既定)。録画中に回すなら絞る |
| `TICTOK_LAUGH_AUDIO_ACTIVATION` | sigmoid | `sigmoid` か `none` |
| `TICTOK_LAUGH_AUDIO_DEVICE` | cpu | `cpu` か `cuda`。cudaは別processで走る(上の「deviceの選び方」) |

`Baby laughter`(index 17)は既定に入れていない。乳児の声は配信の笑いとは別の場面である。

候補側の設定(設定画面「切り出し」categoryから変更可):

| 設定 | 既定 | 意味 |
| --- | --- | --- |
| `clip_candidate_laugh_audio` | 0 | 笑い声を候補の判定に使う |
| `clip_candidate_laugh_audio_weight` | 1.0 | z-scoreに掛ける倍率 |
| `clip_candidate_laugh_audio_min_seconds` | 3.0 | 窓内の笑い秒数の下限(これ未満の窓は候補にしない) |
| `clip_candidate_laugh_audio_solo_only` | 0 | コラボ中(顔が2つ以上)の笑い声を数えない |

下限は必須である。笑い声の系列もほとんどの窓が0秒で標準偏差が極小になるため、下限が無いと
「ほとんど笑わない配信の1刻み」が大きなz-scoreを叩いて候補を占領する(`core/spike.py`)。

### コラボ中を外す(`clip_candidate_laugh_audio_solo_only`)

コラボ中の笑いは共演者のものかもしれず、どの顔が配信者かを画面から決める手段は無い
(`smile.py` の module docstringと同じ制約)。判定は**映像の顔の数**で行い、顔が2つ以上
映っている区間の刻みを数えない(`smile.multi_face_spans` → `laugh_audio.laugh_seconds(
exclude_spans=...)`)。顔検出modelの配置が要る(`doc/SMILE_MODEL.md`)。未配置のままONに
すると候補APIは失敗する — 除外できていない候補を「コラボを外した候補」として渡さない。

**ここではDBの `collab_windows` は使わない。** この設定が数えないのは「配信者以外の顔が
映っている間」で、あれが記録しているのはLinkMic channelの有無であって人数ではない。実測で
`guests_max` が811窓中805窓(99.3%)で0のままだった(名簿が届かない窓では0で確定する)。窓の
合計が配信時間を超える配信者も居る(viewer_11 で115%)。

一覧側(`TICTOK_LAUGH_INDEX_EXCLUDE_COOP`)がDBの窓を使うのは、あちらが**音**を外している
ためである。外したいものが違う(こちらは画面の顔、あちらは音声に乗る相手の声)ので、根拠も
違う。詳細は「共演中(コラボ・Battle)は一覧に出さない」を参照。

顔が**0個**の標本は除外しない。「顔が見えない」は「複数人いる」ではなく、ゲーム画面や
カメラ外しは単独配信でも普通に起きる。ここで0個を多人数側へ入れるとその素材がまるごと消える。

実測(2録画):

| 録画 | 多人数の割合 | 笑い声(閾値0.35) | 除外後 | 多人数への集中度 |
| --- | --- | --- | --- | --- |
| viewer_10 00444 | 91% | 88秒 | **0秒** | — |
| streamer_a 00029 | **25%** | 45秒 | 6秒 | **3.5倍** |

**笑いはコラボ中に集中する。** streamer_aは尺の25%しかコラボでないのに笑い声の87%がそこに
在る(閾値0.5では100%)。したがってこの設定をONにすると候補は大きく減り、配信者によっては
ゼロになる。既定をOFFにしているのはそのため。

## 笑い声の一覧から引く

検出した笑いは `search_hits`(`source=laugh`)へ入る。引く口は配信者動画タブの探し方
**「笑い声」**で、選ぶと語で絞らずに窓を全て並べる(`GET /api/search/laughs`)。行は種別欄に
「笑い声」と出て、本文は `3秒（強さ 0.72）` — 開かずに選べるよう、長さと最大確率を書いてある。

**語の検索(`/api/search`)からは引けない。** 以前は検索対象のcheckboxとして音声・Commentと
並んでいたが、この行は音そのものが根拠で**当たる語を持たない**。`ガンダム` で探しても笑いは
1件も混ざらず、実際には本文へ書いた `笑い声` の3文字がFTSに乗っているだけで、「笑い声」と
打った時にだけ一覧へ化ける隠しmodeだった。語の検索へは混ぜず、語を受け取らない一覧として
独立させてある。

**文字起こしに「笑」と書かれていなくても拾える。** 文字起こしは笑い声を文字にしないため(実測:
文字起こし425,305 segment中「笑」を含むのは648件で、その中身も「笑顔」「笑ってる」という言及)、
語の検索では笑いの場面に辿り着けない。これがその穴を埋める経路である。

並べ替えは**配信が新しい順 / 強い順 / 長い順**。語の一致度が無い代わりに、窓の最大確率
(`search_hits.score`)と長さが「どれを開くか」の手掛かりになる。強さを本文の文字列
(`強さ 0.72`)から読み戻さず列で持つのは、表示の書式を数値の出所にしないためで、score列より
前に入れた行はNULL = 強い順の末尾へ落ちる(入れ直せば値が付く)。

行にするのは確率の刻みではなく**窓**である(`indexer.laugh_windows`)。刻みのまま行にすると
1回の笑いが数行に割れて一覧が同じ場面で埋まるので、隣接する刻みをつなぎ、短すぎる窓は
捨てる。

| env | 既定 | 意味 |
| --- | --- | --- |
| `TICTOK_LAUGH_INDEX_MERGE_GAP_SECONDS` | 2.0 | この隙間までは同じ笑いとして1行に畳む(息継ぎで確率が落ちる) |
| `TICTOK_LAUGH_INDEX_MIN_SECONDS` | 2.0 | これより短い窓は行にしない(1刻みだけ超える点は録画1本で数百個出る) |
| `TICTOK_LAUGH_INDEX_EXCLUDE_COOP` | `coop` | 共演中を一覧から外す範囲。`coop`=コラボとBattle / `collab`=コラボのみ / `none`=外さない |

### 共演中(コラボ・Battle)は一覧に出さない

一覧は「この配信者が笑った場面」として読まれる。ところが共演中の音声には相手の声がそのまま
乗っており、**どの笑い声が配信者のものかを音から決める手段は無い**。根拠が別人だったという
壊れ方が最も高くつくので、共演中の刻みは窓を作る前に落とす(`indexer.laugh_windows(
exclude_spans=...)`)。

**窓の出所はDB(`collab_windows` v2 と `battles`)である。** 切り出し候補側の同じ除外
(`clip_candidate_laugh_audio_solo_only`)が映像の顔の数を使うのと違うのは、こちらが**音**の
話だからである: カメラを外している間もゲーム画面を映している間も相手の声は乗り続けるので、
「画面に顔が2つ映っている区間」では足りない。逆にDBの窓は人数を名乗れないが、ここでは人数を
必要としない ―― 繋がっているかどうかだけで足りる。

窓は壁時計なので、commentと同じmapperで動画時間へ写してから当てる(素の
`time - started_at` は最大20秒以上ずれる)。除外区間は谷ではなく**切れ目**として扱う ――
`MERGE_GAP` でつなぐと共演を跨いだ1つの窓になり、外した秒が窓の長さへ戻ってくる。

外せない場合は**外せないことを名乗る**:

- コラボ窓の判定rule(v2)より前のsessionは、コラボが無かったのか記録が無いのかを区別
  できない。この録画は1秒も外れないので、一覧の行は「コラボ窓の記録が無い時期」とhoverで
  名乗る(`laugh_collab_observed=false`)。
- Battleの時刻はTikTokのserver時計、コラボ窓とsessionはこちらの時計である。同じ軸として
  扱うのは共演構成(`_coop_summary`)と同じで、NTPの効いた環境では差は秒単位に収まる。

**条件を変えたら張り直しが要る。** indexを張ったときのrule版と除外設定は録画へ残る
(`recordings.laugh_index_json`)。一括処理の済み判定はこの記録が現行の条件と一致することを
見るので、設定を変えた録画・この仕組みより前に張った録画は自動で対象へ戻る(sidecarに
当たるので数十msで終わり、indexだけが入れ替わる)。

閾値は `TICTOK_LAUGH_AUDIO_THRESHOLD` を候補側と共有する。**一覧に出す窓を増やしたいなら閾値を
下げて「笑い声分析」を「作り直す」で投入し直す** — 確率列のsidecarは閾値の前の生値なので、
解析はcacheに当たり、indexだけが数十msで入れ替わる。

実測(閾値0.35・最短2秒): 123分の録画で25窓、318分で8窓、330分で16窓。

## 録画一覧を笑い声の多い順で並べる

配信者動画タブで検索語を入れていないときの録画一覧(`GET /api/recordings/browse`)は、
並替に「**笑い声が多い順**」を持つ。値は録画ごとのindex行の合計秒
(`storage.laugh_totals_by_recording`)で、共演中を外して張り直せば合計もそのぶん減る。

**未解析は0秒ではない。** まだ数えていない録画は合計をNULLで返し、画面は「—」と出して
並びの末尾へ落とす(要約に「未解析 N本は末尾」と本数まで出す)。0秒として混ぜると、末尾が
「笑わなかった配信」と「まだ数えていない配信」の混ざった塊になり、どちらなのか読めない。
解析して1件も無かった録画は0秒と名乗る(こちらは分かっている事実)。

行のhoverは、その秒が何を外して数えた値かを名乗る ―― 共演中の何秒を外したのか、外す前に
張ったindexなのか、コラボ窓の記録が無い時期の配信なのか。

## 一括生成

配信者動画タブの一括処理に種別「**笑い声分析**」がある。1録画=1 job(`kind=laugh`)で、
解析 → 一覧のindex(`search_hits`)への登録までを1本で行う。

**済み判定はindexを張った条件で見る**(sidecarの有無ではない)。確率列だけ在ってindexに無い
録画は「解析は済んだが一覧に出ない」状態で、sidecarを根拠に済みとすると誰も拾い直せなく
なる。行の有無だけでも足りない ―― 共演中を外す条件が違うindexは同じ行が別の意味を持つので、
`recordings.laugh_index_json` が現行の条件(rule版と `TICTOK_LAUGH_INDEX_EXCLUDE_COOP`)と
一致する録画だけを済みとする。解析済みの録画が対象に入った場合、jobはcacheに当たって
数十msで終わりindexだけが埋まる。

engineが無効・model未配置のときは**投入の時点で503**にする。全件をqueueへ積んでから1本ずつ
同じ理由で失敗させると、台帳が同じerrorで埋まるだけになる。

同時実行は1本に固定する。cudaならGPU枠(`gpu_slot`)、cpuなら`_infer_lock`で、どちらにしても
1本ずつしか進まないため、見積りのworker数もそれに合わせてある。

## 動作確認と失敗の見え方

`clip_candidate_laugh_audio=1` にして `GET /api/recordings/{id}/clip-candidates` を叩く
(候補を並べる節は再生画面から外したので、確認はAPIで行う)。

- 成功: 候補に `laugh_audio`(秒数)が載る。根拠が笑い声だった候補は `metric` が `laugh_audio`。
- **model未配置・engine無効・解析失敗: 候補APIは503で理由を返す。** 笑い0秒の候補一覧を
  黙って返すことはしない(「笑いが検出されなかった」と「そもそも検出していない」が区別
  できなくなるため)。
- 確率列が録画の一部しか覆えない場合は、その録画では笑い声指標を**外す**(0で埋めない)。
  画面では「—」になり、logへ `clip.material_metric_skipped` が残る。

初回は録画の音声を最後まで読む。結果は録画ごとのsidecar
(`<録画>.laugh.json`)へ残り、以後は再利用する。cacheの鍵は素材の指紋・窓長・hop・class・
activation・**modelの指紋**で、閾値は鍵に含まれない(閾値を変えても再解析は要らない)。

## 閾値0.35の根拠(実測)

正解は「文字起こしが笑い声そのものを書き取った箇所」(`はは`/`ハハ`/`ふふ` を含むsegment。配信者の
音声由来)、対照は無作為の時刻。8録画・約28時間、正解56件・対照9000点。

**AUC = 0.734**(正解の中央値 0.129 / 対照 0.003)

| 閾値 | 対照の発火率 | 正解の捕捉率 | enrichment |
| --- | --- | --- | --- |
| 0.20 | 8.36% | 39.3% | 4.70x |
| 0.30 | 4.79% | 30.4% | 6.34x |
| **0.35(既定)** | **3.54%** | **25.0%** | **7.05x** |
| 0.50 | 1.23% | 10.7% | 8.69x |

切り出し候補は精度優先なので0.35〜0.5が妥当で、既定の0.35は変更していない。生確率を
保存してあるので、後から掃引し直すのに再解析は要らない。

**耳での確認も行った。** 検出上位10箇所を切り出して聴いたところ、いずれも実際に笑っていた。
派生指標だけで良否を決めない(`doc/BUG_CHECKLIST.md` の方針)。

pipelineが健全であることの別証拠: 通常の発話区間では笑いclassが **0.000**・`Speech` が0.88、
文字起こしが「ぽはははははは」と書いた箇所では `Snicker` 0.567・`Laughter` 0.460。

## 未確認の事項

- sherpa-onnx repositoryのlicense表記(pageに無い)と、その `model.onnx` の実際の入力名・shape。
  (`mispeech/ced-tiny` から再exportしたので、この経路は使っていない)
- 配信者ごとの最適な閾値。上の実測は8録画・3配信者ぶんで、素材(マイク・BGM・ゲーム音)の
  違いで最適値が動く可能性は残る。
- 取りこぼし側の大きさ。閾値0.35での捕捉率25%は「文字起こしが書き取った笑い」に対する値で、
  文字起こしが落とした笑い(大半)まで含めた真の再現率は測れていない。
