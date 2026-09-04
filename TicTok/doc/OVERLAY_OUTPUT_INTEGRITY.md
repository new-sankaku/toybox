# 焼き込み成果物の尾切れ検出

## 症状

コメント焼き込み(burn-in)が `rc=0` で成功を名乗ったまま、成果物の**片側 track だけ**が
途中で終わる。`K:\80_Tiktok` の `.overlay.mp4` 59 件中 3 件で発生していた。

| 録画 | 出力日時 | video track | audio track | 素材の尺 |
|---|---|---|---|---|
| 00372_streamer_a_20260726_223438 | 2026-07-27 20:34 | **4318.6s** | 13265.9s | 13267.3s |
| 00391_streamer_a_20260727_225434 | 2026-07-28 21:43 | **4859.4s** | 12252.3s | 12252.3s |
| 00392_streamer_a_20260728_113329 | 2026-07-28 22:18 | 14381.5s | **4315.3s** | 14381.4s |

切れる側は回ごとに入れ替わる。素材(.ts)と comment 層はどちらも全尺で無傷であり
(00391 は層 306,309 frame / 12252.4s を作り切っている)、欠落は合成 encode の段だけで
起きている。

## なぜ誰も気付けなかったか

1. **container 尺は最も長い track を名乗る。** 00391 の `format=duration` は 12252.3s で、
   video track が 4859.4s しか無いことを一切示さない。既存の duration check
   (`_log_duration_check`) は `format=duration` を見るため、出力に対して使っても素通りする。
2. **ffmpeg は rc=0 で返る。** 既存の失敗判定は `returncode != 0` / size 0 のみ。
3. **成功時に ffmpeg の stderr log を消していた。** 原因が出るとすれば warning 段
   (decode error / non-monotonous DTS / packet corrupt) だが、`-loglevel error` で
   そもそも拾っておらず、log file も成功時に削除していた。

結果、job は「焼き込みが完了しました」を出し、成果物を再生した user が最初の発見者になる。

## 追加した関門

`tictok/record/video_overlay.py`

- `_probe_stream_spans()` — 出力を **track 単位** で測る(`stream=duration,nb_frames,
  avg_frame_rate`)。container 尺は見ない。
- `_verify_output_spans()` — `_run_ffmpeg` の rc 判定の**後**に必ず通る。
  - 各 track と期待尺(`expect_seconds`、全尺経路は素材の尺)を比較。不足側だけを咎める。
  - video track と audio track を相互比較。期待尺が取れない経路でも片側の欠落を捕まえる。
  - 全尺の焼き込み(`window is None`)では **例外**。成果物を削除し、cache の
    `.overlay.meta` も書かれないので、次回は再 render される。
  - 窓あり(プレビュー / 範囲焼き込み)は記録のみ。窓の終端は素材末尾で正当に切られ、
    `-ss` の着地が video/audio で非対称なため、同じ基準で落とすと誤検知に埋もれる。

実測での分離は明確で、閾値の余裕は 3 桁ある:

| | v/a 差 |
|---|---|
| 正常 (00395 / 00328) | 0.06s / 0.05s |
| 異常 (00391 / 00392) | 7392.9s / 10066.2s |

既定の許容は 2.0 秒(`TICTOK_OVERLAY_OUTPUT_TOLERANCE_SECONDS`)。

## 追加した証拠

- `-loglevel` を `error` → **`warning`**(`TICTOK_FFMPEG_LOGLEVEL`)。stderr は file へ
  向けているので端末は汚れない。
- 尾切れを検出した回は **ffmpeg log と filter graph を残す**(成功時のみ従来どおり削除)。
  調査中は `TICTOK_FFMPEG_LOG_KEEP_ON_SUCCESS=1` で正常だった回の log も残せる。
- `_gpu_load_ctx()` — render の開始時と終了時に「GPU 枠を握っている stage 一覧 / 待ち数 /
  同時に走っている焼き込み encode」を記録する。同時実行との相関は、症状を出した回そのものが
  隣の状況を持っていないと後から復元できない。

### 追加された event (JSONL)

| event | 意味 |
|---|---|
| `overlay.output_spans_checked` | 合格。track 別の尺・frame 数・実効 fps を残す |
| `overlay.output_truncated` | 不足を検出。全尺経路は ERROR + 例外、窓経路は WARNING |
| `overlay.output_spans_unmeasured` | ffprobe が無い等で測れなかった |
| `overlay.burn_in_failed` | 既存。GPU 実行状況と log path を追加 |

## 切り分けの結果

計測環境: ffmpeg 2026-06-10-git-b29bdd3715 (gyan full build) / RTX 4070 Ti / driver 591.86。

### 同時実行 — 否定

`gpu.py` の semaphore(既定 1)は正しく直列化しており、3件の encode 窓を JSONL で洗った
結果、**どの窓にも他の media/GPU job は 1 件も走っていなかった**。特に 00392 は完全に
単独で走って音声を落としている。正常回(00395)も同じく単独で、区別が付かない。

`hls_source` の一時 playlist を別 job が消す線も否定した。名前は lease ごとに
`uuid4().hex[:12]` で、削除は自分が書いた分だけである。

### av1_nvenc — 単独では不十分

出力 59 件すべてが av1_nvenc で、正常回と異常回で encoder は同じ。異常 3 件に共通する
条件(2 倍拡大 2560 高 / 長尺 3.4〜4.0h / comment 層 17〜21GB)を満たしつつ正常だった回
(00328: 4.7h・1440x2560・出力 6.5GB)があり、条件だけでは再現条件が確定しない。

### 再現実験 — source / encoder / 音声正規化はいずれも無罪

00391 の素材(全尺 3h24m)に対し、本番と同じ入力 option・同じ av1_nvenc・同じ 1280x2560
拡大で、comment 層と ASS・gift icon だけを外した encode を 2 本走らせた。

| | video | audio | v/a 差 |
|---|---|---|---|
| 実験① 層なし・`-c:a copy` | 12252.32s / 306,308 frame | 12252.23s | -0.09s |
| 実験② 層なし・音声正規化あり | 12252.32s / 306,308 frame | 12252.30s / 574,327 frame | **-0.02s** |
| 本番(壊れた出力) | 4859.40s / 121,326 frame | 12252.30s / 574,327 frame | -7392.9s |

どちらも **完全な出力**(25fps CFR きっかりで、層の 306,309 frame とほぼ一致)。よって
素材・av1_nvenc・尺・拡大率・`aresample=async=1,loudnorm` のいずれも原因ではない。

実験②の音声は本番の壊れた出力と **profile も frame 数も完全に一致**(AAC-LC 574,327)
しており、本番経路の音声 encode を正しく再現できていることの裏付けになっている
(素材は HE-AAC で、`-c:a copy` の実験①だけが 287,090 frame になる)。

残る差分は **comment 層の合成経路**だけである:

- 17.6GB の `.overlay.comments.mov` を第 2 video input として `overlay=eof_action=pass`
- gift icon 106 枚の `overlay=eof_action=repeat` 連鎖
- `ass` filter

### 素材の packing — 無関係

00391 の素材は 1 本へ束ねた `pack000.ts`、00392 は束ねる前の `seg*.ts` 群。どちらも
壊れているので、束ねの有無は関係しない。

## 原因(確定)

**HLS 直読みへ移った結果、CFR base pre-pass が 2026-07-25 以降まったく走っていなかった。**

`_probe_is_vfr` は `avg_frame_rate` が公称(`r_frame_rate`)の 95% を下回るかで VFR を
判定する。焼き込みが mp4 ではなく .ts を curated playlist 経由で直読みするようになった
ため、この probe が hls demuxer の値を見るようになった:

| | 値 |
|---|---|
| `r_frame_rate`(公称) | 299/12 = 24.9167 |
| `avg_frame_rate`(hls demuxer) | **25/1** |
| 実測(00398: 283,793 packet / 12843.2s) | **22.10** |

hls demuxer が返すのは segment の実測平均ではなく container の hint で、公称より**上**の
値を名乗る。判定式は必ず False へ倒れ、`cfr_fps` が None になって `_prepass_cfr` も
in-graph の `fps=` も両方走らない。

log の `base_is_prepass` が境目をそのまま持っている:

| 時期 | `base_is_prepass` | 尾切れ |
|---|---|---|
| 〜7/22(00323 / 00328 / 00276 / 00341 / 00345) | **True** | 0 件 |
| 7/25〜(00268 / 00372 / 00355 / 00391 / 00392 / 00398) | **False** | 4 件 + 00268 の frame 欠け |

pre-pass が飛ぶと、24.917fps CFR の comment 層(320,011 frame / 18.7GB)を VFR の HLS へ
直接 `overlay` で合成し、かつ音声も同じ HLS input から `-map 0:a?` で取ることになる。
ffmpeg はこれを **rc=0 のまま片側 track を途中で止める**形で壊す。「未解決」に挙げていた
frame 欠け(00268 の 13%、00398 の実効 21.197fps = 出力 272,237 / 素材 283,793)も同じ根で、
VFR base に CFR 層を framesync で噛ませた時の落ち方である。

00328(4.7h・正常)が反例に見えていたのは、あれが 7/20 の出力で `base_is_prepass: True`
だったため。条件ではなく**時期**で分かれていた。

### 素材と音声経路は無罪(実測)

00398 の curated playlist に対して:

| 経路 | 結果 |
|---|---|
| `-map 0:a -c:a copy -f null` | 12843s 完走 |
| `aresample=async=1,loudnorm` → aac 192k | duration 12843.200 / **602,023 frame** 完走 |

音声の source も正規化 filter も壊れていない。壊れるのは合成 encode の時だけである。

### 直したこと

`_probe_is_vfr(..., is_hls)` を足し、**HLS 入力では `avg_frame_rate` を見ずに VFR として
扱う**(録画は live HLS の stream copy なので定義上 VFR)。全尺経路・窓経路の両方が
`source.is_hls` を渡す。

確認(全尺を焼かずに):

- 実素材の HLS source で `_probe_is_vfr` → **True**(修正前 False)
- 窓経路を実際に流して `CFR baseの前処理が完了しました` を確認、合成出力は
  748 frame / 30.02s = **24.9167fps ちょうどの CFR**(修正前の全尺は実効 21.197fps)

尾切れそのものが消えたことは、症状が 4065〜4859s まで出ないため全尺 render でしか確認
できない。この修正は 7/22 まで 5 ヶ月間 1 件も壊れなかった構成へ戻すものである。

## 残っているもの

- **7/25〜の出力(`base_is_prepass: False` の回)は尾切れが無くても comment がずれている。**
  00268 / 00355 等は関門を通っているが、CFR 層を VFR base へ噛ませた出力なので、
  [[tictok-comment-layer-framesync]] と同じズレを持つ。再出力の対象になる。
- **尺は足りているのに frame だけ欠ける形**は上の根本原因で説明が付く(pre-pass 不在)。
  以下は当時の実測で、`video_fps_effective` の値としては引き続き記録している。00392 は
  video track が全尺
  (14381.5s)ありながら 276,360 frame しか無く、層の 359,538 frame に対して 23% 少ない。
  00268(v/a 一致で「正常」に見える回)も層 127,294 に対し出力 110,629 frame で 13% 少ない。
  正常時の基準がまだ無いため判定には使わず、`video_fps_effective` として値だけ記録している。

  00392 の packet 間隔を実測すると、位置によって出力の実効 rate が違う:

  | 区間 | 実効 rate |
  |---|---|
  | 4293.6〜4340s | 12.5 fps(0.08s 間隔 = 1 frame おき) |
  | 8000〜8020s | 27.1 fps |
  | 12000〜12020s | 30.1 fps |

  半分に落ちる区間の開始(≈4294s)は、**音声 track が終わる 4315.3s とほぼ同じ位置**である。
  素材側の playlist に不連続は先頭の 1 個しか無く、この位置には何も無い。

- ffmpeg が `-filter_complex_script is deprecated, use -/filter_complex instead` を出す。
  現行の build では動くが、この option は Windows の command line 上限(32767 字)を避ける
  ために必須なので、廃止される前に `-/filter_complex` へ寄せる必要がある。
