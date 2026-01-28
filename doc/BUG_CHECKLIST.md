# バグ・仕様バグ チェックリスト

Gitコミット履歴から抽出した、過去に発生したバグ・仕様バグの一覧です。
今後の開発・レビュー時のチェックリストとしてご活用ください。

---

## クライアント側（Frontend）

### 型定義・インターフェース不整合
| # | 内容 | 回数 |
|---|------|------|
| 1 | WebSocket型定義がサーバー側イベントと一致していない（agent:created/running/waiting_provider等のイベントハンドラ未定義、ServerToClientEventsに型定義漏れ） | ×3 |
| 2 | Agent型定義にステータスが不足（waiting_response/paused/interrupted/cancelled/waiting_provider等の追加漏れ） | ×3 |
| 3 | barrel export漏れ（stores/index.ts、components/agents/index.tsにexport追加忘れ） | ×1 |
| 4 | API型定義（ProjectOptionsConfig、UISettingsResponse等）にサーバー側で追加されたフィールドが反映されていない | ×2 |
| 5 | TypeScript型エラー（未使用変数・関数の残存、型キャストの不整合） | ×1 |

### フォールバック・ハードコード問題
| # | 内容 | 回数 |
|---|------|------|
| 6 | サーバーからデータ取得失敗時にクライアント側でデフォルト値をフォールバック表示（ユーザー誤認の原因） | ×2 |
| 7 | AIサービスのプロバイダータイプ（'openai'等）やエンドポイントURLがクライアント側にハードコードされていた | ×2 |
| 8 | コスト設定（DEFAULT_COST_SETTINGS）やオートアプルーバルルール（DEFAULT_AUTO_APPROVAL_RULES）がクライアント側に定数として存在 | ×1 |
| 9 | APIベースURL/WebSocketURLにフォールバック値がハードコードされていた | ×1 |
| 10 | プロジェクトオプション（スケール選択肢等）がクライアント側のTypeScriptファイルに直接定義されていた | ×1 |

### UI表示・操作問題
| # | 内容 | 回数 |
|---|------|------|
| 11 | statusCounts集計にwaiting_response/pausedのカウントが含まれておらずフィルタと不整合 | ×1 |
| 12 | チェックポイントresolved済みのアクションボタンが無効化されていなかった | ×1 |
| 13 | violenceRatingOptions/sexualRatingOptions空配列時にクラッシュ（条件付きレンダリング+オプショナルチェーン不足） | ×1 |
| 14 | defaults nullの場合にクラッシュ（オプショナルチェーン不足） | ×1 |
| 15 | エラー状態がUIに表示されない（filesErrorなどのerror stateが未表示） | ×1 |
| 16 | サイドバー開閉ボタンの矢印方向が逆 | ×1 |
| 17 | フォルダ選択ボタン（未実装機能）がUIに残っていた | ×1 |
| 18 | ログレベルの色分けが不適切（info/warn/errorの色が未区別） | ×1 |
| 19 | 削除確認ダイアログが未実装（プロジェクト、チャットの即時削除） | ×1 |
| 20 | インラインスタイル（style={{ }}）がTailwindクラスに変換されていなかった | ×1 |

### WebSocket・リアルタイム通信
| # | 内容 | 回数 |
|---|------|------|
| 21 | WebSocketにproject:updated/phase:changed/metrics:updateハンドラが未接続（リアルタイム更新されない） | ×1 |
| 22 | agent:speech型にprojectId/timestampフィールドが不足 | ×1 |
| 23 | agent:failedイベントでerrorフィールドがagentに反映されない | ×1 |

### Store・状態管理
| # | 内容 | 回数 |
|---|------|------|
| 24 | agentStoreのログ配列に上限がなくメモリリークの原因（1000件上限追加で修正） | ×1 |
| 25 | hooksレイヤーが不要にもかかわらず存在（Zustandなら直接store接続で十分） | ×1 |

### API同期
| # | 内容 | 回数 |
|---|------|------|
| 26 | バックエンドで削除済みのAPIエンドポイントがフロントエンドのapiService.tsに残存 | ×1 |
| 27 | cancel APIメソッドがapiServiceに未定義 | ×1 |

---

## サーバー側（Backend）

### 実装漏れ・コールバック未接続
| # | 内容 | 回数 |
|---|------|------|
| 1 | Workerにon_progress/on_logコールバックが渡されておらず進捗・ログがフロントに到達しない | ×2 |
| 2 | Leader contextにon_log/on_progress/on_checkpointコールバックが未設定（Leader-Workerパスでスキル実行ログが届かない） | ×1 |
| 3 | on_speechコールバックがskill_runner/orchestratorに伝播されていなかった（エージェント発言システムの実装漏れ） | ×1 |
| 4 | api_runner.run_agent()がlog/progressストリームイベントを破棄していた | ×1 |
| 5 | DB migration漏れ（temperature, messages_jsonカラムのALTER TABLE未実行） | ×1 |

### 状態管理・並行処理バグ
| # | 内容 | 回数 |
|---|------|------|
| 6 | waiting_response状態のAgent二重実行（復帰を既存スレッドが処理するにも関わらずre_execute_agentが呼ばれる） | ×1 |
| 7 | Leader contextにon_checkpointを設定するとLeader個別実行時にwaiting_approvalに遷移しWorker実行がブロックされる | ×1 |
| 8 | _running_agentsがスレッドセーフでなかった（threading.Lock+Dict[str,bool]で修正） | ×1 |
| 9 | ジョブキューの_active_jobsがスレッドセーフでなかった（threading.Lockで修正） | ×1 |
| 10 | claim_job処理がアトミックでなかった（UPDATE文に変更して修正） | ×1 |
| 11 | checkpoint:resolvedのWebSocket emitにroom指定が漏れていた | ×1 |
| 12 | チェックポイントapproved後にagent statusがcompletedに設定されなかった | ×1 |

### ハードコード・設定値問題
| # | 内容 | 回数 |
|---|------|------|
| 13 | プロバイダーID "anthropic"がデフォルト値としてハードコードされていた | ×1 |
| 14 | 品質評価/要約/API呼び出しにモデル名・プロバイダー名がハードコードされていた（動的解決に変更） | ×1 |
| 15 | max_tokensのデフォルト値がモデルの実際の出力上限と一致していなかった（8192→32768等） | ×1 |
| 16 | ハードコードされた設定値（ファイル拡張子、プロジェクトオプション等）がコード内に散在 | ×1 |

### エラーハンドリング・ログ
| # | 内容 | 回数 |
|---|------|------|
| 17 | print()がlogger.info/error()の代わりに使用されていた（20ファイル） | ×1 |
| 18 | bare except/except passでエラーが握りつぶされていた（エラーもみ消し） | ×1 |
| 19 | exc_info=Trueが例外ハンドラに付与されておらずスタックトレースが記録されない | ×1 |
| 20 | speech初期化失敗時にwarningログが出ない | ×1 |
| 21 | skills.yaml読込失敗時にサイレントフォールバック（エラーログ未出力） | ×1 |

### セキュリティ
| # | 内容 | 回数 |
|---|------|------|
| 22 | パストラバーサル脆弱性（backup.pyでファイル名の検証なし） | ×1 |
| 23 | web_skillsのURL解析失敗時にアクセスがブロックされない | ×1 |
| 24 | ai_provider.pyで例外情報（内部実装詳細）がクライアントに漏洩 | ×1 |
| 25 | file_skillsにシンボリックリンク対策がなかった（os.path.realpath未使用） | ×1 |
| 26 | ファイルアップロードにディスクフル対策・書き込みエラーハンドリングがなかった | ×1 |
| 27 | MAX_CONTENT_LENGTHが未設定（サーバーに無制限リクエスト送信可能） | ×1 |

### LLM/AI API関連
| # | 内容 | 回数 |
|---|------|------|
| 28 | xai/deepseek/zhipuのchat_stream()でストリーミング時のトークン使用量が記録されなかった（stream_options未設定） | ×1 |
| 29 | API接続エラー時に無限リトライで待機（wait_for_provider_availableに最大待機時間なし→30分上限追加） | ×1 |
| 30 | WorkerTaskResultにtokens_used等のフィールドが不足（トークン集計不可） | ×1 |
| 31 | LLMジョブ失敗時のリトライロジックが未実装（MAX_JOB_RETRIES=3で追加） | ×1 |
| 32 | 品質チェックリトライ時に前回の問題点がプロンプトに反映されなかった | ×1 |
| 33 | _build_promptに未使用の{config}変数が残存 | ×1 |

### 設計・アーキテクチャ問題
| # | 内容 | 回数 |
|---|------|------|
| 34 | リカバリ処理がサーバー起動時に全プロジェクトスキャンしていた（プロジェクト開始/再開時に変更） | ×1 |
| 35 | 同時実行制御がインメモリSemaphoreのためサーバー再起動でジョブ状態喪失（DBベースに変更） | ×1 |
| 36 | cancel_agentが非同期のままハンドラ側で適切に処理されなかった（sync化） | ×1 |
| 37 | SkillRunnerでトレース記録（create/complete/fail）がなかった | ×1 |
| 38 | revision_requested後の再実行（re_execute_agent）が未実装 | ×1 |
| 39 | Agent完了時の後続Agent自動再開ロジックが未実装 | ×1 |
| 40 | rate_limiterに定期クリーンアップがなくメモリリークの可能性 | ×1 |
| 41 | SQLite WALモードとbusy_timeoutが未設定（同時アクセスで問題発生） | ×1 |

---

## カテゴリ別サマリー

### 頻出パターン（要重点チェック）
| カテゴリ | 合計回数 | 説明 |
|----------|----------|------|
| 型定義・インターフェース不整合 | ×10 | サーバー側で追加した型・ステータス・フィールドがクライアント側に反映されない |
| フォールバック・ハードコード | ×7 | クライアント側にデフォルト値やURLがべた書きされている |
| 実装漏れ・コールバック未接続 | ×6 | 新機能追加時にコールバックや伝播パスが接続されていない |
| エラーハンドリング不足 | ×5 | print使用、エラー握りつぶし、スタックトレース未記録 |
| 状態管理・並行処理 | ×7 | スレッドセーフ未対応、二重実行、状態遷移の不整合 |
| セキュリティ | ×6 | パストラバーサル、情報漏洩、アクセス制御不備 |
| LLM/AI API | ×6 | トークン計測漏れ、リトライ不足、ハードコード |
