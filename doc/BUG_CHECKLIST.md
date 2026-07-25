## Client

| 内容 | 回数 |
|------|------|
| WebSocket型定義がサーバー側イベントと一致していない（イベントハンドラ未定義、型定義漏れ）。推測ベースで構築していた | ×4 |
| 型定義にステータスが不足（新ステータス追加時に型・statusConfig両方の更新漏れ） | ×4 |
| barrel export漏れ（index.tsにexport追加忘れ） | ×1 |
| API型定義にサーバー側で追加されたフィールドが反映されていない | ×2 |
| APIレスポンスのネスト構造を無視して直接配列を期待（{data:[...]}を[...]として扱う） | ×1 |
| TypeScript型エラー（未使用変数・関数の残存、型キャストの不整合） | ×1 |
| サーバーからデータ取得失敗時にクライアント側でデフォルト値をフォールバック表示（ユーザー誤認の原因） | ×3 |
| プロバイダータイプがリバースマッピング失敗時のフォールバックとしてハードコード | ×2 |
| APIベースURL/WebSocketURLにlocalhostがフォールバック値としてハードコード（本番環境で誤接続） | ×2 |
| 選択肢定数（スケール、アセットサービス、レーティング等）がクライアント側TypeScriptに直接定義 | ×1 |
| 外部サービスのエンドポイントがlocalhostにハードコード | ×1 |
| メディア再生URLにlocalhostがプレフィックスとしてハードコード | ×1 |
| ステータス集計にステータス追加漏れがありフィルタと不整合 | ×1 |
| 完了済みアクションのボタンが無効化されず操作可能だった | ×1 |
| 空配列・null値に対するオプショナルチェーン不足でクラッシュ | ×3 |
| エラー状態がUIに表示されない（error stateが未表示） | ×1 |
| ボタンの方向・アイコンが逆 | ×1 |
| 未実装機能のUIが残っていた | ×1 |
| ログレベルの色分けが不適切 | ×1 |
| 暗い背景（CardHeader等）に暗い文字色を指定して視認性が悪い | ×10 |
| 破壊的操作に確認ダイアログが未実装 | ×1 |
| 親子関係の集計にWorkerが混入し表示が不正確 | ×1 |
| デッドコードによる表示の誤動作 | ×1 |
| 返信操作が既存データへの更新ではなく新規作成になっていた | ×1 |
| 操作対象ステータスの網羅漏れ（新ステータス追加時にボタン表示条件が未更新） | ×2 |
| 関数がconsole.logスタブのまま未実装（実際のAPI呼び出しがされない） | ×1 |
| propsが親コンポーネントから未接続でボタンが機能しない | ×1 |
| WebSocketイベントハンドラが未接続でリアルタイム更新されない | ×1 |
| WebSocketイベント型にフィールドが不足 | ×1 |
| WebSocketイベント受信時にデータがStoreに反映されない | ×1 |
| state_syncにドメインデータが含まれずタブ選択まで初期表示されない | ×1 |
| Store内の配列に上限がなくメモリリーク | ×1 |
| 不要なレイヤーが残存（ライブラリ機能で代替可能） | ×1 |
| バックエンドで削除済みのAPIメソッドがフロントエンドに残存し呼び出すと404 | ×1 |
| サーバー側に存在するAPIメソッドがクライアントに未定義 | ×1 |

## Server

| 内容 | 回数 |
|------|------|
| 署名付きCDN URLの資産(avatar等)をbest-effort一発取得し、収集時に失敗するとURL失効後は復元不能（retry/間隔制御がなく取得漏れが永続化、burn-in側で代替不能） | ×1 |
| best-effort処理の失敗logがconsoleのみでfile未保存のため事後の原因特定が不能 | ×1 |
| Workerにコールバックが渡されておらず進捗・ログ・発言がフロントに到達しない | ×3 |
| Leader contextにコールバックが未設定でLeader-Workerパスのイベントが届かない | ×1 |
| Orchestratorでworkerのコールバックが未接続で子の発言がクライアントに届かない | ×1 |
| ストリームイベントを破棄していた | ×1 |
| DB migration漏れ（新規カラムのALTER TABLE未実行でSQLエラー） | ×1 |
| 新規パラメータがジョブ投入時に渡されていない | ×1 |
| シリアライズ用メソッドに新規フィールドが追加されずAPI応答でデータ取得不可 | ×1 |
| system_promptがMessages APIで正しく分離されず構造が破壊されていた | ×1 |
| 状態復帰時に既存スレッドと新スレッドでAgent二重実行 | ×1 |
| コールバック設定により意図しない状態遷移が発生しフローがブロック | ×1 |
| 共有辞書がスレッドセーフでなかった（Lockなし） | ×2 |
| DB操作がアトミックでなかった（競合発生） | ×1 |
| WebSocket emitにroom指定が漏れていた | ×1 |
| 承認後のステータス遷移が未実装 | ×1 |
| 2つのコンポーネントが同じデータストアに並行書き込みし競合状態 | ×1 |
| プロバイダーIDがデフォルト値としてハードコード | ×1 |
| モデル名・プロバイダー名がコード内にハードコード（動的解決すべき） | ×2 |
| max_tokensのデフォルト値がモデルの実際の出力上限と不一致 | ×1 |
| ファイル拡張子・スキャンディレクトリ等の設定値がコード内にハードコード | ×1 |
| 外部キーがNoneにハードコードされ親子関係を設定不可 | ×1 |
| Enum定義に重複エイリアスが存在 | ×1 |
| 設定にlabelがなくクライアントが表示名をハードコードする必要があった | ×1 |
| print()がlogger使用の代わりに使用されていた | ×1 |
| bare except/except passでエラーが握りつぶされていた | ×2 |
| exc_info=Trueが例外ハンドラに付与されておらずスタックトレースが記録されない | ×1 |
| 初期化失敗時にログが出ない（except passのまま） | ×1 |
| エラーレスポンスが統一形式ではなくクライアント側のハンドリングが不整合 | ×1 |
| パストラバーサル脆弱性（ファイル名の検証なし） | ×1 |
| URL解析失敗時にアクセスがブロックされない | ×1 |
| 例外情報（内部実装詳細）がクライアントに漏洩 | ×1 |
| シンボリックリンク対策がなかった | ×1 |
| ファイルアップロードにディスクフル対策・書き込みエラーハンドリングがなかった | ×1 |
| リクエストサイズ上限が未設定 | ×1 |
| ストリーミング時のトークン使用量が記録されなかった（stream_options未設定） | ×1 |
| usage未取得時にも空のfinalチャンクが出力されストリーム終了判定が誤動作 | ×1 |
| 実行結果のtokens_usedがresultオブジェクトに格納されず消失 | ×1 |
| API接続エラー時に無限リトライで待機しAPI負荷を増大 | ×1 |
| 結果型にトークン集計用フィールドが不足 | ×1 |
| ジョブ失敗時のリトライロジックが未実装 | ×1 |
| 品質チェックリトライ時に前回の問題点がプロンプトに反映されなかった | ×1 |
| プロンプトテンプレートに未使用変数が残存 | ×1 |
| リカバリ処理がサーバー起動時に全スキャンし正常動作中のプロセスも停止させてしまう | ×1 |
| 同時実行制御がインメモリのためサーバー再起動で状態喪失 | ×1 |
| グローバル同時実行数制限でプロバイダー間で枠を奪い合う問題 | ×1 |
| グループとプロバイダーの制限値が二重チェックされ低い方で制限される仕様バグ | ×1 |
| 残留ジョブがpendingに戻されて意図せず再実行される仕様バグ | ×1 |
| プロジェクト開始/再開時に前回の未完了ジョブがクリーンアップされない | ×1 |
| 特定モード指定時にfactoryが対応クラスを生成できずエラー | ×1 |
| 非同期/同期の不一致でハンドラ側で適切に処理されなかった | ×1 |
| 処理の記録（トレース）が未実装 | ×1 |
| 再実行トリガーが未実装 | ×1 |
| 後続処理の自動再開ロジックが未実装 | ×1 |
| 定期クリーンアップがなくメモリリークの可能性 | ×1 |
| SQLite WALモードとbusy_timeoutが未設定（同時アクセスで問題発生） | ×1 |
| モデルに存在しないカラム名を参照（timestamp→created_at等のカラム名不一致） | ×2 |
| エージェント作成リストがハードコードされYAML設定と不整合 | ×1 |
| エージェント完了後に次エージェント自動開始ロジックが未実装 | ×1 |
| protoの片系統のみparseし他系統(team_armies等)を読まず値が0になる（受信dataの破棄） | ×1 |
| eventごとにカウンタを+1し同一ID(battle_id)の複数actionを二重カウント | ×1 |
| 信頼できない値で勝敗/集計を判定（取得不能/0頻発のfieldを主軸にしていた） | ×1 |
| 局所的なPTS discontinuity(glitch timestampで1 segmentのEXTINFが巨大化)を全体一律scaleでmedia→mp4 PTS変換し、誤差が全体に拡散してComment焼き込みが時間経過で累積drift（gap edgeをanchorにしたpiecewise mapで解消、captureでも該当segmentをconcatから除外） | ×1 |
| 焼き込みのスピチャレ(倍率タイム)帯で、ミッション帯の終端にtask_duration(実終了)でなくreward_start_tsを使い、達成〜倍率開始のsettle gap分だけ「達成で」表示がズレ、達成beatも欠落（mission_end=task_start+task_durationで終端を確定し、gapを達成beatで埋め、予告帯も追加） | ×1 |
| burn-in倍率(×N=reward_multiple)はSTART messageにしか載らず、START取り逃し(途中接続)時にplaceholderのmultiplier=0で×Nが永続欠落（復元不可のためwarning logで可視化、TASK_SETTLEからreward_start/達成resultを確定取得） | ×1 |
| 同一DBに複数のサーバープロセスが起動し同じroomを二重監視→同一battle_idが複数sessionに保存され戦数/勝敗/コインが水増し（プロセス間排他なし。manager重複排除はプロセス内のみ） | ×1 |
| cleanup_stale_sessionsが起動時にconnecting/connected/reconnectingの全sessionを無条件finalizeし、別プロセス稼働中のlive sessionまで終了させる（時間/所有プロセス境界の未考慮） | ×1 |
| cross-session集計でbattle_idの重複排除をせず、重複保存レコードをそのまま二重計上 | ×1 |
| team戦で相手チーム集約貢献のhost_idにanchor_id_str(="2"等のチームidplaceholder)を使い、UIが参加host(実id)へ紐づけられず貢献者がカードから脱落・人数が表示と不一致（実hostのmember idへ寄せて解消） | ×1 |
| 表示と集計の基準不一致：カードはscore=0貢献者を「BS=実弾(推測)」と表示するのに、件数判定(100↑)は本物のscoreのみで数え「BSが見えるのに0」になる（実効BS=score優先・無ければ実弾、に統一） | ×1 |
| PK中のGift受信(_on_gift)でbattlesを再配信せず、新規貢献者がarmies/battle event受信まで反映されない（進行中battle時にthrottle付き再配信を追加） | ×1 |
| 一時的な負のsignal(LiveRoom欠落=UserNotFoundError)を恒久terminalと断定し、単発の誤検知で監視をSTATE_ERROR停止させ配信復旧不可（partial render/WAF部分通過/地域差でも起きる。offlineと同じくbackoffポーリング継続に変更し自動復旧） | ×1 |
| reconnect上限超過を恒久terminal(STATE_ERROR)化し、一時障害(署名サーバーrate limit/host長時間ネット断)で監視が死んだまま復旧不可（reconnectはwebcast WS再接続=毎回EulerStream署名リクエスト消費。上限超過時はfree(署名0)なbrowser watch loopへフォールバックし、live再確認後のみ再connect＝署名枠を使い切らず自動復旧） | ×1 |
| 配信側の適応bitrateで解像度が配信中に変動(320x640〜720x1280の4種)し、異なる解像度のHLS segmentをstream copyで1 mp4トラックに連結→trackは先頭解像度固定なのに実dataは混在。技術的にvalidだが多くのplayer(MPC-BE等)が切替点でフレーム保持(同一frame反復)/急拡大/カクつき。データ自体は正常(freezedetect0件/全frame画素unique/PTS単調)で結合bugではないが、finalizeで混在検出時のみ最大解像度へaspect保持padで単一解像度化re-encode(timing map維持のため-fps_mode passthroughでPTS保持、uniform配信はstream copyのまま)。互換性目的なのでcodecはH.264既定 | ×1 |
| storage writerは非同期batch方式でadd_eventがeventをmemory bufferに積み後からcommitするため、そのsessionがdelete_session(履歴削除/restricted discard)で先に消えると、buffer滞留分がevents.session_id→sessions(id)のFKに違反しdrainがbatchごと失敗。_drainのexcept節が全例外を一時障害とみなし先頭へ再キューするため、永続エラーのFK違反が永久に失敗し続け後続の全event/viewerが黙って滞留・消失(poison-pill)。修正:(1)delete_sessionがDELETE前にbuffer内の該当session行を破棄し孤児を作らない (2)_drainがinsert前に実在session_idで濾し孤児行をdrop(self._lock保持中でありdelete_sessionもlock取得後DELETEするためTOCTOU無し)。executemanyは違反行手前まで部分挿入するので単純な1行retryは重複を生む点に注意(pre-filter方式で回避) | ×1 |
| _drainのexcept節が全例外を一時障害扱いでbatch丸ごと再キュー→永続エラー(制約違反等)の1行がbatch全体・後続全体を永久に道連れ(poison-pill)。修正: OperationalError=一時障害はrollback+再キューで再試行、IntegrityError=永続不良はrollback後1行ずつ入れ直し違反行だけdead-letter(storage_quarantine.jsonl)へ隔離して残りは確定、想定外例外(DatabaseError等)は誤って全損させぬよう再キューにfallback。error分類で「1つのエラーで全部飛ぶ」を構造的に排除 | ×1 |
| batched SQLite writerが唯一の永続経路のため、writer停滞/クラッシュ/再起動でbuffer未commit分が復元不能に消失(実害: session292/293のevent全損)。修正: 取り込み時点(add_event/add_viewer_sample)でeventをdisk追記する耐久journal(日次NDJSON, config化, flushでOS cacheまで)を追加し、起動時recover_from_journalがDBに欠けた分を復元(session未存在=削除は非resurrect/DB同数以上はno-op/journalが全項目でDB上回る時のみidempotent全置換+stats・buckets・analytics再構成)。retention日数で自動prune。注: 生journal導入前に失われたdataは対象外 | ×1 |
| reconnectは1試行ごとにEulerStream署名リクエストを1消費するが、試行中に配信の生存を一度も再確認しないため、配信終了で死んだroom(署名側は502/500固定)へ上限回数ぶん確実に外れる空撃ちを continue（実測: 1配信で114回消費／日次枠1000。枠を使い切ると他配信者が429で接続不能になる二次被害）。修正: 数試行ごとに署名0のbrowser live再解決を1回挟み、明確なofflineならsessionを閉じてwatch loopへ復帰。曖昧(LiveResolveBlocked/UserNotFoundError/例外)は「不明」として再接続を継続し、live中のsessionを誤って落とさない。再解決は_resolved_room_id(=_connect_onceの接続先)を書き換えるため、別roomでの配信再開も「このsessionの終了」として扱い、次配信のdataが旧sessionへ混入するのを防ぐ | ×1 |
| 同じ「Battle窓のgift貢献」を2箇所が別実装で持ち、片方(streamer_profile)だけend_time欠落時に窓を無制限(9_999_999_999=配信終了まで)にしていたため、Battle後〜配信終了の通常Giftを貢献へ丸ごと誤帰属（実測: 貢献者100+が0人→12人、Batt中コインが26→19397）。もう片方(apply_battle_gift_contributions)はduration→次Battle開始→実観測中央値fallbackで正しく閉じていた。修正: 窓解決をcore/battle.pyのgift_window_end/gift_window_fallback_durationへ単一化し、両経路が同じ窓・同じ入口(battle_gift_contributions)を使う。突合軸もe.time(受信時刻)からCOALESCE(create_time,time)(窓境界と同じserver時刻)へ統一 | ×1 |
| チーム戦のteam集約armiesはhost別に割れず自陣owner(=監視配信者)へ寄せて保存されるため、Battle cardは味方hostのgifterまで監視配信者の貢献者として表示する一方、履歴列は自室Gift eventのみを数え、同じBattleで人数もコインもScoreも食い違う(実測: 25戦中17戦で不一致、貢献者4人 vs 7人)。own_scoreも同様にチーム合計で、監視配信者1人ぶんのscoreとは別物。修正: どちらか片方に寄せず「自室実測 / 陣営計」を両方返して併記(own_host_score/team_diamonds/team_key_contributors)。自hostを特定できない古いrecordは0でなくNoneにし平均の母数からも外す（0は「無得点だった」と読める偽の実測値になるため） | ×1 |
| 中身を作り直す経路(起動時の中断録画復旧・再mp4化)が、live capture用のfinalizeを流用して `ended_at = time.time()` をDBへ書き戻し、捕捉が終わった時刻を**実行した時刻**で潰していた。batchで走ると全行のended_atが同一時刻に揃い、started_atは元のままなので古い行ほど差が開く(実測: 3時間07分の録画が34時間02分、実尺0分の録画が650時間)。新しい順の一覧では下へ行くほど尺が伸び「積算」に見える。ended_atはevent窓としても使われるため、焼き込みが次の録画ぶんのcommentまで巻き込む。修正: 作り直し専用のupdate_rebuilt_recording(ended_at=COALESCE(ended_at,?)で既存値に触れない)へ分離し、尺はffprobe実測のduration_seconds列を新設して画面・見積り・実測比の出所を壁時計から外した | ×1 |
