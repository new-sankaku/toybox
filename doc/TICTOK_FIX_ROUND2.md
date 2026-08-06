# 作業報告: 画面目視検証 + 残課題修正

## 1. 画面目視で見つかった問題

前提として重要な点: 稼働中server(:8520)は**今回の修正前のcodeで動いている**ため、目視で見えた404の多くは「未反映」に起因します。UI固有のlayout問題とは切り分けが必要です。

### broken (機能不全)

**A. route自体が404 (稼働server未反映)**
- `/jobs`, `/ops` が404。`{"detail":"Not Found"}` が素のJSONで表示されるだけでTicTok UIが一切出ない
- header naviに「job」「運用log」tabが**表示されているのにlinkが切れている**
- 404のAPI: `/api/disk`, `/api/ops/*`(summary/events/kinds), `/api/storage/usage`, `/api/jobs`, `/api/gpu`, `/api/analytics/{entry-source,battle-flow,coverage}`

**B. API 404の波及 (全画面共通header)**
- 「空き容量: 取得失敗」(全画面)
- 「運用log ?」badge (`/api/ops/summary` 404)。※ 0件と誤認させない不明状態badgeとしては**正しく設計されている**

**C. UI固有 (server反映後も残ると思われる)**
- **settings: section headerが機能していない**。DOM上 `.s-section` は1個のみ、中身は空文字。36項目が録画→接続→Battle→動画化まで区切りなく連続表示される
- **history: 字幕書き出し3種(SRT/VTT/text)が可視領域から到達不能**。`#transcript-modal` 内にあるが `display:none` で実測 0x0px。開くtriggerは「文字起」button(押下禁止対象)のみ
- **history: 「プレビュー」buttonが存在しない**。DOM全体を「プレビュー」「preview」で検索して0件
- **history: job進捗UIが無い**。progress要素・job系classとも0件。ただし実行中jobが無いため「0件だから出ない」のか「機能が無い」のかは切り分け不能
- **jobs: GPU現況 `span#gpu-summary` が空**。DOM上は存在するがbounding box 0x0で画面に何も見えない
- **error表示が英語生文字列**。jobs/ops とも「Not Found」がそのまま赤字表示。周囲は全て日本語
- **「0件」と「取得失敗」が区別できない**。ops画面はtable本体が「該当する記録はありません。」(=0件)、その直下に別途「Not Found」が出て矛盾して見える

### layout

- **history: Session詳細modal ■録画の操作列が潰れている**。列幅336pxに7 buttonが並び、全label が2〜3行折返し(出力=32px, 派生物削除=56px 等)。列全体が圧迫され、`#676`→`#6/76`、file名・時間(`03:0/9:47`)まで途中改行して読めない。button 1個の録画中sessionでは正常表示のため、button数による圧迫と確定
- **history: Gift tableのコイン列が狭く金額が2行に割れる**(`342,99`+改行`2`)
- **history: 下部右カラム(Memo)が約750px空白のまま**で、左の録画tableを広げる余地が使われていない
- **settings: sticky見出し行がrowのcontrolを隠す**。scrollTop=1300で「配信開始時の自動録画」のradioが見出し行の裏に入る
- **settings: 容量内訳tableの列幅がdata 0件時に不揃い**(「中間file」が右端で見切れ寸前)
- **jobs: dropdownの項目名prefixが選択後に消える**。初期「状態: 実行中・待機中」→変更後「全て」。prefixが先頭optionのlabelにしか入っておらず、変更後はどちらが状態でどちらが種別か判別不能
- **analytics/jobs: 失敗cardの下に数百px単位の空白帯**が残る
- **URL routing**: `.html` 付きURL(`/history.html` 等)は全て404。実routeは拡張子なし

### cosmetic

- **settings: 説明文の参照先が画面に無い**。「『動画化: プレビュー動画の尺(秒)』の設定」→ 36項目に「プレビュー」を含む項目0件。保持policy cardの「上の設定に沿って」→ retention設定項目が見当たらない
- **history: 削除buttonだけtooltipが無い**(他6 buttonは全てtitle付き)。最も破壊的な操作なのに不統一
- **表記ゆれ**: 「取得率」「カバレッジ/録画カバレッジ」「計測不能」「判定不能」が混在。字幕は「SRT出力」「VTT出力」「text出力」で1つだけ小文字
- **history: 一覧load中(約1.2〜1.6秒)に「保存されたSessionがありません。」が確定的な空metaとして出る**。上部統計card(総Session 115)が既に埋まった状態で同時表示され矛盾する
- section header barに長い説明文が右端いっぱいまで詰め込まれている(jobs/ops/settings)

### ok (確認できた正常動作)

analytics既存card 11枚(①〜⑨)全て正常描画、history一覧115行の全列描画、settings絞り込み窓(36→7件)、jobs/ops filter barのlayout、AI無効時の理由明示。

---

## 2. 修正した項目と検証結果

### X1. 素通し録画への音量正規化
`video_overlay.py` / `core/settings.py`

描画対象0件の録画で `ensure_overlay` がsource素通し(ffmpeg不実行)になり `video_output_normalize_audio` が効かない問題を、`-c:v copy` + 音声のみ再encodeの経路(`_run_audio_only`)で解消。cache metaを2行形式(`<sig>\naudio-only`)へ拡張、Mode B起動判定を戻り値identityから `a_drew_nothing` flagへ変更。

**検証済み(実測)**: CFR/VFR両方の合成録画で映像streamのmd5がsourceと完全一致(真のstream copy)、LUFS -47.8→-14.0(設定default到達)、cache hitでbyte同一、ON→OFF切替でstale削除→素通し復帰。VFR素材にbeepを埋めてA/V同期ズレ0.0msを実測(前回未検証だった項目をカバー)。
**未検証**: 実録画(長尺・混在解像度)での動作。UIからの通し操作。

### X2. cancel後の表示不整合 / preview失敗の着地統一
`storage.py` / `record/media_queue.py` / `server.py` / `static/jobs.js`

(a) 終端SQL3箇所に `stage=''` を追加し「terminalな行のstageは常に空」を不変条件化。(b) `JobSkipped` 例外を新設し、preview/clipの「描くものが無い」をfailedではなくstate=`skipped`(「対象なし」badge, 失敗filter非該当)へ着地。

**検証済み(実測)**: cancel後 state=cancelled/stage=''、JobSkipped→state=skipped。隔離server(:8599)でHTTP通し確認 — `POST /api/recordings/9001/preview/clip` → skipped、対照9002 → completed、ops_eventsに `overlay_preview.job_skipped`(severity=info)1件・job_failed 0件。前回未検証だったend-to-endを今回実施。
**未検証**: browserでのjobs画面目視。`applyRecordingJob` はskippedを未対応のまま(現状overlay/upscale/reprocessはskipしないため実害なし)。

### X3. Battle勝敗判定の統一
`core/battle.py` 他 9 file

調査の結果、**指示文の前提と異なり「両側が別々に間違っていた」**。(a)解析側: 確定scoreが `end_time` の数百ms後に届く戦を `t<=end_time` 切りで取りこぼし(5戦)。(b)履歴側: PK後のroster解体で敵scoreが落ちた値を保存(4戦、うち2戦は0対0のdrawに潰れていた)。`BATTLE_SETTLE_GRACE_SECONDS=3.0` を導入し判定を `core/battle.py` へ単一化。**DBは書き換えず**読み出し3経路で `annotate_result` を適用、元値は `*_reported` に保持。

**検証済み(実データ)**: 実DBを再複製した460戦で不一致0件(修正前挙動を再構成すると**ちょうど9件を再現**)。`/api/analytics/battle-flow` の result_diff=4 とstorage読み出しが整合。
**未検証**: 画面目視。焼き込み再renderの実出力。

### X4. battle/collab markerのdeque溢れ
`collect/collector.py` / `storage.py`

原因は2つあった。(1) mask markerと同居し cap 500 を押し出す。(2) **より深刻**: `save_markers` が DELETE→INSERT の全置換で、dequeから溢れた既存DB行まで消し直していた。`linkmic_markers` 専用dequeへ分離+即時永続化、`append_markers`(差分INSERT)へ変更。

**検証済み(実測)**: cap 3倍(1500件)投入で実際に溢れを発生させ、in-memory/DB双方でbattle/collab生存を確認。旧設計を再現すると実際に消失することも確認。
**未検証**: 実配信での長時間動作(禁止事項)。simulation mode経由の実行。

---

## 3. 回帰

**既存機能の回帰は検出されませんでした。** 字幕書き出し(SRT/VTT/TXT)・clip正規化・静止画/動画プレビュー・Battle統計API・運用log API・容量APIを隔離server(:8599)で全て200確認。

ただし**新規に1件の不具合を発見**しました(今回の修正が作り込んだものではありません)。

**音量正規化した出力のsample rateが96kHzに上がる。** `audio_norm.encode_args()` のfilter chainで loudnorm が常に192kHzを出すため、後段aacが最寄りの96kHzを選ぶ。実測: 48000→96000、44100→96000(正規化OFFはsourceのまま)。実害は音声dataの肥大(bitrate 2倍)で音質向上は無し。**共有helperに元からあった欠陥**で clip出力・Up出力が既に同経路を通っており既存機能の回帰ではありませんが、今回「素通し録画にも正規化を掛ける」変更で焼き込み出力にも新たに波及しました。`audio_norm.py` 1箇所の修正(filter末尾に `,aresample=<rate>`)で3経路とも直ることを最小再現で実証済みです。

その他:
- 音声のみencode経路で尺が+0.1秒(AAC tail padding、定数)。beep位置ズレ0.0msでA/V同期に影響せず、回帰ではないと判断
- 前回報告の「判定が変わる戦は8件」は、解析対象402戦では**4件**。差は解析対象外57戦を含むか否かの母集団定義の違い。userへ提示する際は母集団を揃える必要があります

---

## 4. 残った課題

**即対応候補**
1. **稼働serverが古いcodeのまま** — 今回の修正は全て未反映。server再起動まで画面では確認できません
2. **sample rate 96kHz問題**(上記) — `audio_norm.py` 1箇所
3. **settings の section headerが空** — 目視で見つかった最も影響の大きいUI不具合
4. **history 操作列の折返し** — 7 button/336pxの構造的な狭さ。button集約かlayout変更が必要

**未検証で残っているもの**
- 実配信・長時間動作での確認(禁止事項のため全て未実施)
- browser目視での修正結果確認(server再起動不可のため)
- 実録画での preview/clip の NothingToDrawError 実発火(隔離環境の合成録画では確認済み)
- 焼き込み再renderの実mp4出力

**設計上の未対応(意図的)**
- 焼き込み設定を**全てOFF**にした場合は `_burn_in_recording` が早期returnし、依然として音量正規化が掛からない(別caseと判断し範囲外)
- 焼き込み signature 25→26により既存297録画の `.overlay.mp4` cacheが全件無効化される。実際に表示が変わるのは8戦を含む録画のみ。**再render costの許容可否はuser判断**
- `score_series` が空の古い12戦は確定判定不能で `basis=reported` のまま
- 過去にdequeから溢れて失われたmarkerは情報源が無く復元不能

**未commit** — 今回の変更は全てworking tree上にあります。