# Development Rules

## Design Principles

| Principle | Description |
|-----------|-------------|
| Single Responsibility | 1 Agent = 1 Task |
| Fine Granularity | 小さいAgentほど再利用・テスト・保守が容易 |
| Human Checkpoint | 不可逆アクションの前に`interrupt()` |
| Durable State | 数日〜数ヶ月後でも再開可能 |
| Parallel Execution | 依存関係のないAgentは並列実行 |

---

## Agent設計

### DO / DON'T

| ✅ DO | ❌ DON'T |
|-------|----------|
| 1つのAgentに1つの責務 | 複数タスクを詰め込む |
| 入出力を明確に型定義 | anyや曖昧な型を使う |
| 冪等性を保つ | 副作用に依存する |
| エラーは明示的に返す | 例外を握りつぶす |

### Agent間通信フォーマット

```python
class AgentMessage(BaseModel):
    agent_name: str
    status: Literal["success", "needs_revision", "error"]
    data: dict
    metadata: dict  # tokens_used, duration_ms, model
```

---

## コード規約

### 命名規則

| 対象 | 規則 | 例 |
|------|------|-----|
| Agent関数 | snake_case | `concept_agent()` |
| Agentクラス | PascalCase + Agent | `ConceptAgent` |
| State型 | PascalCase + State | `GameDevState` |
| 定数 | UPPER_SNAKE_CASE | `MAX_RETRIES` |

---

## 品質・テスト

### テストレベル

| Level | 対象 | 必須テスト |
|-------|------|-----------|
| Unit | 各Agent | 入出力の型チェック、エッジケース |
| Integration | Agent間連携 | State受け渡し、並列実行 |
| E2E | 全フロー | Planning→Dev→Qualityの一連 |

### エラーハンドリング

```python
class AgentError(Exception):
    def __init__(self, agent_name: str, message: str, recoverable: bool = True):
        self.agent_name = agent_name
        self.message = message
        self.recoverable = recoverable
```

---

## Human介入

### 承認基準

| Phase | 承認ポイント | 基準 |
|-------|------------|------|
| Planning | 各Agent後 | 方向性が正しいか |
| Development | 各Agent後 | コードが動作するか |
| Quality | Test/Review後 | リリース可能か |

### フィードバック形式

```python
class HumanFeedback(TypedDict):
    decision: Literal["approve", "revise", "reject"]
    comments: str
    priority: Literal["high", "medium", "low"]
    affected_agents: list[str]
```

### タイムアウト

| 経過時間 | アクション |
|---------|-----------|
| 24時間 | リマインド通知 |
| 72時間 | エスカレーション |
| 7日間 | 自動一時停止 |

---

## ログ/監視

### ログレベル

| Level | 用途 |
|-------|------|
| DEBUG | プロンプト全文、LLMレスポンス |
| INFO | Agent開始/終了、承認完了 |
| WARNING | リトライ発生、タイムアウト接近 |
| ERROR | LLM呼び出し失敗 |
| CRITICAL | 認証失敗、State破損 |

### 監視メトリクス

| メトリクス | アラート閾値 |
|-----------|-------------|
| agent_duration_p95 | > 30秒 |
| agent_success_rate | < 95% |
| human_wait_time_avg | > 24時間 |
| token_usage_daily | > 100万 |

---

## Config管理

設定は `config.yaml` で一元管理。

```yaml
llm:
  provider: "anthropic"
  model: "claude-3-opus"
  temperature: 0.7

retry:
  max_attempts: 3
  backoff: "exponential"
  base_delay_sec: 2