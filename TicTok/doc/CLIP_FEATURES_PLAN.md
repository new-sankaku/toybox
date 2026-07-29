# 配信切り抜き機能 — 統合実装計画

4本の設計（範囲焼き込み / smart cut / reel配線 / 笑い検出）を1つの順序へ畳んだもの。
着手時に `doc/` へ移す。

## 前提: 着手待ち

`tictok/server.py` が本session外から変更中（retention・storage掃除の一群）。
4本すべてが `server.py` と `static/videos.js` を触るため、並行作業の完了を待ってから着手する。

---

## 1. 実装順序

順序は「他を待たせないもの」→「他の前提になるもの」→「重いもの」。

| # | 作業 | 触るfile | 前提 |
|---|---|---|---|
| **0** | **buckets の穴を塞ぐ** | `storage.py` / `collect/collector.py` / `core/config.py` | なし |
| 1 | 笑い検出 Phase 1（comment） | `core/laugh_text.py`(新) / `core/spike.py` / `server.py` / `videos.js` | **#0** |
| 2 | 連結機構の抽出 | `media/concat.py`(新) / `media/reel.py` | なし（挙動不変） |
| 3 | **切り出しのA/V整合 + smart cut** | `media/keyframes.py`(新) / `media/clipper.py` / `server.py` / `videos.*` | #2, 実測A |
| 4 | reel 配線 | `server.py` / `jobs.js` / `videos.*` / `core/ops_labels.py` | **#3** |
| 5 | 範囲焼き込み | `record/video_overlay.py` / `media/clipper.py` / `server.py` / `videos.*` | 実測B |
| 6 | 笑い検出 Phase 2（笑い声） | `media/laugh_audio.py`(新) / `server.py` | #1の実測結果 |
| 7 | 笑い検出 Phase 3（笑顔） | `media/smile.py`(新) / `server.py` | #6 |

### 測定を受けて順序を変えた点

**#0 を新設して先頭へ。** buckets を持つのは session 144本中84本で、**切り抜き候補を出せる録画は 135/340（40%）**。
笑い指標は buckets 経由なので、#1 を先に入れても**録画の6割で動かない**。#0 を直せば
見どころ・heat bar・peak_viewers・切り抜き候補の4機能が同時に復旧し、28,437 bucket / 58 session が戻る。
内容は (a) `cleanup_stale_sessions` が `_rebuild_buckets_locked` を呼ぶようにする、
(b) `timeline` deque の6時間上限で冒頭が落ちる件、(c) `session_id IS NULL` 136本（原因調査中）。

**reel配線(#4)を #3 の後ろへ。** reel の engine は各partで audio が video より短く、連結すると
接合点ごとにA/Vがずれる（合成で約148ms/接合、実素材で103〜384msのaudio不足を実測）。
先に配線すると「ずれた成果物が出るようになるだけ」。真因は切り出し段のA/V不揃いで #3 と同じ場所。

**#2 を #3 #4 の前に置く理由**: 両者が同じTS中間＋concat機構を使う。先に抽出しないと二重実装になる。
抽出は挙動不変で、`tests/test_reel.py` のassertを1行も変えずに通ることが完了条件。

---

## 2. file 衝突マップ

同じfileを複数の作業が触るため、並行実装は不可。上の順序で直列に進める。

| file | 触る作業 |
|---|---|
| `tictok/server.py` | #1 #3 #4 #5 #6 #7（全部） |
| `static/videos.js` / `videos.html` | #1 #3 #4 #5 |
| `tictok/media/clipper.py` | #4 #5 |
| `tictok/media/reel.py` | #2 #3 |

---

## 3. 実装前に埋める空白（測定結果）

| id | 内容 | 結果 |
|---|---|---|
| A | stream copyの入力側 `-ss` は backward か forward か | **解決: 実録画でも forward が起きる。** 密sweep25点で **3点(12%)がforward、最大1.789秒の欠落**。疎な4点では全backwardに見えたため一度誤判定した。支配要因はsegment境界との関係(playlist tag・offset・`-copyts`は無関係)。→ **任意時刻を `-ss` に渡さない。着地ptsを検証して要求より後ろなら失敗させる** |
| A2 | 既存clipperの欠陥（Aの帰結） | `make_clip` は任意時刻をそのまま渡すため .ts由来の切り出しが内容を失い得る。`keyframe_lead_seconds` は `max(0.0,…)` なので欠落が0と報告され前置きと区別が付かない。tolerance 1.0秒未満の欠落は警告も出ない |
| B | 窓経路の音声と0起点化 | **解決: 音声は `-map 0:a?` だけで足りる**（第2 input不要＝設計簡素化）。0起点は `-output_ts_offset -(start_time+rel)` のみ。`-avoid_negative_ts make_zero` は不可、`-muxdelay 0` はmp4に無効。`-copyts` は維持（外すとfilterの絶対時刻keyが壊れる） |
| C | 連結passで1回だけloudnorm | **解決、ただし前提が覆った。loudnormは完全にtiming中立**（無罪）。真因は切り出し時のA/V不揃いで、**連結の基準（正規化なし）自体が接合点ごとにA/Vがずれる**。実素材で確認済（下記） |
| D | 長GOP時の保護の必要性（playlist tag か GOP比か） | **解決: tagは無関係、比も決定要因でない。**支配要因はsegment境界との関係。0byte出力は比18倍で実在（比3では未発生） |

### C の詳細 — reel は「配線だけ」では済まない

実素材（3区間）で `reel.py` と同一引数で切り出したTSを実測:

| part | audio先行 | video尺 | audio尺 | audio不足 |
|---|---|---|---|---|
| 0 | 49ms | 10.158 | 9.774 | **384ms** |
| 1 | 47ms | 10.159 | 10.056 | 103ms |
| 2 | 79ms | 9.003 | 8.731 | 272ms |

連結結果は video 29.327 / audio 29.272 / format 29.376（要求30.0）。
**各partでaudioがvideoより短く（末尾が早く切れる）、連結するとその差が接合点ごとに累積する。**
合成素材での実測は接合点あたり約148ms、5接合で約740msに達する。

- `loudnorm` を区間ごとに掛けると先頭0.5秒がずれる、という `reel.py` docstringの根拠は
  **合成素材では再現しなかった**（要 実content確認）
- `aresample=async=1` は同期を直すが、実体は**各接合点へ約150msの無音を実挿入**するため
  連続音声ではdropoutとして聞こえる。`async=48000:min_hard_comp=1.0` なら無音は消えるが
  区間頭に最大-133msのlip-sync誤差が出る
- **本筋は切り出し段でA/Vのstart/endを揃えること。** それができれば aresample 自体が不要
- 副次: `linear=true` は target LRA < measured LRA のとき**無警告でdynamicへ落ちる**

### 実測で判明した既存の欠陥（Bの副産物）

`preview_clip` は絶対timestampのまま出力し、**窓開始120秒の例で121.4秒のempty edit**が両trackに入る。
窓焼き込みを正式経路へ昇格させる際に `-output_ts_offset` を入れないと、切り抜きがこれを引き継ぐ。
また窓焼き込み（再encode）は frame 精度で切れる（要求121.43に対し着地121.435）ので `keyframe_lead_seconds` は 0 を返せる。

## 3b. 笑い検出 Phase 1 の実測結果 — **実装可**

実DB（84 session / 81,831 bucket / comment 76,368件 / 40日）で検証。4基準すべて通過。

| 基準 | 結果 |
|---|---|
| `comments` の代理変数でないか | ρ = **+0.29**（基準0.9を大きく下回る） |
| gift活動の従属変数でないか | 偏相関 **\|ρ\| < 0.04**（comment総数を統制） |
| 別の時刻を指すか | laugh候補の **79.2%** が `comments` 候補と別時刻 |
| pattern誤検出でないか | gift burstと**負**の関係（笑い件数 -59%） |

### 設計既定値の訂正（実測で覆った3点）

| 項目 | 当初 | 実測後 | 根拠 |
|---|---|---|---|
| 単発 `w` を笑いに含めるか | 既定OFF | **既定ON** | 3,468件中FP **0件**(88件全数目視)。除くと笑いの41%を捨てる |
| per-user dedup | 既定ON | **設定自体を作らない** | 影響3.22%、ρの差0.0002。10秒bucketで同一userの重複がほぼ無い |
| `clip_candidate_laugh_min_comments` | 3 | **2** | 3では候補が89%消え、session窓合計の最大値 median 3.0 に接触 |

- `藁` は**削除**（唯一のhitが「藁人形」）
- `草` は複合語除外が必要（水草/除草/仕草/雑草でFP）
- **gift案内templateが「爆笑」「🤣」を含む汚染が実在**（同一session内3回以上・20文字以上で除外。影響0.6%）
- `ㅋㅋ` は0件。害はないが既定に入れる根拠はこのdataに無い
- zero-inflationの警告は方向は正しく程度は過大だった。単発窓のzは median **1.50**（8ではない）。影響を受けるのは22.1%のsession
- `min_values`=2 / `weight`=1.0 で上位20件の笑い占有は median 25% → flooding は起きない

### この結論の限界（重要）

**笑いhitの97.2%が2配信者（pomiiiip / wicha_3111）のもの**で、他5名は合計222件。
**外部妥当性はこの2名に限られる。** 新しい配信者を監視対象に加えたら再測定が必要。
特に「単発wが100%笑い」はこの2名の視聴者層の性質である可能性がある。
音声・映像channelとの独立性はPhase 2/3の実装後にしか測れない。

---

## 4. 既存側の欠陥（測定で確定したもの）

すべて実code／実DB／実素材で裏付け済み。切り抜き機能とは独立に存在する。

### 重い順

| # | 欠陥 | 実測 | 性質 |
|---|---|---|---|
| D1 | `cleanup_stale_sessions` が buckets を作らない | session 60本が欠落。見どころ・heat bar・peak_viewers・切り抜き候補が沈黙 | 非破壊で修正可（+69録画） |
| D2 | session削除が録画行と `.ts` を残す | 136録画が幽霊化、**.ts 9.9GB漏洩**、現在も発生中（直近7日で6本） | 修正は非破壊／既存分の掃除は**破壊的** |
| D3 | HLS seek に任意時刻を渡すと forward で内容が欠落 | 実録画で12%、最大1.789秒。`keyframe_lead_seconds` は 0 と報告され前置きと区別不能 | 着地検証が必須 |
| D4 | 切り出しの A/V 不揃い（reel の連結でずれが累積） | 各partで audio が 103〜384ms 短い。接合あたり約148ms | 真因は切り出し段 |
| D5 | `preview_clip` が絶対timestampのまま出力 | 窓開始120秒で **121.4秒のempty edit** | `-output_ts_offset` で解消 |
| D6 | `timeline` deque の6時間上限で長時間配信の冒頭が落ちる | 3 session、計1.89時間 | 非破壊で修正可 |
| D7 | 窓経路が音声を捨てている（`-an`） | 範囲焼き込みに音が入らない | `-map 0:a?` で解消 |
| D8 | `_run_ffmpeg` が出力pathへ直接書く | 中断時に完成品の顔をした断片mp4が残る | tmp→rename |
| D9 | 重複判定が `(kind, recording_id)` のみ | 同じ録画の別範囲が投入できない | |
| D10 | reel の probe が 0% のまま取り消せない | 3時間級で数十秒〜分、`register_process` 漏れ | |
| D11 | `keyframe_lead_seconds` がUIで未使用 | 「30秒頼んで67秒」の体感の正体 | |
| D12 | `precise` の切り出しが AV1 になる | `get_normalize_codec()` 既定が av1 | |
| D13 | job の `recording_id` が空だと断続的に拾われない | `NULL NOT IN` の三値論理。実行中jobが在るときだけ飢餓 | |
| D14 | `hls_source` の一時playlistが異常終了時に残留 | 2件確認 | 軽微 |

### 元の一覧

| 箇所 | 内容 | 直す作業 |
|---|---|---|
| `storage.py` claim SQL | `recording_id` が NULL の job は、実行中jobが1件でもあると `NULL NOT IN (...)` が真にならず拾われない。**平常時は動き、混雑時だけ止まる断続的な飢餓** | #3（reelは代表recording_idを持たせて回避） |
| `server.py` `_enqueue_media_job` | 重複判定が `(kind, recording_id)` のみ。同じ録画の**別範囲**が投入できない | #3 #5 |
| `media/reel.py` `_probe_sources` | 最初の進捗報告より前に全素材のkeyframe走査。3時間級で数十秒〜分。その間 ffprobe が `cancel.register_process` されておらず**0%のまま取り消せない** | #3 |
| `record/video_overlay.py` 窓経路 | 出力pathへ直接書く。中断すると完成品の顔をした断片mp4が残る（upscaleは tmp→rename 済み） | #5 |
| `record/video_overlay.py` 窓経路 | sidecar名が録画ごとに固定。同一録画の2範囲を並行renderすると衝突 | #5 |
| `static/videos.js` | `keyframe_lead_seconds` がUIで一切使われていない。**「30秒頼んで67秒」の体感の正体がこれ** | #4 |
| `core/config.py` | `get_normalize_codec()` の既定が `av1`。`make_clip(precise=True)` がこれを使うため、**NLEへ渡す素材がAV1になる** | #4（smart cutはheadのcodecを原本から決める） |

---

## 5. 笑い検出の設計要点

### 検出する3 channel（すべてCPU、VRAM 0）

| channel | 手法 | 追加install | 3時間1本 |
|---|---|---|---|
| comment | 正規表現（自前） | なし | 1秒未満 |
| 笑い声 | CED-tiny ONNX + onnxruntime | 実質なし（onnxruntime 1.23.2 導入済・CPU provider） | 2〜3.5分 |
| 笑顔 | YuNet + HSEmotion ONNX | opencv-python | 4〜6分 |

GPUを使わないのは、12GB を faster-whisper と超解像が既に奪い合っているため。
CPUへ逃がせば `gpu_slot` を取らず焼き込みと並走できる。

### valence（喜怒哀楽の全象限）は採らない

- cross-corpus実験で arousal 62.6% に対し **valence 55.6%**（ほぼcoin flip）
- 日本語SER corpus は演技音声中心で、配信の自然発話とdomainが違う
- 決め手は**検証可能性**。笑い声・笑顔・笑いcommentはその時刻へseekすれば人が正誤を確認できる観測。
  valence は内的状態の推定で正解が存在しない。「候補が的外れでも気付きにくい」というこの機能固有のriskを最大化する

代わりに「笑い秒数 / 笑いcomment件数 / 笑顔秒数」の**生値を候補行に並記**し、userがその場で反証できる状態にする。

### 必須の対処: zero-inflated な z-score の暴発

`spike.py` は指標間で z の **max** を取る（実code確認済み）。笑いの系列はほぼ全ゼロで標準偏差が極小になるため、
**ほとんど笑わない配信の0.4秒の笑いが z=8 を叩き出して候補上位を独占する**。

対処は `detect_spikes` へ後方互換のoptional引数を2つ追加する:

- `min_values`: 絶対量の下限（「窓内で合計2秒以上笑っていること」）。
  これは fallback ではなく**判定条件の追加**（0.4秒の笑いは笑っている場面ではない、という定義）
- `weights`: z へ掛ける倍率。「笑い重視」をここで表現

既定値では既存挙動と完全に同一で、配信者pageの見どころ（`streamer_highlights`）は影響を受けない。

### 笑顔検出の構造的な穴

battle・collab では画面が分割され、**どの顔が配信者本人かDBのdataから復元できない**。
該当録画では笑顔metricを出さない（`server.py` の音声metric skipと同じ作法）。
battle常連の配信者では恒常的に機能しない。これがPhase 3を最後に置く実務上の理由。

### 検証設計（この機能の中核）

「上位10件見て8件当たった」には意味がない。**配信者は元々よく笑うので、無作為な場面でも半分は笑って見える。**

したがって盲検 precision@K を**無作為対照つき**で行う:

1. (a) 新ranking上位K / (b) 旧ranking上位K / (c) 無作為K を各15件
2. shuffleして出所を伏せて再生し、0/1 で採点
3. **(a) が (c) を有意に上回らなければ、この機能は動いていない**

加えて、sidecar には threshold を掛ける**前の生確率**を保存する。
正解labelができた後、再decodeなしに threshold を掃引して precision/recall 曲線を引ける。
配信音声はAudioSetの学習分布とcalibrationがずれるため、文献の既定値をそのまま使ってはいけない。

### 運用上の制約

- `media_queue` の worker は1本。笑い解析jobが焼き込みqueueを塞ぐ
- 配信者1人100本を一括すると 12〜17時間。夜間実行前提
- 新sidecarを `*_artifact_paths` へ登録し忘れると、録画削除時に取り残されて堆積する（`_backup` 307GB の前例あり）

---

## 6. ユーザー判断が要る事項（未決）

| # | 内容 | 選択肢 |
|---|---|---|
| 1 | 素材版(variant)の語彙 | A: 現行3値の意味を「この範囲でその素材を得る」へ変える / B: 5値にして経路を明示選択 |
| 2 | 範囲内にcomment も gift も無い場合 | 焼き込み経路のまま出力し実数を報告 / 拒否する |
| 3 | 切り出しmodeの既定 | `copy` 据え置き（現行の「前後の余白は素材用途で扱いやすい」判断を維持）/ `smart` へ倒す |

#3 は設定 key（`clip_default_mode`）にするので、実測後に code 変更なしで切り替えられる。

---

## 追記（2026-07-26 完了時点）

この計画で「未解決」「真因は切り出し段」と書いてある A/V ずれは**解決済み**。ただし
**当時の診断（各partで audio が 103〜384ms 短い / 接合あたり約148ms）は誤り**だった。
packet levelで測り直した実際の姿と、修正・検証の結果は `doc/CLIP_TIMEBASE.md` §6 にある。
要点だけ:

- 真因は「audio が短い」ではなく **`-ss` の着地が video と audio で非対称**（video は要求の
  直後の keyframe から = **要求した範囲の頭を失う**、audio は手前の segment 境界から）
- 症状は「連続的なずれ」ではなく**接合ごとの穴**（part の内側は修正前も ±18ms で同期していた）
- 同じ欠陥は `clipper` の copy 経路にもあり、**30秒の切り出しが先頭1.99秒ぶん映像なしで
  出ていた**。copy 経路も同じ2段（TS中間経由）へ直した
- 副産物として `keyframes.video_keyframes` の `-read_intervals` が実HLS録画で必ず空振りする
  bug を発見・修正（smart cut は実録画で動いていなかった）

`doc/CLIP_TIMEBASE.md` §6 の数値が唯一の正で、この計画側の 148ms / 103〜384ms という
記述は**参照しないこと**。
