# Development Rules (開発規約)

LangGraph Game Development Systemの開発規約。Agent設計、コード規約、品質基準、運用ルールを定義。

## Design Principles (LangGraph Best Practices)

| Principle | Description |
|-----------|-------------|
| Single Responsibility | 1 Agent = 1 Task |
| Fine Granularity | 小さいAgentほど再利用・テスト・保守が容易 |
| Human Checkpoint | 不可逆アクションの前に`interrupt()` |
| Durable State | チェックポイントで永続化 |
| Parallel Execution | 依存関係のないAgentは並列実行 |

## 1. Agent設計原則

### DO / DON'T

| ✅ DO | ❌ DON'T |
|-------|----------|
| 1 Agentに1責務 | 複数タスクを詰め込む |
| 入出力を型定義 | anyや曖昧な型 |
| 冪等性を保つ | 副作用に依存 |
| エラーは明示的に返す | 例外を握りつぶす |
| プロンプトは外部ファイル化 | コード内にハードコード |

### Agent間通信フォーマット

JSON形式で統一。Pydantic BaseModelで定義。

```python
class AgentMessage(BaseModel):
    agent_name: str
    status: Literal["success", "needs_revision", "error"]
    data: dict
    metadata: dict  # tokens_used, duration_ms, model
```

### プロンプト設計

**ディレクトリ:** `prompts/{planning,development,quality}/`

**段階的生成フロー:** 理解 → 分析 → 計画 → 実行 → 検証

**自己修正ループ:** 生成 → 検証 → (NG時) フィードバック → 再生成 (最大3回)

## 2. コード規約

### ファイル構成

```
langgraph/
├── agents/{planning,development,quality}/
├── prompts/
├── state.py
├── graph.py
└── main.py
```

### 命名規則

| 対象 | 規則 | 例 |
|------|------|-----|
| Agent関数 | snake_case | `concept_agent()` |
| Agentクラス | PascalCase + Agent | `ConceptAgent` |
| State型 | PascalCase + State | `GameDevState` |
| プロンプトファイル | snake_case.md | `concept_agent.md` |
| 定数 | UPPER_SNAKE_CASE | `MAX_RETRIES` |

## 3. 品質・テスト方針

### テスト必須条件

| Level | 対象 | 必須テスト |
|-------|------|-----------|
| Unit | 各Agent | 入出力の型チェック、エッジケース |
| Integration | Agent間連携 | State受け渡し、並列実行 |
| E2E | 全フロー | Planning→Dev→Qualityの一連フロー |

### レビュー基準

- 単一責任
- 型定義
- テスト存在
- エラー処理
- プロンプト外部化

### エラーハンドリング

AgentError: agent_name, message, recoverable

リトライ設定は `config.yaml` で管理。

## 4. Human介入ルール

### 承認基準

| Phase | 承認ポイント | 承認基準 |
|-------|------------|---------|
| Planning | 各Agent後 | 方向性、要件充足 |
| Development | 各Agent後 | 動作、設計準拠 |
| Quality | Test/Review後 | バグなし、リリース可 |

### フィードバック形式

decision: approve/revise/reject, comments, priority, affected_agents

### タイムアウト処理

24h → リマインド、72h → エスカレーション、7日 → 自動一時停止

## 5. ログ/監視方針

### ログレベル

| Level | 用途 |
|-------|------|
| DEBUG | 開発時詳細 (プロンプト全文等) |
| INFO | 正常処理フロー |
| WARNING | リトライ発生、タイムアウト接近 |
| ERROR | 処理失敗 (リカバリ可能) |
| CRITICAL | 致命的エラー (要介入) |

### 監視メトリクス

| メトリクス | アラート閾値 |
|-----------|-------------|
| agent_duration_p95 | > 30秒 |
| agent_success_rate | < 95% |
| human_wait_time_avg | > 24時間 |
| token_usage_daily | > 100万 |
| retry_rate | > 10% |

## 6. バージョニング戦略

### セマンティックバージョニング

MAJOR.MINOR.PATCH

| 変更種別 | バージョン |
|---------|-----------|
| バグ修正 | PATCH |
| 新Agent追加 | MINOR |
| State schema変更 | MAJOR |
| プロンプト改善 | PATCH (別管理) |

### コンポーネント別バージョン

各agents/, prompts/, state/ にVERSIONファイル配置。

State Schemaは`_schema_version`フィールドで管理、マイグレーション対応。

## 7. Config管理

全設定値は `config.yaml` で一元管理。

### 設定項目

- **llm**: provider, model, temperature, max_tokens
- **retry**: rate_limit/timeout/invalid_response毎の設定
- **human**: timeout (reminder/escalation/auto_pause)
- **monitoring**: log_level, metrics, alerts
- **parallel**: max_concurrent_agents, timeout_per_agent
- **persistence**: backend, checkpoint_interval

### 環境別設定

config.yaml, config.dev.yaml, config.prod.yaml, config.test.yaml

環境変数 `ENV` で切り替え。
