# 笑顔検出のmodel入手手順

`tictok/media/smile.py`(録画の映像から笑顔の強さを時系列で出すengine)が使うweightsの
入手・配置手順。**weightsは同梱しない**。利用者が置いたfileをpathで指す方式で、置かれて
いなければ機能は明示的に失敗する(0や中立値を返すfallbackは持たない)。

自動downloadのscriptは**作らない**。取得元・licenseの確認を利用者の目の前で1度だけ行う
方が、CIやserver起動時に外部URLへ出る仕組みを抱えるより安全である。

---

## 1. 必要なmodelは2つ

| 段 | 役割 | 設定 |
|---|---|---|
| 顔検出 | frameのどこに顔があるか | `TICTOK_SMILE_FACE_MODEL_PATH` |
| 表情分類 | 切り出した顔が笑っているか | `TICTOK_SMILE_MODEL_PATH` |

2段に分けているのは、「配信者が笑っているか」を1つのmodelで答えられるmodelが無いため
である。顔の位置が分からないと表情分類は配信画面全体を1枚の顔として見てしまう。

### engine側の契約(これを満たさないexportは受けない)

**顔検出**

- 入力: `(batch, 3, height, width)`、**height/widthは固定**(可変寸のexportは受けない)
- 出力: **2本**。最終次元が2のscoreと、最終次元が4のbox
- boxは**正規化座標** `(x1, y1, x2, y2)`(0.0〜1.0)。pixel座標を出すexportはエラーにする
- 閾値・NMSはengine側で掛ける

stride別に `cls_8/obj_8/bbox_8/kps_8...` を出すexport(YuNet・SCRFD・RetinaFace系)は
**受けない**。anchor(prior)の作り方とvarianceをこちら側で推測することになり、学習時と
少しでも違えば枠が静かにずれる。ずれた枠から切り出した顔の表情は、出力を見ても誤りに
気付けない。

**表情分類**

- 入力: `(batch, 1|3, height, width)`、height/widthは固定
- 出力: class数ぶんのscore1本。class名の順は `TICTOK_SMILE_LABELS` で与える

入出力の**tensor名はgraphから読む**ので、名前は何でもよい。

---

## 2. 顔検出: Ultra-Light-Fast-Generic-Face-Detector-1MB

- 取得元: <https://github.com/Linzaer/Ultra-Light-Fast-Generic-Face-Detector-1MB>
- file: `models/onnx/version-RFB-320.onnx`(repositoryをcloneするか、GitHubの
  該当fileから "Download raw file")
- license: **MIT**(repository全体)
- 大きさ・計算量(公表値): 1.11MB / 320x240の入力で90〜109 MFlops

`_without_postprocessing` の付いたfileは**使わない**(box decodeがgraphの外にあり、上の
契約を満たさない)。`version-slim-320.onnx` も同じ契約なので使えるが、精度はRFB版が上。

### 配置と設定

```
models/smile/version-RFB-320.onnx     ← 任意の場所。相対pathはproject root基準
models/smile/LICENSE-ultralight.txt   ← MITは著作権表示の保持が条件なので一緒に置く
```

```ini
TICTOK_SMILE_FACE_MODEL_PATH=models/smile/version-RFB-320.onnx
# 以下は既定値。このexportに合わせてあるので、このmodelなら書かなくてよい。
TICTOK_SMILE_FACE_MEAN=127.0
TICTOK_SMILE_FACE_SCALE=128.0
TICTOK_SMILE_FACE_SCORE_ACTIVATION=none
TICTOK_SMILE_FACE_SCORE_INDEX=1
TICTOK_SMILE_FACE_THRESHOLD=0.7
TICTOK_SMILE_FACE_NMS_IOU=0.3
```

前処理 `(pixel - 127) / 128`・RGB・NCHW と、後処理(scoreの閾値0.7 → hard NMS IoU 0.3 →
正規化boxを実寸へ)は、repositoryの `run_video_face_detect_onnx.py` に書かれているものと
同じである。

---

## 3. 表情分類: FER+ (emotion-ferplus-8)

- 取得元(いずれか同じfile):
  - <https://github.com/onnx/models/blob/main/validated/vision/body_analysis/emotion_ferplus/model/emotion-ferplus-8.onnx>
  - <https://huggingface.co/onnxmodelzoo/emotion-ferplus-8>(mirror、`emotion-ferplus-8.onnx` / 35MB)
- license: onnx/models側の該当READMEは **MIT**、Hugging Face mirrorのmodel cardは
  **Apache-2.0** と表記している(**両者で表記が食い違っている** — 商用配布など判断が要る
  用途では原typeのFER+ を辿って確認すること)
- 入力: `(N, 1, 64, 64)`(grayscale 64x64)
- 出力: `(1, 8)` のscore。**softmaxを掛けて確率にする**
- class順: `neutral, happiness, surprise, sadness, anger, disgust, fear, contempt`

### 配置と設定

```ini
TICTOK_SMILE_MODEL_PATH=models/smile/emotion-ferplus-8.onnx
# 以下は既定値。このexportに合わせてあるので、このmodelなら書かなくてよい。
TICTOK_SMILE_LABELS=neutral|happiness|surprise|sadness|anger|disgust|fear|contempt
TICTOK_SMILE_POSITIVE_CLASSES=happiness
TICTOK_SMILE_ACTIVATION=softmax
TICTOK_SMILE_FOLD=sum
TICTOK_SMILE_MEAN=0.0
TICTOK_SMILE_SCALE=1.0
```

class名の区切りが `|` なのは、class名がカンマを含み得るため(`Chuckle, chortle` のような
AudioSetのclass名で実際に壊れた)。

`TICTOK_SMILE_POSITIVE_CLASSES` に `surprise` を足すと驚き顔も拾う。既定に入れていない
のは、驚きが喜びとは限らないため。複数指定したときの畳み方は `TICTOK_SMILE_FOLD` で、
softmax(排他多class)なら `sum`(「どれかである確率」)、sigmoid(多label)のexportなら
`max` が正しい。

---

## 4. 有効化

```ini
TICTOK_SMILE_ENABLED=1
TICTOK_SMILE_SAMPLE_SECONDS=2.0    # frameを1枚見る間隔。これが時間分解能になる
TICTOK_SMILE_WORK_WIDTH=480        # 解析に使うframeの幅(源より大きくは引き伸ばさない)
TICTOK_SMILE_THRESHOLD=0.5         # 笑顔ありとみなす確率。後から変えても再解析は不要
TICTOK_SMILE_THREADS=0             # onnxruntimeのintra-op thread数(0=既定に任せる)
```

`pip install onnxruntime` が必要(lazy importなので未installでも他の機能は動く)。推論は
**CPU固定**である。GPU 12GBはfaster-whisper(転写)と超解像が奪い合っており、ここが
`gpu_slot` を取るとその間だけ焼き込みが待たされる。どちらのmodelもtiny級なのでCPUで足りる。

閾値(`TICTOK_SMILE_THRESHOLD`)を変えても再解析は要らない。sidecarには閾値を掛ける前の
生確率を保存してあり、閾値の適用は問い合わせ時にだけ行う。逆に、**顔検出側**の閾値・NMS・
最小寸・class名・活性化・sampling間隔・解析寸を変えると確率列そのものが変わるので、
sidecarは自動で作り直される。

---

## 5. この指標が名乗れること・名乗れないこと

**「配信者が笑ったか」は答えていない。** 答えているのは「その時刻のframeに顔がちょうど
1つ映っていて、その顔が笑顔と判定された」である。実映像で確認済みの理由が2つある:

1. battle・collab中は画面が分割され、配信者以外の顔が同時に映る
2. どの顔が配信者かを画面から決める手段が現状無い(layoutは1v1と多人数で変わり、顔の
   大小でも決まらず、配信者の顔写真も持っていない)

engineは **顔が2つ以上見えた標本を捨てる**(`scores` に `null`、`faces` に実際の検出数)。
最大値や平均を採ると、相手や共演者の笑顔を配信者の笑顔として名乗ることになる。領域を
固定して配信者の枠だけを見る案は、layoutを座標で決め打ちすることになり(hard-code)、
layoutが変わった録画で静かに別人を見続ける。

**顔が1つでも配信者だとは限らない。** battle中に配信者のcameraが暗く相手だけが検出される
状況は起こり得る。この身元の不確かさは検出だけでは解けないので、battle・collabの窓は
DB側(`collab_windows` / battle判定)の事実で外す。engineに `without_spans(profile, spans)`
があり、sidecarを作り直さずに窓内の標本を判定不能へ落とせる。

顔が0個の標本も `null` にする(「顔が映っていない」は「笑っていない」ではない)。

集計側の線引き:

- `smile_seconds(profile, start, end)` は**観測できた**笑顔の秒数。判定不能な標本は
  数えないので、判定不能が続く区間は実際より小さく出る。標本の割合から区間全体へ
  引き伸ばすと観測していない時間の笑顔を作り出すので、過小に出る側へ倒している。
- 区間内が全て判定不能でも **0.0** を返す(解析はしているため)。ここを `None` にすると
  呼び出し側の指標登録は最初の `None` で指標ごと外すので、顔が写らない60秒が1つある
  だけで録画全体の笑顔指標が消える。
- 解析していない区間(profileの外)だけが `None`。
- どれだけ観測できたかは `smile_coverage(profile, start, end)` で別に取れる。**0秒が
  「笑っていなかった」なのか「顔が見えなかった」なのかは、この値だけが区別できる。**

---

## 5.5 顔の数は笑い声の側でも使う

`smile.multi_face_spans(profile, min_faces=2)` は顔が2つ以上映っていた区間を返す。
笑い声検出(`clip_candidate_laugh_audio_solo_only`)がコラボ中を候補から外すのにこれを使う
ため、**顔検出modelを置くと笑顔指標を使わなくてもその設定が使えるようになる**。

DBの `collab_windows` を使わない理由は `doc/LAUGH_AUDIO_MODEL.md` にある(あちらが記録して
いるのはLinkMic channelの有無で、人数ではない — 実測で `guests_max` が811窓中805窓で0)。

顔が0個の標本は多人数側に入れない。「顔が見えない」は「複数人いる」ではなく、ゲーム画面や
カメラ外しは単独配信でも普通に起きる。

実測(2026-08-02、2録画):

| 録画 | 顔0個 | 顔1個(単独) | 顔2個以上 | 解析時間 |
|---|---|---|---|---|
| pistachio_ijichi 00444(122.8分) | 0.7% | 8.3% | **91.0%** | 105秒(実時間の70倍) |
| pomiiiip 00029(317.6分) | 6.4% | **68.8%** | 24.8% | 538秒(実時間の35倍) |

---

## 6. 所要時間

3時間(10,800秒)の録画・sampling間隔2秒(=5,400標本)・解析寸480x852での見込み:

| 内訳 | 値 | 根拠 |
|---|---|---|
| decode + 前処理(letterbox・切り出し・NMS) | **約2.0分** | 実測。720x1280/25fpsの実録画600秒に対し6.77秒(実時間の88.7倍速)。ONNX推論のみfake sessionで置換 |
| ONNX推論(顔検出 + 表情分類) | 約1〜4分(**見積り**) | 顔検出は90〜109 MFlops/frame(公表値、Raspberry Pi 4B 1coreで35ms / iPhone 6s Plusで7.8ms)。desktop CPUではこれより速いが未実測 |
| 合計 | **約3〜6分** | |

推論部は利用者が置くweightsで変わるので実測できていない。weightsを置いた後の実値は
logの `smile.built` の `realtime_factor` / `duration_ms` に出るので、そこで確認できる。

sampling間隔を4秒にすれば推論部はほぼ半分になる(decode部は変わらない — ffmpegはどの
間隔でも全frameをdecodeするため)。3時間の録画を全frame(約27万枚)見る案は、推論だけで
1時間を超えるので採らない。

---

## 7. 別のweightsを使うとき

置き換えは契約(§1)を満たせば可能で、model名はcodeに焼かれていない。ただし
**前処理の定数(mean/scale)・活性化・class順はmodelの契約であって好みの値ではない**。
既定値はここに書いた参照exportに合わせてあるだけなので、別のweightsを置くなら必ず
上書きすること。推測で合わせると確率が静かに壊れ、出力を見ても気付けない。

class名の数がmodelの出力数と合わなければengineはエラーにする(別の表情の確率を笑顔として
読むのを防ぐため)。

---

## 8. 確認済み / 未確認

**確認済み**(2026-07-26時点、出典を辿って確認)

- Ultra-Light-Fast-Generic-Face-Detector-1MB が MIT license であること
- 同modelの前処理 `(pixel - 127) / 128`・BGR→RGB・NCHW・320x240、後処理が
  「scoreの閾値 → hard NMS(IoU 0.3) → 正規化boxを実寸へ」であること
  (`run_video_face_detect_onnx.py`)
- 同modelの公表値: 1.11MB、90〜109 MFlops(320x240)、Raspberry Pi 4B 1coreで35ms
- FER+ (emotion-ferplus-8) の入力 `(N,1,64,64)`、出力 `(1,8)`、softmaxを掛けること、
  class順 `neutral, happiness, surprise, sadness, anger, disgust, fear, contempt`
- FER+ のlicense表記が取得元で食い違っていること(onnx/models: MIT、
  Hugging Face mirror: Apache-2.0)
- YuNet(OpenCV Zoo)が MIT であること、および生のONNX出力が stride別の
  `cls/obj/bbox/kps` でanchor decodeを要すること(opencv_zoo issue #192)

**未確認**

- 顔検出modelのscoreがgraph内でsoftmax済みかどうか。参照実装が出力を確率として
  0.7と比較しているため既定を `none` にしているが、export手順まで辿っていない。
  置いたweightsで検出が極端に多い/少ない場合は
  `TICTOK_SMILE_FACE_SCORE_ACTIVATION=softmax` を試すこと
- 顔検出modelのanchor数(`4420` とする記述を見たが出典で確認できていない)。engineは
  graphから読むので設定は不要
- FER+ の原type(Microsoft FERPlus)まで辿ったlicenseの確定
- 実weightsでの検出精度・笑顔判定の精度(閾値の既定値0.7 / 0.5が実配信で妥当かは
  未検証。生確率をsidecarへ残してあるので、後から掃引して決められる)
- 実weightsを通した所要時間(§6の推論部)
