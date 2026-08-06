# TicTok 機能提案書

## 現状のTicTokがカバーしている範囲

TicTokは、TikTok LIVEのWebCast event（34種をsubscribe）をrealtimeで収集してSQLiteへ永続化し、Browser上で監視・履歴閲覧・配信者別プロファイル・配信者横断の統計解析（時間帯index、event-study、Gini集中度、グローブcrit率など12 panel）まで行うlocalhost常駐toolです。加えてHLS録画・混在解像度の正規化・Comment/Gift/Battle score barの焼き込み出力・AI超解像(Up出力)・ローカルSTT転写・FTS5全文検索(STT/comment)・clip切り出し・ローカルLLMによるcomment分析/配信者講評を備えます。設計方針としてFallback・捏造を禁じ、取得できない値は空のまま扱う姿勢が全体に徹底されています。

一方で、**貯めたdataを外へ出す出口**（字幕file、対戦単位のclip、音量正規化）、**長時間jobの運用可視性**（進捗のreload耐性、ops_eventsの閲覧手段、disk容量）、**AI結果の永続化**が欠けており、成果物へ到達するまでのコストと、無人常駐運用中の障害把握が現状の主なボトルネックです。

---

## ① 即やる価値が高い（既存dataで完結・工数小）

### 1-1. 字幕fileの書き出し（SRT / VTT / plain text）

転写済み録画から字幕fileをdownloadできるendpointとbuttonを転写viewerのheaderに追加します。segments_jsonの時刻は転写時にmedia軸へ再map済みのため、そのまま字幕timecodeへ落とせます。timemap_versionが古いtranscriptには書き出し前に警告を出します。

**なぜ価値があるか**: 転写結果の出口が現状DB閲覧しかなく、外部NLEでの仕上げ運用と完全に断絶しています。誤認識があってもsidecarなら外部で修正可能で、焼き込み（後述②）より先に出すべき順序です。先例（`GET /api/cutlist/export`）があり実装costが最小です。

**必要data**: 既存。transcripts(segments_json / language / timemap_version)。新規収集なし。

**想定変更file**: `tictok/server.py` / `static/history.js` / `static/history.html`

**工数**: S

> 注意: 出力timecodeは元録画mp4のmedia軸基準です。焼き込み出力・Up出力に対するPTS整合は保証しないため、UI文言に「元録画mp4基準」と明記してください。

---

### 1-2. clip切り出しの音量正規化と出力版選択

`make_clip` に `normalize_audio` と `variant`(source / overlay / upscaled) を追加します。音声のみ再encodeして `loudnorm` を適用し（映像は `-c:v copy` を維持）、切り出し元をsource/焼き込み済み/Up出力から選べるようにします。

**なぜ価値があるか**: 現状すべての映像経路が `-c:a copy` で、音量正規化の手段がcodebase全体に存在しません（loudnorm/dynaudnorm等grep 0件）。配信ごとに音量が大きくばらつくため、投稿前の最後の1ステップが毎回手作業になっています。variant解決logicは `server.py` に既存で、ほぼ追加codeゼロです。

**必要data**: 既存。録画mp4 / overlay mp4 / upscale mp4のみ。ffmpegで完結。

**想定変更file**: `tictok/media/clipper.py` / `tictok/server.py` / `tictok/core/settings.py` / `static/videos.js`

**工数**: S

> 注意: 録画はHLS由来のVFRです。`-c:v copy` + audio filterはsync崩れの温床なので `aresample=async=1` を併用し、出力尺が入力尺と一致することを検証してください。目標値はflat scalar設定2個（target LUFS / true peak）で足り、preset table等の新機構は不要です。

---

### 1-3. GPU排他の一元化と、映像jobの進捗喪失の解消

process内に散在するGPU lock（STT / Up出力 / avatar超解像 / 焼き込み）を、config駆動の共有semaphore（既定1）配下へ入れます。併せてserver側に薄いjob registry（job_id → domain / recording_id / pct）を置き、WS接続時にsnapshotをpushします。session単位の出力loopをbrowserからserverへ移します。

**なぜ価値があるか**: (a) avatar超解像のlockはUp出力とCUDA contextを共有するとcomment明記されながら別lockで、二重侵入が起こり得ます。(b) 焼き込みは出力path単位lockのみで全体上限がなく、複数録画へ投げるとGPU/diskを無秩序に奪い合います。(c) 進捗はclick時にclient側Mapへ登録する方式のため、reloadすると完了も失敗も永久に届きません。(d) session出力はbrowserのforループで直列実行しており、tabを閉じると残りの録画は起動すらされません。長時間job運用で最も実害の出る箇所です。

**必要data**: 既存。job管理のみでTikTok側data不要。

**想定変更file**: `tictok/core/gpu.py`(新規) / `tictok/core/config.py` / `tictok/record/transcription.py` / `tictok/record/upscale.py` / `tictok/media/avatar_upscale.py` / `tictok/record/video_overlay.py` / `tictok/server.py` / `static/history.js`

**工数**: S〜M

> 注意: 既存のper-key lockは「同一対象の二重render防止」として役割が違うので残します。LLM推論はHTTP client（OpenAI互換endpoint = 別process）なのでこのsemaphoreでは制御できません。AI server側のkeep_alive設定はServer Config fileへ出す別issueです。

---

### 1-4. 空き容量の可視化と、重いjobの実行gate

`disk_free_by_volume()` の結果を返すendpointを追加し、既存画面（overview または settings）にvolume別の空き/合計barを常時表示します。閾値割れ時はUp出力・焼き込みの開始を拒否します。

**なぜ価値があるか**: disk満杯は「焼き込みのPIL層が落ちてASS転落しアイコンが消える」という別bugの顔で実際に表面化しています。現状 `log_disk_preflight` も `_disk_ctx` も警告logを出すだけの純診断で、枯渇を止める機構がゼロです。既存の計測関数をそのまま使い、呼び出し点の戻り値をgateに使うだけで実害の大半を止められます。

**必要data**: 既存。`shutil.disk_usage`(record_dir / record_dir_final / db / log)。

**想定変更file**: `tictok/record/recorder.py` / `tictok/record/upscale.py` / `tictok/core/config.py` / `tictok/server.py` / `static/overview.js`

**工数**: S

> 注意: 閾値は既存log用の値を流用せず専用設定を新設してください（hard-code禁止）。

---

### 1-5. 焼き込み設定の静止画プレビュー

指定media PTSでffmpegからframeを1枚抜き、既存の描画planから該当時刻のPIL層のみを合成してpngを返します。encode・comment layer pipe・CFR prepassを一切通らないため秒で返ります。

**なぜ価値があるか**: 焼き込み関連の設定は13項目あるのに、効果を確認する手段が「1配信ぶん本出力する」しかなく、数十分〜数時間の待ちが挟まるため事実上チューニング不能です。font size / icon percent / avatar / comment delay / gift min diamonds といったチューニング需要の大半は静止画1枚で判断できます。

**必要data**: 既存。録画mp4 + 既存events。

**想定変更file**: `tictok/record/video_overlay.py` / `tictok/server.py` / `static/settings.js`

**工数**: S

> 注意: 動画プレビュー（尺を切ったmp4出力）は③へ回します。timing mapを分岐させると「プレビューでは正しいが本出力はdriftする」嘘のプレビューになるためです。

---

## ② 中期（新規収集や中規模実装が必要）

### 2-1. Battle展開の統計化（リード変動・終盤スナイプ・終盤集中度）

既に全Battle分が永続化されている `score_series` から、残り時間帯別の得点分布、リード交代回数、最終60秒での逆転有無、「残り1分リード時の勝率」、自陣得点が終盤集中型か平坦型かの類型を算出します。時間軸はTikTok server権威値である `end_time` を原点とする残り時間軸に統一します。

**なぜ価値があるか**: score_seriesはUIで折れ線を描くだけで統計として一切集約されておらず、勝率・平均スコアという結果指標はあっても「どういう勝ち方/負け方をしているか」が分かりません。実測でも指標は退化せず読める値になります（残り60秒リード209戦→勝利170戦、リード交代の中央値1、自陣最終scoreの34%が最後60秒に集中 ＝ 一様なら20%）。

**必要data**: 既存。battles.data_json(score_series / start_time / end_time / result / aborted)。追加購読不要。実DBで449 battles、最終score変化時刻とend_timeの差は中央値-1.4秒で、残り時間軸へのmappingは信頼できます。

**想定変更file**: `tictok/analytics.py` / `tictok/storage.py` / `tictok/server.py` / `static/analytics.js` / `static/streamers.js`

**工数**: M

> 制約: 449戦の内訳は1v1が169戦のみで、個人マルチ182・team 82です。`score_series.opp` は `max(opp_scores)` のためsample毎に相手が入れ替わるキメラ系列で、リード交代・相手得点相関はそのまま出すと無意味です。1v1とteam（計251戦）を母集団とし、個人マルチはparts[]から直近rivalの系列を再構成した場合のみ算出してください。「残り1分リード時の勝率」はWilson CI併記の記述統計とし、**戦術効果ではなく選択効果**である旨を注記します（「終盤温存が有効」という因果的な言い回しは使いません）。終盤集中度はglove critの寄与を差し引いた系列と生の系列の両方を出します。

---

### 2-2. Battle / コラボ窓を単位とした自動clip書き出し

battles の start/end、collab_windows の start/end を録画のtiming mapでmp4時間軸へ変換し、「1戦=1本」「1コラボ=1本」のclipを一括生成します。file名にbattle_id・相手・勝敗を埋めます。

**なぜ価値があるか**: Battleは本tool最大の差別化dataで、score bar焼き込みも実装済みなのに、成果物は「配信まるごと1本」しか出せません。実測で現存mp4内に完全に収まるbattleは379件、collab窓は232件ある一方、`_clips` dir配下の出力は**0本**です。手動UIは1戦ごとに時刻を手計算する必要があるため実質使われていません。部品（make_clip / build_time_mapper_sync / battles_for_session / clips_dir）は全て揃っており、純粋な配線です。

**必要data**: 既存。battles(start_time欠落0件 / end_time欠落4件=1%、result全件populated) / collab_windows(315件) / recordings / .timing.json。

**想定変更file**: `tictok/media/clipper.py` / `tictok/server.py` / `tictok/storage.py` / `static/history.js` / `static/videos.js`

**工数**: M

> 実装前に必ず補うべき点: (a) 前後padding（±5〜10秒）を仕様に含めること。stream copyはkeyframe単位（segment 2秒）でしか切れず、padding無しでは開始が欠けます。精度が要る場合に `precise=True` を選べるようUIへ露出させます。(b) recording単位の窓絞り込みを必須にすること（実測で10件のbattleがrecording境界を跨いでいます）。(c) end_time欠落の扱いを明示し、値を捏造しないこと。(d) clip labelは40文字上限のため命名layoutの再設計が要ります。(e) 素材の既定はsourceにします（overlay mp4は現存録画187本中32本のみ）。

---

### 2-3. 候補listからのclip一括書き出し（highlight候補 + 検索hit）

recording単位で「切り抜き候補」をランキング表示し、検索結果と併せて複数区間をmulti-selectして一括切り出しできるようにします。検出は既存 `streamer_highlights` のspike判定を共通関数へ切り出してrecording窓版と共用します。

**なぜ価値があるか**: 現状 `/clip` は1区間1回のPOSTで、10件の見せ場を抜くのに10往復の手作業が要ります。時刻listはsearch_hits(video_time付き)として既に整っており、束ねる層が無いだけです。heat barによる目視導線は既にあるため、増分は「ソート済みlistからの選択」と「往復回数の削減」に限定されますが、成果物への到達コストは実際に下がります。

**必要data**: 既存。buckets / events(gift・comment) / search_hits。新規購読不要。

**想定変更file**: `tictok/storage.py` / `tictok/server.py` / `static/videos.js` / `static/videos.html`

**工数**: M

> 制約: 「秒次密度」は不可能です。bucketsはbucket_seconds粒度（既定10秒、session単位可変）なので、rolling窓は「bucket個数」ではなく「秒」で定義し、各sessionのbucket_secondsから窓内bucket数を導出してsession間の可比性を保ってください。検出器を2系統に増やすと既存highlightと食い違うため、必ず判定を共通化します。入力はdiamondsとcommentsのみ（joinsは純増でなく交絡、viewersはbuckets列に既存で重複）。候補開始点の前方shiftは「反応より出来事が先行するためのlead秒」としてConfig化します（「コメント遅延補正」ではありません。PTS変換側で既に解消済みです）。search_hitsのcomment hitはend_timeがNULLなのでpre/post padding設計が必須。**concat結合（ダイジェスト）と「一括切り出しボタン」は範囲外**とします（spikeは単発高額giftに支配されるため成果物の大半がゴミclipになり、diskを食います）。preciseは分単位かかるためbatchはbackground job化が必要です。

---

### 2-4. STT字幕の焼き込み（default OFF）

①-1のsidecarに続き、segmentsからASS字幕を生成して既存の焼き込みfilter graphへ合成する設定 `video_overlay_subtitles` を追加します。

**なぜ価値があるか**: 字幕はTikTok Live切り抜きで事実上必須の要素で、現状「字幕付きmp4」を出す手段がありません。Windows command line 32KB問題は `-filter_complex_script` で既に回避済みのため、filter追加自体は障害になりません。

**必要data**: 既存。transcripts(segments_json)。焼き込みMode Aが使う元mp4のPTS軸と同一のため、wall-clock変換は不要です。

**想定変更file**: `tictok/record/video_overlay.py` / `tictok/core/settings.py` / `tictok/server.py` / `static/history.js`

**工数**: M

> 必須条件: (a) `_signature()` の入力にtranscript fingerprint（segments hash + timemap_version）を含めること。含めないと転写後の再焼きがcache hitで無視されます（v23 per-recording windowと同型の踏み抜き）。(b) 字幕は既存Comment feed / score barと座標帯を分離し、位置とfont sizeをsettings化（固定座標のhard-code禁止）。(c) 転写未作成のrecordingは字幕なしで焼かず、UIで未完を明示。
> 承認事項: 現在のsegmentsは `{start,end,text}` のみで `avg_logprob` / `no_speech_prob` を持たず、低信頼segmentをgateできません。誤字幕を恒久的にmp4へ焼き込むのを避けるなら、先にこの2値を保存する小改修（既存transcriptは再転写要）を入れるかをご判断ください。

---

### 2-5. 入室の流入元と視聴者のfollow関係の収集

既に届いているのに読んでいないfieldを追加取得し、events表へpoint-in-time snapshotとして保存します。対象は実測で到達を確認できたものに限定します。

- JoinEventの `client_enter_source`(58/58で13種の実値) / `client_enter_type`(41/58) / `client_live_reason`(8/58)
- Comment/Giftの `payload.userIdentity`: isFollowerOfAnchor / isMutualFollowingWithAnchor / isSubscriberOfAnchor / isModeratorOfAnchor / isGiftGiverOfAnchor
- JoinEvent / LikeEvent 限定の `user.follow_info`(followStatus / followerCount)

**なぜ価値があるか**: (a) ①' organic入室推定は現在 base0.15＋再訪0.45＋engaged0.30＋Lv0.10 という名前付き定数のヒューリスティックweightに依存しており、提案書自身が捏造疑いと注記しています。`clientEnterSource` を discovery / referred / incentivized / unknown へ分類すれば、この定数を実測labelへ置換できます。特に `ug_task_page`（報酬task誘導）は§15が除去対象とするノイズ流入そのもので、現状は完全に不可視です。(b) ⑦入室の質は `users.first_seen` による「TicTokが観測したことがあるか」でしかなく、「配信者をfollowしているか」とは別物です。userIdentityを持てばこの2つを分離できます。(c) moderator除外・subscriber判定の正規の源もuserIdentityです。

**必要data**: 既存購読eventのfield追加読みのみ。新規subscribe不要、追加fetch不要、sign消費ゼロ。

**想定変更file**: `tictok/collect/collector.py` / `tictok/storage.py` / `tictok/analytics.py` / `tictok/server.py` / `static/analytics.js` / `static/common.js`

**工数**: M

> 実測で除外したfield: `enter_type` / `user_share_type` / `is_top_user` / `rank_score` / `top_user_no` / `is_follower` / `is_following` / `anchor_level` / `user_role` / `is_verified` は全sampleで0 hit（protobufはdefaultを省くため「常に空」）。`action` は全件1の定数。**share経由入室の直接attributionは `user_share_type` が空のため成立しません**。③ share-upliftは従来通りplacebo対照による間接推定を維持します。ShareEvent / FollowEvent は follow_info が完全に不在です。
> 設計上の必須事項: followStatus不在は「非follower」と「未送出」が区別できません。`following / mutual / not_following / unknown` の4値で持ち、followInfo dictごと不在は unknown とします（非followerに丸めない）。既存行はNULLになるため、「流入元不明」を独立カテゴリとしてUIに別掲し、organic_ratioの分母は既知分のみ、被覆率を併記します。CACHE_VERSIONS を+1し、storageのbatch writer経路（読み取り前flush）も追従させます。samplesはshape dedup済みで値の頻度が実勢比率ではないため、構成比の事前見積りには使わないでください。

---

### 2-6. 削除済みcommentの追随（ImDeleteEvent）

未購読の `ImDeleteEvent`(delete_msg_ids / delete_user_ids) を購読し、events表へ `deleted` flagを立てる方式（物理削除しない）とします。FTS index・AI分析・焼き込みの対象から除外します。

**なぜ価値があるか**: TicTokはcommentを無期限に保存し、FTS indexへ載せ、動画へ焼き込みます。TikTok側でmoderator削除されたcommentを保持し続けると、FTS/AI分析の母数が汚染され、削除済み発言が焼き込み済みmp4に残ります。突合に必要な `baseMessage.messageId` が実サンプルで埋まっていることは確認済みです。

**必要data**: 新規subscribe（ImDeleteEventのみ）。CommentEvent側の message_id 保存もセットで必要です。

**想定変更file**: `tictok/collect/collector.py` / `tictok/storage.py` / `tictok/search/indexer.py` / `tictok/record/video_overlay.py`

**工数**: Phase 0 = S、Phase 1 = M

> **Phase 0（必須gate）**: samplerに `ImDeleteEvent` を追加するだけの診断購読を行い、実配信で発火有無・頻度・実値を実測してください。匿名接続にImDeleteが届くかの実測はまだ存在せず（samplerが未購読なのでsamples/に無いのは当然で、無いことの証拠になりません）、TikTokのmoderationの多くはdispatch前のserver側filterでそもそも受信しません。発火が確認できなければPhase 1へ進まず打ち切りです。
> Phase 1の注意: `_events_fingerprint` に deleted を含めないと、既に焼き込み済みのcacheが更新されず削除追随が反映されません。既存commentはmessage_idを持たないため、msg_id経路は前方互換のみ（遡及適用はdelete_user_ids経路に限られます）。
> なお当初案にあった MessageDetectEvent / UnauthorizedMemberEvent / RoomVerifyEvent / AccessControlEvent は、それぞれ接続遅延計測の設定配布・nickname非表示member通知・anchor向け警告・sign層challengeであり、moderationでもrestricted判定の補強でもないため対象から外します。

---

### 2-7. 運用ログ画面（ops_events viewer）

ops_events表を時系列で閲覧する専用page（/ops）を追加します。severity / kind前方一致 / 配信者 / 期間 / job_idでfilterし、detail(JSON)を展開表示します。errorの直近件数をheader navにbadge表示します。設定変更履歴（`process.settings_updated` の旧値→新値diff）も同endpointで表示します。

**なぜ価値があるか**: `storage.list_ops_events()` は実装済みなのに**呼び出し元がゼロ**（dead code）で、HTTP endpointも画面もありません。録画失敗（validation_failed / concat_failed / empty_finalized、detailにvolume空き容量とffmpeg stderr付き）、接続断・再接続、設定変更diff、job開始完了が全てDBに貯まっているのに、userはtext logをgrepするしか手段がありません。無人常駐監視toolとして「昨夜なにが壊れたか」を答えられないのは運用体験上の最大の穴です。設定変更については、焼き込み品質のように設定で結果が大きく変わる項目が多いため「いつどの値からどの値へ変えたか」を辿れる価値が固有にあります。

**必要data**: 既存。ops_events（保持180日）。新規購読不要。

**想定変更file**: `tictok/server.py` / `tictok/storage.py`(filter拡張) / `static/ops.html` / `static/ops.js` / `static/common.js` / `static/style.css` / nav追加のため既存8 htmlファイル

**工数**: M

> 前提の修正: 「list_ops_eventsをそのまま公開するだけ」は誤りです。現行実装は `kind = ?` の完全一致のみで、kind前方一致・until・offsetのいずれも未実装です（前方一致はLIKE+ESCAPE、ページングはkeyset推奨）。navは8 htmlにhard-codeされているため一括編集が要ります。detailは4000字でtruncateされ得るので、全文はtext log側にある導線を示してください。header badgeはCOUNT(*)を返す軽量endpointを別に立てます（DB照会失敗を0件として握り潰さないこと）。session削除後の行も残る設計なので、session_unique_idがNULLのケースを正しく描画してください。

---

### 2-8. AI分析結果の永続化とcache

`ai_analysis(kind, target_type, target_id, model, prompt_version, input_signature, payload_json, computed_at)` を新設し、comment分析・配信者reviewの結果を保存します。`analytics_session_cache` と同型のversion運用で、model / prompt_version / input_signature のいずれかが不一致のときだけ再実行します。

**なぜ価値があるか**: `ai_analysis.py` はstorageをimportすらしておらず、画面を開くたびにLLMを直接叩きます。ローカル量子化modelで毎回数十秒を払う構造は実用性を削ぎ、結果が残らないため分析日時すら分かりません。他のAI活用すべての前提になるenablerです。

**必要data**: 既存。events.comment / streamer profile集約（server側で構築済み）。新規購読不要。

**想定変更file**: `tictok/storage.py` / `tictok/ai/ai_analysis.py` / `tictok/server.py` / `static/history.js` / `static/streamers.js`

**工数**: M

> 必須の設計制約: 再計算契機は**明示要求時のみ**とし、既存の `_ensure_analytics_cache_locked` のような「未計算session全件をその場で一括計算」は絶対に実装しないでください（server起動/初回accessで数十秒×session数のLLM実行が走り事実上停止します）。session対象の行は `sessions(id) ON DELETE CASCADE` で孤児化を防ぎます。APIのresponseに computed_at / model / prompt_version / cached を含め、画面に「分析日時」と明示的な『再分析』ボタンを出すところまでが完成形です。
> **「前回の雰囲気との差分」「topic推移」は今回のscopeから外します**。現在のcomment samplingは直近N件の末尾sampleで配信長の違うsession間の母集団が別物になること、topic labelがfree textで正規化層なしには横断集計できないこと、sentiment%のnoise floor（同一入力の再実行差）が未測定であることの3点が未解決で、このまま差分を出すとmodel noiseをsignalとして表示することになります。

---

### 2-9. 横断検索へのgift source追加と配信者別hit件数

search sourceに gift（gift名）を追加し、既存 `index_comments` と同一のmapper経路でrecording窓のgift eventをvideo_timeへ変換して search_hits へ投入します。併せて配信者別hit件数を検索responseへ追加し、since/untilの日付入力をtoolbarへ露出させます。

**なぜ価値があるか**: 「あのギフトを誰がいつ投げた場面」という最頻の探し方がscene検索から漏れています（sourceはstt/commentの2種のみ）。session詳細のgift rankingは集計のみで「その瞬間へseek」はできません。giftはstreaking除外済みで1 gift=1行のため量も妥当です。

**必要data**: 既存。events(kind='gift', gift_name, user_nickname, time)。新規購読不要。

**想定変更file**: `tictok/search/indexer.py` / `tictok/storage.py` / `tictok/server.py` / `static/videos.js` / `static/videos.html`

**工数**: M

> 設計上の注意: bodyにはgift_nameのみを入れ、送り主は既存の nickname 列へ入れてcommentと意味論を揃えてください（giftだけbodyに人名を混ぜると、同一人名queryがgiftでは当たりcommentでは当たらない非一貫な挙動になります）。既存録画向けにbackfillの起動時実行が必要です。facetは新UI部品を作らず既存の配信者dropdownのラベルへ件数を併記し、毎打鍵で走るためreset時(offset=0)のみ返します。
> **「配信者note」の検索対象化は不採用**です。実体はsessions.noteで、search_hitsは recording_id / video_time が NOT NULL のため録画にもseek先にも紐づきません。必要ならhistory画面のsession filterとして別途実装してください。日付ヒストグラムとCSVは後回しで足ります。

---

### 2-10. 設定画面のsection化と既定値復元

36項目のflat tableに非折りたたみのsticky section header（収集/接続・録画・焼き込みoverlay・診断/sample）を差し込み、各項目に「既定値へ戻す」を置きます。項目名・note全文へのincremental filter窓を上乗せします。

**なぜ価値があるか**: 現状は全項目を1枚のtableへ縦に並べるだけで、目的の項目に辿り着くまでscrollが必要です。既存のkey順は既に論理clusterに並んでいるため、順序を変えずにheaderを差し込むだけで済みます。

**必要data**: 既存。SETTING_DEFS の `describe()` に category / default / default_source を追加するのみ。

**想定変更file**: `tictok/core/settings.py` / `tictok/server.py` / `static/settings.js` / `static/settings.html`

**工数**: M

> 注意: **折りたたみ（collapse）は採用しません**。1枚のflat pageならbrowserのCtrl+Fが既にlabel/note全文へのincremental filterとして機能しており、畳むとそれを自ら壊すことになります。filter窓はCtrl+Fの代替ではなく上乗せの位置づけです。
> 「既定値へ戻す」の default は built-in と 環境変数由来の2種があるため、`default` と `default_source`("builtin"/"env") の両方を返し、UIに「環境変数で上書き中」を表示してください（片方だけ返すとenv運用時に嘘の既定値を提示することになります）。変更履歴は2-7のops_events viewerと同じ汎用endpointを使います。なお本toolは無認証の単一operator toolでactor列も存在しないため、「誰が変えたか」は原理的に記録できません（表示は 時刻・項目・旧値→新値 の3点）。

---

## ③ 大物（録画 / AI / 大規模）

### 3-1. 映像jobのDB永続queueとジョブセンター

`media_job_queue` 表を新設し、焼き込み・Up出力・再mp4化・clipを転写と同格のjob queueへ載せます。優先度・state(pending/running/done/failed)・再起動跨ぎの復元を持ち、実行中・待機中・過去のjobを1画面に並べるpageから再実行・cancel・出力fileを開く導線を提供します。ops_eventsの `{domain}.job_*` を job_id でgroupして過去履歴とします。

**なぜ価値があるか**: ①-3で「進捗が消える」「GPUを奪い合う」は解消できますが、process再起動をまたいだ**投入意図の永続化**とcancelは残ります。長時間job（1配信の焼き込み＋超解像で実時間の数倍）を回す運用では、投げた処理の全体像が見える価値が大きくなります。

**必要data**: 既存。recordings / ops_events(job_id・duration_ms付きで記録済み) / 既存ProgressCb。

**想定変更file**: `tictok/record/transcribe_queue.py` / `tictok/storage.py` / `tictok/server.py` / `static/jobs.html` / `static/jobs.js` / `static/history.js`

**工数**: L

> なぜ大物か: 4 endpointが同期でfilename/output_pathを返す契約をUIが使っており、非同期化は `history.js` の大規模改修を伴います。再mp4化はmp4を `_backup/` へ退避済みでcrashするとrestore経路が失われるため、単純なpending復帰では不十分で個別のrecovery設計が要ります。cancelは全domainで未実装で、ffmpeg subprocess終了＋部分fileの後始末＋spandrel loop中断の新規配線が必要です。また `transcribe_queue` を同一workerへ畳み込まない限り、GPU排他の一元化は完成しません（①-3のsemaphoreで実害は先に潰せます）。

---

### 3-2. 容量内訳の可視化とretention policy

Phase A: layoutのsidecar規約に沿ったfilesystem走査で、配信者別・種別別（source / overlay / up / cfrbase+comments.mov / ts / avatar cache）のbytesを集計し、結果をDBへcacheして表示します。Phase B: 保持ルール（日数・volume別上限・最小空き）を設定化し、dry-run結果をops_eventsとUIへ残す方式で削除を実行します。

**なぜ価値があるか**: 無人常駐録画＋超解像＋CFR base＋comment layerと中間生成物が多層で膨らむのに、削除policy・容量管理は一切ありません。①-4のgateで枯渇は止まりますが、「何が容量を食っているか」「何を消せるか」は依然として見えません。

**必要data**: 既存。ただし `recordings.bytes` は**mp4本体のみ**で、overlay/upscale/CFR base/timing/HLS/avatar cacheはDB未記録のため、種別別内訳にはfilesystem走査が必須です。

**想定変更file**: `tictok/record/recorder.py` / `tictok/core/settings.py` / `tictok/server.py` / `tictok/storage.py` / FS走査module(新規) / `static/settings.js` / `static/history.js`

**工数**: L

> **設計上の決定的な注意**: 「古い生録画を優先削除」「出力済みで元mp4が不要」は**順序が逆**です。source mp4は唯一の再取得不能資産で、overlay / up / cfrbase / comments.mov はsourceとeventから再生成可能な派生物です。sourceを消すと reprocess・再output・transcribe・clip・heat が全て復旧不能になります。削除順序は (1)孤児transient(crashed renderが残したCFR base) → (2)再生成可能な派生物 → (3)生録画 とし、生録画の自動削除は既定OFF・dry-run必須・保護flagで除外します。「転写済みで再利用予定が薄い」等の主観scoreは実装せず、並べ替えはsize/最終更新のみにします（根拠のないscoreの提示は捏造に近くなります）。
> HDD走査は数TB規模で数十秒〜分単位になるため同期API化は不可で、to_thread＋cache＋手動再scanが必須です。record_dir(SSD)/record_dir_final(HDD)の2 volume構成のため閾値はvolume別に定義します。削除実体は既存のcleanup関数を再利用し、新規の削除経路を作らないでください。既存のDELETE endpointはsourceごと消すため、派生物だけ消す新endpointが要ります。

---

### 3-3. 収集カバレッジ・欠測のメタ解析

Phase 1（collector計装の修復）: 全切断でmarker + ops_eventを発行し、planned/unplannedを区別。reconnectにもops_eventを追加。接続系markerをdriver markerと別deque化するか中間永続化してcrash耐性を持たせる。room_infoの `create_time` をsessionsへ永続化。Phase 2（解析panel）: 収集開始遅延、切断による欠測秒数、viewer_samplesの中央sampling間隔とp95欠測窓、録画カバレッジ率、STT済み率を集計するkind="coverage"を追加。

**なぜ価値があるか**: 全体解析は母数chipこそ出しますが「そのdataがどれだけ穴だらけか」を示しません。切断中のjoin/giftは丸ごと欠落し、event-studyのbaselineや⑤driftを静かに歪めます。結論の信頼度を読者が自分で割り引けるようにする投資で、Fallback禁止・捏造回避の方針とも整合します。

**必要data**: 既存表（markers / viewer_samples / recordings / transcripts / ops_events）ですが、**現状のDBでは切断欠測を復元できません**（後述）。

**想定変更file**: `tictok/collect/collector.py` / `tictok/analytics.py` / `tictok/storage.py` / `tictok/server.py` / `static/analytics.js` / `static/analytics.html`

**工数**: L

> なぜ「既存資産だけで足りる」ではないか: `_on_disconnect` は `self.state == STATE_CONNECTED and self._stop_requested` の内側でしかmarkerを発行しません。つまり**予期しない切断＝測りたい唯一のケースでmarkerが残らず**、reconnect markerだけが対の無い状態で孤立します。さらにmarkersは `deque(maxlen=500)` で、refractory 60sのportal/envelope markerが長時間sessionでは接続系markerを押し出し、永続化はfinalize時の一括置換のみなのでcrash時は全損です。したがってcollectorの計装修復が前提条件になります。
> また「接続時 total_user と joins累計の乖離」は開始遅延の指標になりません（joinは配信側がthrottleするため、差分は取りこぼし量に支配されます）。正しい源はroom_infoの `create_time` で、現状は取得しているのにstream URL抽出にしか使われていません。
> **最重要**: Phase 1以前の既存sessionは接続系markerを持たないため、欠測秒数を0と表示してはいけません（存在しない健全性の提示になり、方針に正面から反します）。data源が無いsessionは「計測不能」として別掲し、指標ごとに対象session数のchipを個別に出してください。録画カバレッジ率・STT率・sampling間隔の3指標は旧sessionでも正しく出ます。

---

### 3-4. 焼き込み設定の動画プレビュー（尺を切ったmp4出力）

①-5の静止画で判断できないencode品質・codec・score bar hold・gift秒数のために、media PTS窓を指定して数十秒だけを実解像度で焼き込むプレビュー出力を追加します。

**なぜ価値があるか**: 13項目の焼き込み設定のうち、静止画で判断できないものが残ります。costの支配要因は解像度ではなく尺なので、30秒に切れば約100分の1のcostで、quality/codecを含めて初めて評価可能になります。

**必要data**: 既存。録画mp4 + 既存events。

**想定変更file**: `tictok/record/video_overlay.py` / `tictok/server.py` / `tictok/core/settings.py` / `static/settings.js`

**工数**: L

> なぜ大物か: 「ensure_overlayに窓指定を追加するだけ」では済みません。窓を効かせるべきは comment layer render（全frameをPIL描画してqtrle pipeへ、CPU律速）・CFR prepass（全尺CFR base、数GB）・本encodeの**3箇所すべて**で、1つでも全尺のままなら本出力とcostが変わらず提案価値が消えます。
> **最大の危険**: プレビューが本出力と別のtiming mapを通ると「プレビューでは正しいが本出力はdriftする」嘘のプレビューになり、無いより有害です。timing map構築は絶対に分岐させず、全尺のまま組んだ出力に対してmedia PTS窓でfilterと平行移動をかけるだけにしてください。cacheはprevie専用sidecar・専用lock key・専用job kindで本出力と物理的に分離し、本出力のcache hit判定へ一切影響させないこと。窓の開始時刻はuser入力ではなくevent密度で自動選定します（無指定の30秒ではgift秒数・min diamonds・score bar holdが空振りします）。「低解像度」は自己矛盾なので撤回し（quality/codecはencode artifact自体なので低解像度では検証不能）、costは尺で落とします。

---

### 3-5. 配信の比較ビュー（複数sessionの重ね合わせ）

履歴一覧から2件のsessionを選び、経過時間を揃えたtimelineへ重ねて描画する比較画面を新設します。指標を切り替え、Battle窓をchart下部の細帯laneとして並べ、KPIを横並びの表で差分表示します。

**なぜ価値があるか**: 現状の比較は配信者profileの「今回/前回/平均/自己Best」という数値4列止まりで、時系列の形（立ち上がりが早い/後半に伸びる/Battleで跳ねた）を並べて見る手段がありません。時間帯heatmapは横断集計なので個別配信の形は分かりません。

**必要data**: 既存。buckets表(gifts/diamonds/comments/likes/joins/follows/shares/viewers)、battles、markers。

**想定変更file**: `tictok/server.py` / `static/compare.html`(新規) / `static/compare.js`(新規) / `static/common.js` / `static/history.html` / `static/style.css` / 全画面のnav

**工数**: L

> なぜ大物か: 「chart基盤が既にあるため素直に載る」は成立しません。`createTimelineChart` はpanel毎にdatasetが1本固定、x軸が絶対時刻、marker/band pluginが単一session前提のclosure変数に閉じており、Battle帯は全高塗り・marker縦線も全高で、複数系列を重ねると判読不能です。実質は新規chart moduleの書き起こしです。加えて `bucket_seconds` はsession毎の列なので、共通gridへの再sampling処理が別途要ります（sum系はsum、viewersはlast）。正規化はBackendの専用軽量endpointへ寄せてください（`/api/sessions/{id}` の4回呼びは重すぎます）。
> 位置づけ: まず2件比較・指標1つずつ切替に限定し、4件同時＋lane描画は第2段とします。経過時間軸は切断/再接続の空白を含む実時間であり稼働時間ではない旨を明記し、機能の位置づけは「個別配信の推移を並べて振り返る（因果判断は全体解析を参照）」とします。全体解析のevent-study（95%CI＋placebo対照）が「何が跳ねたか」に統計的に答える設計なので、n=2の目視比較を因果の当たり付けと称すると誤読を誘発します。

---

## 調査した結果、実現不可・低価値として却下したもの

### A. 取得できないdataに依存していたもの（実現不可）

| 候補 | 却下理由 |
|---|---|
| Rank系event（RankUpdate / RankText / HourlyRank / WeeklyRank）のDB化 | proto定義を実測した結果、順位数値を持つeventが存在しません。tab_infoはランキングUIのtab構成、winnersは受賞者IDとbadge assetのみ。唯一indexを持つRankTextEventは「視聴者のroom内top-N順位」であって配信者の時間別順位ではありません。実装するとUI構成の誤読から順位を捏造することになります。 |
| 入室→初コメント→初giftのファネル転換率 | 実測で、commentした人の38〜69%に先行するjoin eventが存在しません（配信開始30分以降に限定しても改善せず）。MemberMessageは部分配信で、算出される「転換率」は実質「join event配信率」を測っている状態です。欠落が無作為である保証もありません。 |
| Bonus Mission達成率と収支分析 | settle受信済み251件のうち未達成が**0件**（unset enumが0=SUCCEEDと同一視される実装artifact）。target_typeは284件中257件がNULL、contributorsは0〜6名、progressの単位はcoinではなく、貢献者countはmessage受信回数です。達成率も集中度も構成できません。 |
| 配信スケジュール規則性と成果の関係 | sessions行は「配信」ではなく「collector接続segment」で、1本の配信がgap 0.1〜5分の再接続で多数に分裂します。started_atは配信開始時刻ではありません。また「配信していない」と「監視していなかった」が区別できず、配信間隔・連続配信日数は監視稼働率と完全に交絡します。 |
| 配信状態event（Control / LivePause / LiveUnpause / StreamStatus / RoomStreamAdaptation） | RoomStreamAdaptationは解像度signalではなく被写体のフレーム内位置情報で、width/heightを持ちません（提案の中核根拠が不成立）。LiveUnpauseはpinned版libのbugで永久に発火しません。punish_infoは実サンプル0件です。 |

### B. dataは取れるが、実dataでは指標が成立しないもの

| 候補 | 却下理由 |
|---|---|
| Gifter RFM/LTV・離反予測(GBDT) | distinct gifter 1,173人中856人(73%)がF=1の単発。coin構成比はtop20で79%、配信者別では実質3〜8人で目視可能な規模です。segment遷移matrixは履歴1か月では作れず、R（最終giftからの経過日）は配信cadence（最大gap 3〜5日）と交絡して「配信者が休むと全員がAt-Riskに落ちる」検出器になります。 |
| SocialEvent.follow_count による follower総数の時系列化 | follow eventはsession中央値3件、26%のsessionで0件。かつ値は単調増加せず±20程度の揺れがあり（sharded counter由来）、1配信あたりのgross followが3〜42件なのでSNR<1。純増の符号すら保証できません。 |
| リーグ帯別ベンチマーク | 7帯中5帯がowner 1名＝自分自身との比較でpercentileが構造上無意味。帯は配信者内でも変動するため、帯遷移が測定対象の成績と交絡します。 |
| コメント本文の統計解析 / topic clustering | comment 59,922件のmedian長10文字、40%が8文字以下。character bigram上位は全て機能語・活用語尾の断片で、解決には形態素解析器（提案が明示的に避けた新規依存）が必要。頻出上位は挨拶ではなくgift勧誘のコピペ定型文で、上位10人が全commentの62.5%を占めます。 |
| sentiment/toxicity分類による感情カーブ | 名指しされたDetoxify multilingual / cardiff XLM-R はいずれも**日本語を対象言語に含みません**（corpusの87.5%が日本語）。zero-shotで数値は返りますが精度は未検証で、検証不能なscoreで感情帯を描くことになります。 |
| Gift品目ミックス分析 | 品目別の回数/coin/単価集計は session_summary と aggregate_dashboard に既に実装済み。総coin 3,042,368のうち上位50 eventで39%を占め、どの切り口も数十件の個別課金で決まります。gift棚はplatform都合でrotationするため期間横断の時系列は誤読を誘発します。 |
| グローブ運用ROI（投下効率） | 窓中vs窓外のcoin/秒は「盛り上がる瞬間を狙ってカードを使う」逆因果で解釈不能。実効倍率は選択biasが致命的で（score_deltaはcrit解決済みgiftにしか入らず、未解決は分割送信が多い条件で発生）、「小分けほど得に見える」方向に必ず歪みます。 |
| 対戦相手プロファイルDB | 相手陣の実弾は接続前giftを構造的に取り逃す別instrument計測（自陣は完全計測）で、カバレッジ率併記では救えません。相手別効果量も大半がn=1〜3でmatchmakingが非ランダム。そもそも本toolは他者配信の観測toolで、userは対戦相手を選べません。 |
| 視聴者Lv/badge成長トラッキング | メンバーLvは当該配信者へのgiftで上がる仕様のため「昇格前後のcoin変化」は循環論法（実測で昇格の55%が直前10分以内のgiftを伴う）。gifter Lvは全TikTok累積のため当room内課金と紐付きません。バッジ取得eventは0が「非保有」と「未搭載」を区別できず検出不能です。 |
| viewer_samples直読みの同接カーブ解析 | 時間加重平均CCV・viewer-hours・peakは `_payload_scale_efficiency` で既に算出済み。viewer_samplesもbuckets経由でanalyticsへ流入済みです。増えるのは解像度10s→4sのみ。（ただし検証中に、終了済みsessionの一部でbucketsが0行という**既存の欠測bug**を発見しました。こちらは別途対応の価値があります。） |
| 転写textを軸にしたevent-study | transcriptsは全録画296本中3件。segmentは中央値2.14秒で2〜3秒に1回発火するため、baseline区間にも発話が詰まっており「喋っていない反実仮想」が存在しません。diarizationも無く配信者本人の発話を切り分けられません。 |
| コラボ配信の話者diarization | collab_windowsは参加者rosterを持たず（guests_maxは315行すべて0）、speaker→実人物の候補集合が空になります。「自分の発話比率」は1v1では音声のみで決定できません。 |
| リアルタイム異常検知アラート | 実DB 59.8時間でrobust z-scoreを実走させた結果、z<-6.0でも1.8件/hr/stream発報（正規分布なら事実上ゼロ）。閾値を倍にしても6割しか減らず、同接系列が強い非定常のためz-scoreが情報を持ちません。z<-4.0の発報の64%はbattle窓内/終了直後で、実体はbattle終了で水増しviewerが引く既知の現象です。 |

### C. 既存機能と重複、または増分が薄いもの

| 候補 | 却下理由 |
|---|---|
| RoomUserSeqEvent.m_contributors（Top Gifter ranking） | m_deltaもm_popularityも実wireに一度も現れず常に空。contributorsは常に上位5件のみでGini等の分布統計は補正不能。m_scoreがdiamondsである保証もありません（視聴者払いcoin軸の可能性）。行数は約72万行（events表の1.6倍）に達します。 |
| GiftEventの未読field（to_user / is_first_send_gift / match_info等） | 最上位のto_userは0/52、is_first_send_giftも0/52、match_info.criticalは0/52。確実に届くcombo_count/group_idが解決するはずの「streak重複計上risk」は、streaking中early-returnで既に構造的に閉じています。 |
| Subscribe周辺の詳細化 / SuperFan系 | 本番DB 437,000 eventで `kind='subscribe'` が**0件**。samplerに登録済みなのにSubscribeEvent.jsonlも生成されていません。器を作っても格納される行がありません。 |
| 視聴者参加型企画event（Goal / Poll / Question / Countdown） | 同じ論法の先行bet 7種（GoodyBag/BoostCard/HotRoom/SpecialPush等）がsampler登録済みで**1本もjsonlが生成されていません**。実装済みのportalですらmarker 15件/7sessionでtreatmentに昇格できていない母数です。 |
| CaptionEvent（TikTok公式自動字幕） | realtime pushのため既存296録画への恩恵はゼロ（「転写なしの過去録画にも検索が張れる」という中核理由が不成立）。anchor側のcaption有効化率も未計測です。 |
| EmoteChatEvent | engagementに算入すると過去session全件で欠落する系列断絶を作り（backfill不可）、算入しなければ便益ゼロ。実発生量の測定値も皆無です。 |
| 配信メタ（title / hashtag / category） | LiveIntroEventはTikTokアカウントloginが前提で、匿名sign接続では原理的に届きません。カテゴリ層別も配信者6名・上位2名で89%という構成では配信者IDとほぼ共線です。 |
| サムネイル / コンタクトシート生成 | 横断的な平坦「録画一覧」画面が存在せず（recording listはsession詳細panel内）、縦型・単一人物・同一の部屋という条件下では別sessionのサムネがほぼ同一画になります。中身への到達手段はFTS検索・heat bar・highlight deep-linkの3系統が既にあります。 |
| 統計HUDの焼き込み | 同一history画面にtimeline chartとplayerが既に同居しています。毎frame変化するsparklineは、comment layerの性能を支えるcontent signature dedupを崩壊させます。 |
| mp4 chapter埋め込み | 主要browserはmp4 chapterをnative controlsに出さず、app内便益ゼロ。battleはcollab窓の内側で発生し区間が重なるため線形分割で構造情報が失われます。markersをDBから返して既存playerの下にseek stripを描く方が安く上位互換です。 |
| gift streakのcombo演出焼き込み | streakするのはgift.type==1（Rose等の1コイン級）のみで、`gift_min_diamonds` が間引くために用意された層です。希少な4 slotをそこへ割り当てることになり、集約保存では起きていないタイミングの描画＝捏造になります。 |
| ローカル埋め込みによる意味検索 | commentのmedian長10文字・31%が6文字以下で、高頻度上位はコピペ勧誘と絵文字連打。長文source（STT）はcoverage 1%。「盛り上がった場面」はbuckets/markers/heat barが既に直接満たしています。加えてsearch_hits.idが再index毎に総入れ替わるため、hit_id参照のvector表は毎回孤児化します。 |
| ハイライト検出のLLM命名 | comment 4.0〜4.8件/分では30秒窓に約2件しか入らず、そこから「何が起きたか」を生成させるのは捏造です。 |
| 音響event検出（歓声/笑い/拍手） | 観客が物理的に居ないため AudioSet の Cheering/Applause はほぼ発火せず、発火の主因はgift効果音とBGM＝giftと交絡した派生量です。TF/TF-Hub依存の追加も、CUDA DLLを手動登録している既存環境へのriskが高い。 |
| Battle戦術のAIレビュー | 逆転判定・score推移chart・bonus mission表示は既に実装済み。glove_eventsを持つbattleは28%、そのうち52%がcrit判定不能で、dedupなしにLLMへ渡すと幻の弾数を数えます。 |
| 配信チャプタ自動生成 | 転写は296本中3件、heat barによるnavigationは既存。最長転写でもtextは34KBの断片的な雑談で、抽出できるtitleは「挨拶」「雑談」程度に収束します。 |
| 視聴者（gifter）横断プロフィール画面 | gifter 1,173人中1,166人(99.4%)が単一配信者にしか出現せず、「他の配信にも来ているか」の答が固定です。配信者別gifter表・固定ファン/一見・cohortは既に実装済み。 |
| 全体解析の配信者/リーグ絞り込み | cluster-robust CI・偏相関・owner別dedupを前提とする解析群のため、配信者を絞るとcluster数が1〜2に落ちてCIが定義不能、散布図は1点、相関行列はn<3で全セル空になります。「絞り込むほど図が消える」機能になります。 |
| 監視対象の一括操作とimport/export | monitored_targetsは実測5件。移行はtictok.dbのcopyで足り（restore()が起動時に全target自動復帰）、CSVは永続済みtableの再serializeにしかなりません。checkboxを載せる表形式の管理画面も存在しません。 |
| グローバル検索bar + keyboard shortcut | 横断検索page（シーン検索）が既に存在し、配信者filterも4画面に実装済み。navは階層がなく既に1 clickです。document levelのkeydownが5箇所に既存でfocus contextの回帰面が広い。 |
| AI jobのDB queue化（提案原案） | LLM推論はin-process GPUではなく別processのHTTP endpointで、queueではVRAM常駐を制御できません。支える対象の機能群が未着手の段階での先行基盤は死荷重riskです。→ 実在の穴であるGPU排他のみ①-3へ縮小して採用しました。 |
| SNS投稿preset（解像度/bitrate/尺分割/無音trim） | sourceは既に適正で縮小は劣化のみ。無音trimはTikTok liveでほぼ無反応な上、中間trimが全再encodeを強制しtranscript timestampを破壊します。尺の機械分割は文の途中で切れます。→ 価値のあるloudnormと出力版選択のみ①-2へ縮小して採用しました。 |