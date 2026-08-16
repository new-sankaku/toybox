# BGM除去（出力から話し声だけを残す）

切り出しの出力から、BGM・効果音・環境音を落として配信者の話し声だけを残す。
音量正規化（`clip_normalize_audio`）と同じ「出力ごとに選ぶoption」で、既定はOFF。

## 何が消えるのか

modelは「話し声かどうか」で分けるので、**BGMだけが消えるわけではない**。実測で
話し声以外が -22.2dB 落ちる。同じ側に入るもの:

- BGM（曲・環境音）
- gift SE
- battleの効果音・歓声
- コラボ相手の声（マイクが遠ければ「話し声以外」の側へ寄る）

このため原本（`.ts`）には掛けない。battleのある録画に常時掛けるのは素材を壊す方向で、
**出力するときに選ぶ**形にしてある。

## 使うmodel

`MossFormer2_SE_48K`（ClearerVoice-Studio）。

**音楽用の音源分離を使ってはいけない。** Mel-Band Roformer等は「歌声 vs 伴奏」を分ける
学習をしているので、BGMが曲のときにその曲のボーカルを配信者の声と同じ側へ置く。
実配信で試して伴奏だけが消え歌が残った。パラメータでは直らない、model classの違いである。

| 案 | BGM抑圧 | 声 | click/min | 判定 |
|---|---|---|---|---|
| **MossFormer2_SE_48K** | **-22.2dB** | -1.6dB | 59.3 | 採用 |
| 音楽分離→MossFormer2（cascade） | -23.8dB | -2.0dB | **172.0** | 却下（artifactが3倍） |
| 音楽分離のみ（Roformer） | -10.0dB | -1.6dB | 64.7 | 却下（歌が残る） |

48kHz nativeなので、録画のsample rateのまま処理できる（44.1kHzのmodelで起きる往復
resampleが無い）。実測でsample数のdriftは0。

## 掛ける場所は「出来上がった成果物」

切り出しと同時には掛けない。stream copyの切り出しは要求より手前のkeyframeから始まる
ため、「要求した窓」と「実際に出力された窓」が一致しない。別々に切った音声を後から
重ねると、その差だけ音がずれる。**出来上がったmp4から音声を取り出して差し替える**なら
窓は定義上一致する。映像はstream copyのままなので、追加費用は音声だけである。

音量正規化を併用する場合、切り出し段では掛けずに差し替えと同じencodeで1回だけ行う
（先に正規化するとAACを2世代重ねることになる）。

## 別processで動かす理由

`tictok/record/bgm_child.py` を **BGM除去用venvのpython** が直接起動する。3つとも実測。

1. clearvoiceはtorchを**CPU版で上書きする**。本体venvへ入れるとUp出力がGPUを失う
2. 文字起こし（faster-whisper = CTranslate2）と同processに置けない。cuDNNの版が
   食い違う組で呼ばれるとprocessごとfail-fastで即死する（`doc/STT_PROCESS_ISOLATION.md`）
3. 子の死は親が終了codeとstderrで必ず観測できる。job毎にVRAMも必ず解放される

親子の約束はSTTと同じで、**子の標準出力はJSONLの制御channel専用**。clearvoiceは進捗を
標準出力へ書くので、子の側で標準errorへ寄せてある。

## 速度

RTX 4070 Ti。固定約5.5秒（process起動3秒 + model load 2.5秒）＋ 尺÷18.8。

| clip尺 | GPUが空いているとき | serverが他のjobでGPUを使っているとき |
|---|---|---|
| 1分 | 約9秒 | 約18〜26秒 |
| 3分 | 約15秒 | — |
| 10分 | 約45秒 | — |

VRAMは尺によらず0.25GB（modelが内部で分割処理する。10分で確認済み）。

## 出力

- **monoになる。** modelがmonoしか受け取らないため。録画の左右chは実質同一
  （L-R差が本体より27.5dB下）なので落ちる情報は無い
- file名は `.nobgm` を名乗る。同じ範囲のBGM入り・BGM無しを両方持てる
- 掛け損なった出力は残さない。BGM入りのまま `.nobgm` を名乗るfileが残ると、
  名前が中身の嘘をつく（一覧は名前からしか素性を読めない）

## 設定

**.env**（実行環境）:

```
TICTOK_BGM_REMOVE_ENABLED=1
TICTOK_BGM_REMOVE_PYTHON=AI_AUDIO/venv_cv/Scripts/python.exe
TICTOK_BGM_REMOVE_MODEL=MossFormer2_SE_48K      # 既定
TICTOK_BGM_REMOVE_TASK=speech_enhancement       # 既定
TICTOK_BGM_REMOVE_DEVICE=auto                   # 既定（CPUは子が拒否する）
```

**設定画面**（既定値）: `clip_remove_bgm`（既定0）。切り出しのたびに画面側で変更できる。

## 構築

```bash
python -m venv AI_AUDIO/venv_cv
AI_AUDIO/venv_cv/Scripts/pip install clearvoice
AI_AUDIO/venv_cv/Scripts/pip install --force-reinstall torch==2.11.0 torchaudio==2.11.0 \
    --index-url https://download.pytorch.org/whl/cu128
```

**順番が重要。** clearvoiceを後に入れるとtorchがCPU版へ置き換わる。入れた後は必ず
`torch.cuda.is_available()` を確認する。

## 検証用CLI（`AI_AUDIO/`）

serverからは呼ばない。model選定と効果測定に使ったもの。

| script | 用途 |
|---|---|
| `scripts/audio_ab.py` | 加工前後を同じ物差しで比較（BGM残量・click/min・貼り付き率・sample数一致） |
| `AI_AUDIO/enhance_cv.py` | speech enhancementを直接実行（複数fileのbatchも可） |
| `AI_AUDIO/stt_ab.py` | 文字起こしの加工前後比較 |
| `AI_AUDIO/stt_experiment.py` | 対照群つきの文字起こし比較（下記） |

却下した音楽用音源分離（`audio-separator` + Mel-Band Roformer）の検証環境は、専用venvとweightsで8.3GBあったため削除した。再現するなら別venvを作り直す:

```bash
python -m venv AI_AUDIO/venv
AI_AUDIO/venv/Scripts/pip install "audio-separator[gpu]"
AI_AUDIO/venv/Scripts/pip install --force-reinstall torch==2.11.0 torchaudio==2.11.0 \
    --index-url https://download.pytorch.org/whl/cu128
```

## 文字起こしへの転用は否定済み

「BGMを消せば文字起こしが良くなる」を60窓（3配信者・10録画・各60秒・BGM量
-28.1〜-71.8dB）で検証し、**効果なし**と結論した。

対照群は3つに分けた。A=原音 / B=原音を同じ経路（mono48k化・peak正規化）に通し
**modelだけ通していない**もの / C=BGM除去。さらに同一fileを2回流してwhisper自身の
揺らぎを測った。

| 指標 | A | B | C | C-B 平均差 [95%CI] |
|---|---|---|---|---|
| avg_logprob | -0.449 | -0.445 | -0.436 | +0.009 [-0.023, +0.040] |
| 文字数 | 168.2 | 166.8 | 167.0 | +0.2 [-10.3, +8.5] |
| segments | 15.8 | 15.8 | 16.6 | +0.8 [-0.6, +2.2] |

すべて信頼区間が0をまたぐ。BGMが鳴っている窓（n=19）に絞ると -0.011 とむしろ悪い側。
whisperはほぼ決定的（60窓中55窓でtext完全一致、avg_logprobの揺らぎは絶対値平均
0.0019）なので、C-Bの差は**測定できるほどの効果がない**という意味である。

文字化けtokenがBGM除去で増えるという当初の観察も、60窓の合計でA=1/B=1/C=3であり
**加工の影響とは言えない**（whisperが元々まれに出す）。

## 残っている宿題

**lip音は解決していない。** click/minは原音40.7に対しBGM除去後59.3で減っていない。
BGMのmaskingが外れて露出した分である。これは別の層（生成系のspeech restoration、
または音源分離zooの `aspiration` model）の話になる。
