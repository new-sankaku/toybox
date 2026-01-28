# バグ・仕様バグ チェックリスト

Gitコミット履歴から抽出した、過去に発生したバグ・仕様バグの一覧です。
今後の開発・レビュー時のチェックリストとしてご活用ください。

---

## クライアント側（Frontend）

### 型定義・インターフェース不整合
| # | 内容 | 回数 |
|---|------|------|
| 1 | WebSocket型定義がサーバー側イベントと一致していない（agent:created/running/waiting_provider等のイベントハンドラ未定義、ServerToClientEventsに型定義漏れ）。型定義全体を実サーバーイベントと乖離した推測ベースで構築していた | ×4 |
| 2 | Agent型定義にステータスが不足（waiting_response/paused/interrupted/cancelled/waiting_provider等の追加漏れ）。AgentCardのstatusConfigにも対応エントリが不足 | ×4 |
| 3 | barrel export漏れ（stores/index.ts、components/agents/index.tsにexport追加忘れ） | ×1 |
| 4 | API型定義（ProjectOptionsConfig、UISettingsResponse等）にサーバー側で追加されたフィールドが反映されていない | ×2 |
| 5 | TypeScript型エラー（未使用変数・関数の残存、型キャストの不整合） | ×1 |

### フォールバック・ハードコード問題
| # | 内容 | 回数 |
|---|------|------|
| 6 | サーバーからデータ取得失敗時にクライアント側でデフォルト値をフォールバック表示（DEFAULT_SERVICES/DEFAULT_COST_SETTINGS/DEFAULT_AUTO_APPROVAL_RULES等。ユーザー誤認の原因） | ×3 |
| 7 | AIサービスのプロバイダータイプ（'openai'/'comfyui'/'voicevox'/'suno'等）がリバースマッピング失敗時のフォールバックとしてハードコード | ×2 |
| 8 | APIベースURL/WebSocketURLに`localhost:5000`がフォールバック値としてハードコード（本番環境で誤接続） | ×2 |
| 9 | プロジェクトオプション（PROJECT_SCALE_OPTIONS/ASSET_SERVICE_OPTIONS/VIOLENCE_RATING_OPTIONS/SEXUAL_RATING_OPTIONS等6定数）がクライアント側TypeScriptに直接定義 | ×1 |
| 10 | ComfyUI/VOICEVOXのエンドポイントが`localhost:8188`/`localhost:50021`にハードコード | ×1 |
| 11 | DataViewのオーディオ再生URLに`localhost:8000`がプレフィックスとしてハードコード | ×1 |

### UI表示・操作問題
| # | 内容 | 回数 |
|---|------|------|
| 12 | statusCounts集計にwaiting_response/pausedのカウントが含まれておらずフィルタと不整合 | ×1 |
| 13 | チェックポイントresolved済みのアクションボタン（承認/却下/変更要求）が無効化されず操作可能だった | ×1 |
| 14 | violenceRatingOptions/sexualRatingOptions空配列時にクラッシュ（条件付きレンダリング+オプショナルチェーン不足） | ×1 |
| 15 | defaults nullの場合にクラッシュ（オプショナルチェーン不足） | ×1 |
| 16 | 未定義ステータスでAgentCardがクラッシュ（statusConfig undefinedのnull安全対策なし） | ×1 |
| 17 | エラー状態がUIに表示されない（filesErrorなどのerror stateが未表示） | ×1 |
| 18 | サイドバー開閉ボタンの矢印方向が逆 | ×1 |
| 19 | フォルダ選択ボタン（未実装機能）がUIに残っていた | ×1 |
| 20 | ログレベルの色分けが不適切（info/warn/errorの色が未区別） | ×1 |
| 21 | 削除確認ダイアログが未実装（プロジェクト、チャットの即時削除） | ×1 |
| 22 | 待機理由表示にWorkerが混入し不正確（Leader待機時の「何を待っているか」表示が誤り） | ×1 |
| 23 | デッドコード（到達不能なrunningAgentsチェック）による待機理由の誤表示 | ×1 |

### 機能未接続・動作不良
| # | 内容 | 回数 |
|---|------|------|
| 24 | InterventionView返信が既存介入への返答ではなく新規介入を作成していた | ×1 |
| 25 | リトライ対象ステータスにinterrupted/cancelledが不足（failed/blockedのみ対応） | ×1 |
| 26 | 一時停止対象ステータスにwaiting_approvalが不足（runningのみ対応） | ×1 |
| 27 | handleRetry関数がconsole.logスタブのまま未実装（実際のリトライAPI呼び出しがされない） | ×1 |
| 28 | AgentListViewにonRetryAgent propsが未接続（一覧画面からの再試行ボタンが機能しない） | ×1 |

### WebSocket・リアルタイム通信
| # | 内容 | 回数 |
|---|------|------|
| 29 | WebSocketにproject:updated/phase:changed/metrics:updateハンドラが未接続（リアルタイム更新されない） | ×1 |
| 30 | agent:speech型にprojectId/timestampフィールドが不足 | ×1 |
| 31 | agent:failedイベントでerrorフィールドがagentに反映されずUIでエラーメッセージ未表示 | ×1 |

### Store・状態管理
| # | 内容 | 回数 |
|---|------|------|
| 32 | agentStoreのログ配列に上限がなくメモリリークの原因（1000件上限追加で修正） | ×1 |
| 33 | hooksレイヤーが不要にもかかわらず存在（Zustandなら直接store接続で十分） | ×1 |

### API同期
| # | 内容 | 回数 |
|---|------|------|
| 34 | バックエンドで削除済みのAPIエンドポイント（projectApi.get/agentApi.getOutputs等5メソッド）がフロントエンドapiService.tsに残存し呼び出すと404 | ×1 |
| 35 | cancel APIメソッドがapiServiceに未定義 | ×1 |

---

## サーバー側（Backend）

### 実装漏れ・コールバック未接続
| # | 内容 | 回数 |
|---|------|------|
| 1 | Workerにon_progress/on_log/on_speechコールバックが渡されておらず進捗・ログ・発言がフロントに到達しない | ×3 |
| 2 | Leader contextにon_log/on_progress/on_checkpointコールバックが未設定（Leader-Workerパスでスキル実行ログが届かない） | ×1 |
| 3 | LeaderWorkerOrchestratorでworkerのspeechコールバックが未接続（worker発言がクライアントに届かない） | ×1 |
| 4 | api_runner.run_agent()がlog/progressストリームイベントを破棄していた | ×1 |
| 5 | DB migration漏れ（temperature, messages_jsonカラムのALTER TABLE未実行でSQLエラー） | ×1 |
| 6 | _integrate_outputsのsubmit_jobにtemperatureパラメータが渡されていない | ×1 |
| 7 | to_dict()にmessagesJsonフィールドがなくAPI応答でメッセージ履歴が取得不可 | ×1 |
| 8 | system_promptがMessages APIで正しく分離されず構造が破壊されていた | ×1 |

### 状態管理・並行処理バグ
| # | 内容 | 回数 |
|---|------|------|
| 9 | waiting_response状態のAgent二重実行（復帰を既存スレッドが処理するにも関わらずre_execute_agentが呼ばれる） | ×1 |
| 10 | Leader contextにon_checkpointを設定するとLeader個別実行時にwaiting_approvalに遷移しWorker実行がブロックされる | ×1 |
| 11 | _running_agentsがスレッドセーフでなかった（threading.Lock+Dict[str,bool]で修正） | ×1 |
| 12 | ジョブキューの_active_jobsがスレッドセーフでなかった（threading.Lockで修正） | ×1 |
| 13 | claim_job処理がアトミックでなかった（UPDATE文に変更して修正） | ×1 |
| 14 | checkpoint:resolvedのWebSocket emitにroom指定が漏れていた | ×1 |
| 15 | チェックポイントapproved後にagent statusがcompletedに設定されなかった | ×1 |
| 16 | AgentSimulatorとtestdata.pyが同じTestDataStoreに並行書き込みし競合状態を引き起こしていた | ×1 |

### ハードコード・設定値問題
| # | 内容 | 回数 |
|---|------|------|
| 17 | プロバイダーID "anthropic"がデフォルト値としてハードコードされていた | ×1 |
| 18 | 品質評価/要約/API呼び出しにモデル名・プロバイダー名がハードコードされていた（動的解決に変更） | ×2 |
| 19 | max_tokensのデフォルト値がモデルの実際の出力上限と一致していなかった（8192→32768等） | ×1 |
| 20 | ファイル拡張子のカテゴリマッピングとスキャンディレクトリがコード内にハードコード | ×1 |
| 21 | parent_agent_idがNoneにハードコードされWorker親子関係を設定不可 | ×1 |
| 22 | AgentType enumに重複エイリアス定義（CONCEPT/CONCEPT_LEADERが同じ値等） | ×1 |
| 23 | auto_approval_rulesにlabelがなくクライアントがカテゴリ名をハードコードする必要があった | ×1 |

### エラーハンドリング・ログ
| # | 内容 | 回数 |
|---|------|------|
| 24 | print()がlogger.info/error()の代わりに使用されていた（20ファイル） | ×1 |
| 25 | bare except/except passでエラーが握りつぶされていた（deepseek.py/project_tree.py/ai_provider.py等4箇所以上） | ×2 |
| 26 | exc_info=Trueが例外ハンドラに付与されておらずスタックトレースが記録されない | ×1 |
| 27 | speech初期化失敗時にwarningログが出ない（except Exception: passのまま） | ×1 |
| 28 | エラーレスポンスが統一形式ではなく生JSONで返されておりクライアント側のハンドリングが不整合 | ×1 |

### セキュリティ
| # | 内容 | 回数 |
|---|------|------|
| 29 | パストラバーサル脆弱性（backup.pyでファイル名の検証なし） | ×1 |
| 30 | web_skillsのURL解析失敗時にアクセスがブロックされない | ×1 |
| 31 | ai_provider.pyで例外情報（内部実装詳細）がクライアントに漏洩 | ×1 |
| 32 | file_skillsにシンボリックリンク対策がなかった（os.path.realpath未使用） | ×1 |
| 33 | ファイルアップロードにディスクフル対策・書き込みエラーハンドリングがなかった | ×1 |
| 34 | MAX_CONTENT_LENGTHが未設定（サーバーに無制限リクエスト送信可能） | ×1 |

### LLM/AI API関連
| # | 内容 | 回数 |
|---|------|------|
| 35 | xai/deepseek/zhipuのchat_stream()でストリーミング時のトークン使用量が記録されなかった（stream_options未設定） | ×1 |
| 36 | deepseek/xaiでusage未取得時にも空のfinalチャンクが先に出力されストリーム終了判定が誤動作 | ×1 |
| 37 | Worker実行結果のtokens_usedがresultオブジェクトに格納されず消失 | ×1 |
| 38 | API接続エラー時に無限リトライで待機しAPI負荷を増大（health_monitorフラグ確認方式に変更） | ×1 |
| 39 | WorkerTaskResultにtokens_used等のフィールドが不足（トークン集計不可） | ×1 |
| 40 | LLMジョブ失敗時のリトライロジックが未実装（MAX_JOB_RETRIES=3で追加） | ×1 |
| 41 | 品質チェックリトライ時に前回の問題点がプロンプトに反映されなかった | ×1 |
| 42 | _build_promptに未使用の{config}変数が残存 | ×1 |

### 設計・アーキテクチャ問題
| # | 内容 | 回数 |
|---|------|------|
| 43 | リカバリ処理がサーバー起動時に全プロジェクトスキャンし正常動作中のエージェントもinterruptedにしてしまう | ×1 |
| 44 | 同時実行制御がインメモリSemaphoreのためサーバー再起動でジョブ状態喪失 | ×1 |
| 45 | グローバル同時実行数制限ではプロバイダー間で枠を奪い合う問題（プロバイダー別に分離して解決） | ×1 |
| 46 | cloudグループとプロバイダーのmax_concurrentが二重チェックされ低い方で制限される仕様バグ（排他ロジックに変更） | ×1 |
| 47 | staleジョブがpendingに戻されて意図せず再実行される仕様バグ（delete方式に変更） | ×1 |
| 48 | プロジェクト開始/再開時にジョブクリーンアップが行われず前回の未完了ジョブが残留 | ×1 |
| 49 | testdataモード指定時にfactoryがValueErrorを出す（MockAgentRunner生成パスなし） | ×1 |
| 50 | cancel_agentが非同期のままハンドラ側で適切に処理されなかった（sync化） | ×1 |
| 51 | SkillRunnerでトレース記録（create/complete/fail）がなかった | ×1 |
| 52 | revision_requested後の再実行（re_execute_agent）が未実装 | ×1 |
| 53 | Agent完了時の後続Agent自動再開ロジックが未実装 | ×1 |
| 54 | rate_limiterに定期クリーンアップがなくメモリリークの可能性 | ×1 |
| 55 | SQLite WALモードとbusy_timeoutが未設定（同時アクセスで問題発生） | ×1 |

---

## カテゴリ別サマリー

### 頻出パターン（要重点チェック）
| カテゴリ | 合計回数 | 説明 |
|----------|----------|------|
| 型定義・インターフェース不整合 | ×12 | サーバー側で追加した型・ステータス・フィールド・イベントがクライアント側に反映されない |
| フォールバック・ハードコード（C+S） | ×17 | クライアント側にデフォルト値やURL、サーバー側にプロバイダーID/モデル名がべた書き |
| 実装漏れ・コールバック未接続 | ×10 | 新機能追加時にコールバックや伝播パスが接続されていない、DB migrationの漏れ |
| 状態管理・並行処理 | ×8 | スレッドセーフ未対応、二重実行、状態遷移の不整合、競合状態 |
| UI表示・操作・機能不良 | ×17 | クラッシュ、未接続props、スタブ関数の放置、確認ダイアログ欠如 |
| エラーハンドリング不足 | ×6 | print使用、エラー握りつぶし、スタックトレース未記録 |
| セキュリティ | ×6 | パストラバーサル、情報漏洩、symlink対策、アクセス制御不備 |
| LLM/AI API | ×8 | トークン計測漏れ、リトライ不足、ストリーム終了判定の誤り |
| 設計・アーキテクチャ | ×13 | リカバリ設計、同時実行制御、ジョブライフサイクル、DB設定 |
