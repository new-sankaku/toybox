# TicTok 16機能 実装 最終報告

作成日: 2026-07-19 / branch: `tictok/package-refactor-and-features`

---

## 0. 全体の前提（読む前に）

- 本報告の「動作確認済み」は、**隔離環境（複製DB / port 8530・8531）で実際にHTTPを叩き、応答・生成file・ffprobe実測値を確認したもの**だけを指します。
- **browserでの画面目視は全機能で未実施です。** userのserverが実DBで稼働中で二重起動できなかったためで、job画面・運用log画面・設定画面・analytics新card・履歴画面の追加buttonは、いずれもHTML/JSの構文検査とAPI応答までしか確認していません。
- 検証中に**実配信へ偶発接続し、30.5秒ぶんの二重録画が発生しました**（file削除済み）。この副作用は修正phaseで `TICTOK_NO_RESTORE` を追加して封じ、無効化を実測確認済みです。
- **実DB（tictok.db）へ意図しない副作用が2件あります**（後述「残課題」5番）。

---

## 1. 機能ごとの状態

### F1: GPU排他の一元化 — **完了**

- `core/gpu.py` に re-entrant semaphore（既定1）を新設し、stt / upscale / avatar_upscale / overlay の4箇所で取得。
- evidence: upscale実行中に `GET /api/jobs` → `gpu={"limit":1,"active":["upscale"],"waiting":0}`。単体testで、別Taskからの取得が0.41秒待機し、nested取得はno-opで通過することを実測。
- 制約: **STT(transcribe_queue)は独立queueのまま**。VRAM競合はsemaphoreで潰れていますが、queue/UIの一元化はしていません。録画finalizeの再encodeは意図的にsemaphore対象外（録画を遅延させないため）。

### F13相当基盤: 永続job queue + job画面 — **部分的**

- `media_job_queue` 表 + 1本直列worker、`/jobs` 画面、cancel/retry。
- evidence(pass): `POST /api/recordings/679/output` → `{"job_id":"147bfe8a","state":"pending"}` 即返し → 完了時 `result.output_path=...overlay.mp4`。retryで新job_id払い出し→completed到達。`GET /jobs` 200。session一括は `group_id` 返却、存在しないsessionは404。
- **cancelは一度failしたのち修正・再検証済み**:

| 項目 | 修正前(実測) | 修正後(実測) |
|---|---|---|
| 最終state | `failed` | `cancelled` |
| message | 「CFR正規化(pre-pass)に失敗しました（ffmpeg）。」 | 「取り消しました。」 |
| ops_event | `overlay.job_failed` severity=**error** | `overlay.job_cancelled` severity=info |
| cancel→終了 | 109秒 | 1〜2秒 |
| 中間file残存 | `.comments.mov` 5.77GB + 0byte log | 0件 |

- 未完: **実行中の再mp4化はcancel不可**（409で明示拒否）。preview/clip の「描くものが無い」はjobとして `failed` 着地（stillの409と不揃い）。cancel後 `stage` が「取り消し中…」のまま残る表示不整合。

### 容量の可視化とgate（1-4） — **部分的**

- evidence(pass): `GET /api/disk` が record_dir(C:) と record_dir_final(K:) の実値を返却（C: 約116GB / K: 約5.4TB空き、`min_free_bytes=21474836480`）。
- **未検証: 507拒否のcode pathは一度も通っていません。** 到達にはdiskを実際に埋める必要があり破壊的なため見送りました。
- 制約: gateは焼き込み/Up出力/session一括のみ。文字起こし・再mp4化・clip単発・waveform生成は無gate。録画開始は警告logのみでgateしません（収集を止めないため）。

### 容量内訳とretention（3-2） — **部分的**

- evidence(pass): `POST /api/storage/scan` が138.5秒で完了し、`GET /api/storage/usage` が実走査値を返却（source 391.3GB/251file、ts 106.1GB/513,424file、overlay 33.1GB、backup 30.0GB、配信者別 pomiiiip 392.8GB 等）。
- evidence(pass): retention dry-run で `total_items=7 / 3,932,524,847B`、derived/sourceは既定OFFで理由文つきskip、`apply=true&confirm=false` → 400。**実削除は一切実行していません。**
- evidence(pass): `POST /api/recordings/665/protect` 200、存在しないid → 404。
- **未検証: `DELETE /api/recordings/{id}/derived` の成功path**（404 pathのみ確認）、および retention の実削除。
- 制約: **自動実行(scheduler)なし**。設定値だけでは何も消えず、設定画面での dry-run → 明示確認でのみ削除が走ります。volume別上限は未実装。

### F2: 字幕書き出し（SRT/VTT/TXT） — **完了**

- evidence: 実転写4286 segmentの録画665で srt 308,168B / vtt 287,853B / txt 154,980B を200で取得。cue数4286、開始時刻の非単調0件、`end<start` 0件。未転写録画→404、不正format→400。
- **検証で1件bugを発見し修正済み**: 最終cue end=16861.81s に対しmedia実尺16860.04s（1.77秒超過）。ffprobe実測尺でcueを打ち切る修正を入れ、再検証で「実尺8.000sに対し9.77sのcueが8.000へ打ち切られ、完全範囲外cueは出力されない」ことを確認。

### F3: 字幕の焼き込み（既定OFF） — **部分的**

- evidence(pass): 設定ONにして録画665の静止画プレビューを再生成し、**出力pngを目視**。画面高58%付近にSTT字幕が描画され、上部Battle score bar・下部Comment帯と重ならないことを確認。libassでのink bbox実測（横中央対称・縦中心58%）も別途取得済み。
- **未確認: 全尺の焼き込みmp4を生成しての目視**（GPU encodeに数十分かかるため）。
- 制約: 低信頼segmentのgate（avg_logprob / no_speech_prob）は**未実装**（承認事項と判断し見送り）。誤認識もそのまま焼き込まれます。字幕は libass 描画のためカラー絵文字は出ません。Session一括は1本でも転写欠落があれば全体を409で拒否。

### F18: 焼き込み静止画プレビュー — **完了**

- evidence: `POST .../preview/still` → 200 / 25.6秒、`GET still.png` → 896,489B / PNG 720x1280。**目視で** Battle score bar（チーム戦2v2 6,156 vs 28,552）・Gift card 4枚（icon画像付き）・avatar付きcomment feed・カラー絵文字が本出力同等に描画されることを確認。

### F19: 焼き込み動画プレビュー — **完了**

- evidence: `POST .../preview/clip` が0.055秒で即返し、job実行 **5.4秒**で完了（全尺4.7時間の本出力とcostが桁違い）。ffprobe: av1 720x1280 / nb_frames=750 / duration=30.000000 / start_time=15991.6。
- 制約: 音声なし(`-an`)。`-copyts` のためtimestampは0始まりではありません（設計上の意図）。設定画面のjob待受はreloadで失われます（再押下でcache hit）。

### F5: clip音量正規化 + 出力版選択 — **部分的**

- evidence(pass): 録画665の30秒clip、`normalize_audio:true` → 応答 `{"normalized":true,"output_duration_seconds":30.0}`、ffprobe format duration=30.000000、**ebur128実測 I=-16.8 LUFS**（正規化なしは -27.1 LUFS）。尺一致と正規化の実効を確認。
- **未検証: 焼き込み出力 / Up出力への正規化適用のend-to-end**（GPU encodeが数十分〜数時間のため、同一音声引数での短尺再encodeによる尺一致とLUFS到達までの確認に留めています）。
- 制約: loudnormは単一passのため目標-14 LUFSに対し実測 -16.8〜-14.0 とばらつきます。焼き込みが走らない録画（描くものが無い）には正規化もかかりません。

### F4: 切り出し候補 + 一括書き出し — **完了**

- evidence: `GET .../clip-candidates` → z-score降順の実値（例: `start:2924.1, end:2999.97, zscore:16.65, diamonds:18003`）。`POST /api/clips/batch`(2件) → job完了、`result={count:2, bytes:2754555, normalized:true}`、実file 2本をdirで確認。30秒録画では空listを200で返し推測しません。
- 制約: 検索hitからの直接一括書き出しは未実装。候補の窓mergeで指定30秒に対し83〜93秒になることがあります。順位は素のz-score最大値のみ（重み付けは根拠が無いため入れていません）。

### F6: 流入元 / follow関係の計装 — **部分的**

- evidence(pass): 検証中に偶発接続した実配信(session 315)で**新規計装が実際に埋まりました**。`sources=[homepage_hot-live_cell:7, live_merge-live_cover:6, inner_push-inner_push:1, message-live_cover:1, unknown:1]`、`follow.breakdown=[following:2, not_following:14]`、`engaged.roles={sub:8/15, mod:8/15, gg:15/15}`。
- **ただし被覆率は `coverage=0.0002`（89,220 joins中 measured 16件）。** 計装前の89,204件はunmeasuredとして別掲され、非followerへ丸められていません。
- **未実施（本命）**: doc §2-5 の中核である「organic入室の重み（base0.15＋再訪0.45＋…）を実測labelで置換」は**やっていません**。既存joinsの被覆率が0%で、今置換するとpanelが丸ごと計測不能になるためです。**実配信でデータが貯まってから別作業で行う必要があります。**
- discovery/referred/incentivized の4分類もしていません（解釈になるため）。

### F10: 収集カバレッジ（Phase1計装 + Phase2解析） — **完了**

- evidence: `GET /api/analytics/coverage` 200 / 0.175秒。`instrumented={measured:1, unmeasured:115}` で**計装前sessionを「計測不能」として分離**（欠測0秒に化けていないことを実測確認）。sampling median 2.54s / p95 median 10.91s / worst 214.44s、録画カバレッジ中央値99.5%、STT 45/168(26.8%)。days filterも機能。
- 制約: 収集開始遅延は `sessions.live_create_time` が必要で、実DBは全115 sessionがNULLのため**現状は常に「計測不能」表示**です（今後の収集分から埋まります）。

### F9: Battle展開統計 — **完了**

- evidence: `GET /api/analytics/battle-flow` 200。`n_battles=439, n_eligible=382`、forms={1v1:126, team:76, multi:180}、excluded={chimera:42 等}。残り60秒リード `{n:201, k:155, rate:0.7711, ci:[70.8,82.4]}`、逆転率0.2149、末尾集中度(crit差引後)中央値0.3116（判定不能86戦を別掲）。
- 既知の不一致: 勝敗を `end_time` 時点で判定し直しているため、履歴画面の `battle.result` と**9戦だけ食い違います**（注記でuserに明示済み）。score_seriesはPK終了後も伸びるため、この切り直しは必要な処置です。

### F12: AI結果の永続化 — **部分的**

- evidence(pass): **GETがLLMを起動しないこと**を応答時間で実証。`GET /api/sessions/306/comment-analysis` → 200 / **0.004秒** / `analysis:null`。`GET /api/streamers/wicha_3111/ai-review` → 200 / 0.003秒。
- **未検証: POSTでの実行と `ai_analysis` 表への保存、prompt_version・入力指紋によるcache hit。** `.env` に `TICTOK_AI_ENABLED` が無く、`POST` は503（「AI機能が無効です」）で拒否されました。Fallbackせず503で止める挙動自体は方針どおりです。なお隔離環境の単体testでは cached=false→true→refresh→署名不一致→CASCADE削除まで通し確認済みですが、**実server上では未通過**です。
- 契約変更: GET 2本は保存済みを返すだけになりました。実行はPOSTのみ。

### F13: 運用log画面 — **完了（API範囲）**

- evidence: `GET /ops` 200。`GET /api/ops/events?limit=3` が実eventを返却（kind/duration_ms/detail/JOIN列付き）。kind_prefix・severity filter動作、該当なしは `{"events":[]}` 200。`GET /api/ops/kinds?hours=720` 200、`GET /api/ops/summary` → `{"counts":{"error":1,"warning":0,"info":54}}`。
- 制約: **画面の見た目は未確認。** 定期pollingなし（badgeのみ60秒間隔）。severity filterは完全一致のみ（「warning以上」は不可）。detail全文はtext logの案内のみで画面から検索できません。

### F20: 設定画面の整理 — **部分的**

- evidence(pass): `GET /api/settings` 200（57項目、category/default/default_source付き）。categoryの並びが全て連続（同じsection headerが二度出ない）ことを実測。`PUT /api/settings {"video_overlay_subtitles":true}` → 200 で反映され、**直後のプレビューに字幕が実際に描画された**（DB値が描画へ効いていることの実証）。
- **未確認: section header / 絞り込み / 既定値button のbrowser表示。**
- 制約: 焼き込みsectionが2つに分かれています（既存key順を変えない方針を優先）。「既定値へ戻す」は入力欄を書き換えるだけで保存はしません。

---

## 2. 追加された endpoint

### 新規
| endpoint | 用途 |
|---|---|
| `GET /api/jobs` | job台帳 + GPU現況 |
| `POST /api/jobs/{job_id}/cancel` / `retry` | 取り消し / 再実行 |
| `GET /jobs` | job画面 |
| `GET /ops` | 運用log画面 |
| `GET /api/ops/events` / `kinds` / `summary` | 運用log照会 |
| `GET /api/disk` | volume別空き容量 |
| `GET /api/storage/usage` / `POST /api/storage/scan` | 容量内訳 |
| `POST /api/storage/retention` | 保持policy（dry-run必須） |
| `POST /api/recordings/{id}/protect` | 保護flag |
| `DELETE /api/recordings/{id}/derived` | 派生物のみ削除 |
| `GET /api/recordings/{id}/transcript/export?format=srt\|vtt\|txt` | 字幕書き出し |
| `POST /api/recordings/{id}/preview/still?at=` / `GET .../still.png` | 静止画プレビュー |
| `POST /api/recordings/{id}/preview/clip` / `GET .../clip.mp4` | 動画プレビュー |
| `GET /api/recordings/{id}/clip-candidates` | 切り出し候補 |
| `POST /api/clips/batch` | clip一括書き出し |
| `POST /api/sessions/{id}/output` / `upscale-output` | session一括出力 |
| `GET /api/analytics/entry-source` / `battle-flow` / `coverage` | 新解析3本 |
| `POST /api/sessions/{id}/comment-analysis` / `POST /api/streamers/{id}/ai-review` | AI実行 |

### 契約変更（**既存呼び出しを壊す可能性あり**）
- `POST /api/recordings/{id}/{output,upscale-output,reprocess}` — 同期でfilenameを返す形をやめ、`{job_id, state:"pending"}` を即返し。出力file名は完了時のjob resultとWS `job_update` で届きます。
- `POST /api/sessions/{id}/{output,upscale-output}` — `group_id` を返却。
- `GET /api/sessions/{id}/comment-analysis` / `GET /api/streamers/{id}/ai-review` — **LLMを実行しなくなりました**。未分析なら `null` を200で返します。
- `POST /api/recordings/{id}/clip` — `variant` / `normalize_audio` を受付、応答に `variant` / `normalized` / `output_duration_seconds` を追加。

---

## 3. 追加された設定項目（計 +15 でSETTING_DEFS 57件 / env専用6件）

**画面設定(SETTING_DEFS)**
`disk_min_free_gb`(20) / `retention_transient_hours`(24) / `retention_derived_days`(0=無効) / `retention_source_enabled`(0=無効) / `retention_source_days`(0) / `retention_free_target_gb`(0) / `video_overlay_subtitles`(0=OFF) / `video_overlay_subtitle_font_size`(26) / `video_overlay_subtitle_position_percent`(58) / `video_overlay_preview_seconds`(30) / `video_output_normalize_audio`(0=OFF) / `audio_normalize_lufs`(-14.0) / `audio_normalize_true_peak`(-1.5) / `audio_normalize_bitrate_kbps`(192) / `clip_normalize_audio`(0) / `clip_pad_before_seconds`(8) / `clip_pad_after_seconds`(5) / `clip_candidate_window_seconds`(30) / `clip_candidate_zscore`(2.0) / `clip_candidate_lead_seconds`(10) / `clip_candidate_limit`(20)

**env専用**
`TICTOK_GPU_CONCURRENCY`(1) / `TICTOK_GPU_WAIT_TIMEOUT_SECONDS`(0=無制限) / `TICTOK_JOB_RETENTION_SECONDS`(300) / `TICTOK_MEDIA_QUEUE_POLL_SECONDS`(5.0) / `TICTOK_MEDIA_JOB_HISTORY_DAYS`(14) / `TICTOK_CLIP_DURATION_TOLERANCE_SECONDS`(1.0) / `TICTOK_OPS_BADGE_WINDOW_HOURS`(24) / **`TICTOK_NO_RESTORE`**（新設・監視復元を止める。検証時の実配信接続を防ぐ）

---

## 4. DB変更

**新表(3)**
- `storage_scan` — id=1固定の容量走査cache。FKなし。
- `media_job_queue` — 永続job queue。`recording_id` / `session_id` とも **ON DELETE CASCADE**。後から `params_json` 列を追加。
- `ai_analysis` — PK=(kind, target_type, target_id)。`session_id` は sessions ON DELETE CASCADE、配信者対象行はNULL。

**列追加(12)**
- `recordings.protected` (INTEGER DEFAULT 0)
- `sessions.live_create_time` (REAL) / `sessions.conn_instrumentation` (INTEGER)
- `events` に8列: `enter_source` / `enter_type` / `enter_reason` / `follow_status` / `follower_count` / `is_subscriber` / `is_moderator` / `is_gift_giver`（events表は22列→30列）

静的検査で「live tictok.db と fresh schema の表・列差分: 26表完全一致、欠落0」を確認済みです。

**重要な意味論**: events の `NULL` は「計装前＝未計測」、`'unknown'` は「届いた上で空だった」で**別物**です。同一視すると被覆率が出せなくなります。`conn_instrumentation` がNULLのsessionは「切断が無かった」ではなく「記録されていない」であり、遡って埋めてはいけません。

---

## 5. userが次にやるべきこと

### 手動確認が必要（今すぐできる）
1. **全画面のbrowser目視** — 未確認です。優先度順:
   - `/jobs`（進捗bar・cancel/retry button・GPU現況）
   - `/ops`（一覧・詳細展開・設定変更diff・navのerror badge）
   - 設定画面（section header・絞り込み・「既定値へ戻す」・容量内訳card・保持policy card・プレビューcard）
   - analytics の新3card（②' 流入元 / ⑩ Battle展開 / ⑪ カバレッジ）
   - 履歴画面の追加button（派生物削除・保護・字幕書き出し3種）
2. **`TICTOK_AI_ENABLED=1` を設定してAI分析を実行** — POST実行・保存・再分析(refresh)・cache hitが実serverで未検証です。
3. **`DELETE /api/recordings/{id}/derived` を捨ててよい録画1本で試す** — 破壊的なため未実行です。
4. **retention の実削除を dry-run 結果を見た上で1回試す** — 現在 transient 7件 / 3.9GB が検出されています。
5. **再mp4化(reprocess)の非同期化を1本で試す** — 元mp4を `_backup` へmoveするため未実行。実行中はcancel不可(409)という設計も未検証です。
6. **焼き込みの実出力を1本走らせる** — 字幕ON時の全尺mp4、および音量正規化ONでの焼き込み/Up出力はend-to-end未検証です。**既存の `.overlay.mp4` は全件cache無効化されている**（signature v25 + OVERLAY_KEYS追加）ため、次の出力操作で再encodeになります。

### 実配信でしか確認できない
7. **F6の流入元計装が実際に埋まるか** — 16件の実サンプルは取れましたが、母数がまだ極小です。数配信ぶん貯めてから被覆率を再確認してください。
8. **`sessions.live_create_time` による収集開始遅延** — 現状は全session「計測不能」。新規収集分から埋まります。
9. **接続系markerによる欠測秒数** — `conn_instrumentation=1` のsessionが1件しかありません。
10. **F6が貯まった後に、organic入室の重み（ヒューリスティック定数）を実測labelへ置き換える作業** — これが§2-5の本命で、**まだ手を付けていません**。

---

## 6. 残課題（隠さず列挙）

### A. 構造的なもの
1. **`tictok.server` の import 副作用が残っています。** module levelでDB open → instance lock → `cleanup_stale_sessions()` まで走ります。`TICTOK_NO_RESTORE` が止めるのはlifespanの監視復元だけで、**import自体の副作用は対象外**です。lockを `cleanup_stale_sessions()` より前に置くのは意図的な設計（server.py:370）なので、lifespanへ移す改修は**user承認が必要**と判断して見送りました。現状、toolingから安全にimportするには `TICTOK_DB_PATH` の分離が必須です。
2. **STT(transcribe_queue)は media queue に統合していません。** GPU semaphoreでVRAM競合は潰れていますが、doc 3-1が指摘する「GPU排他の一元化」はこの点で未完成です。
3. **retention の自動実行(scheduler)はありません。** 手動dry-run→確認でのみ削除されます（無人で消える経路を作らない判断）。

### B. 未検証のまま残った範囲
4. AI分析の実行・永続化 / 再mp4化 / 容量不足507 / derived削除の成功path / 全画面のbrowser目視 / 焼き込み・Up出力の正規化end-to-end / 字幕付き全尺mp4の目視。

### C. 実DBへの副作用（発生済み・要認識）
5. import検査の初回が既定DB path まで到達したため、**稼働中の実DBに対して `ai_analysis` 表のCREATEと `sessions.conn_instrumentation` のALTERが実行されました**。いずれも次回起動時に走るはずのmigrationが前倒しされただけで、既存行はNULL・データ損失はありませんが、稼働中DBへ書き込んだのは事実です。

### D. 挙動の不揃い・既知の限界
6. **実行中の再mp4化はcancelできません**（409で明示拒否。finalize pipelineに中断点が無いため）。
7. **preview/clip の「描くものが無い」はjob `failed` 着地**。still は409に揃えましたが、job経路はHTTP statusを持たないため未対応。
8. **cancel後 `stage` が「取り消し中…」のまま**残ります（stateは `cancelled` で正しい）。
9. **焼き込みcancelは即座には止まりません**（frame/process粒度）。修正後は1〜2秒まで短縮しましたが0ではありません。
10. **cancel時の中間file掃除は既存の失敗経路に相乗り**しています。今回 `.comments.mov` の巨大残骸は塞ぎましたが、既存経路が拾わない中間物があれば残ります。
11. **loudnormは単一pass**のため目標-14 LUFSに対し±3程度ばらつきます。
12. **字幕の低信頼segment gate（avg_logprob / no_speech_prob）は未実装** — 承認事項と判断して見送りました。誤認識もそのまま焼き込まれます。
13. **Battle勝敗判定が履歴画面と9戦食い違います**（end_time切り直しによる。解析側が正しく、履歴側の `battle.result` は直していません）。
14. **切断markerの全置換書き込みが O(n²)** — 実測nは数十で実害なしと判断しましたが差分INSERTにしていません。
15. **battle/collab marker は依然 maxlen=500 の共有deque**（接続系のみ分離）。
16. **設定画面の焼き込みsectionが2つに分かれています**（既存key順を保つ方針の帰結）。
17. `toybox/10_build_check.bat` は langgraph-studio/backend 用でTicTokを対象にしないため、**全batchで未実行**です。