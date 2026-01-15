# Agent間通信プロトコル

## 概要

このドキュメントでは、Agent間のメッセージング標準を定義します。
全Agentは本プロトコルに準拠することで、一貫性のある通信を実現します。

---

## メッセージフォーマット

### 基本構造

```typescript
interface AgentMessage {
  // === ヘッダー ===
  header: {
    message_id: string;           // ユニークID (UUID v4)
    timestamp: string;            // ISO8601形式
    version: "1.0";               // プロトコルバージョン

    // 送受信者
    from: AgentIdentifier;
    to: AgentIdentifier;

    // メッセージ種別
    type: MessageType;
    correlation_id?: string;      // 返信時の元メッセージID
  };

  // === ペイロード ===
  payload: MessagePayload;

  // === メタデータ ===
  metadata?: {
    priority: "low" | "normal" | "high" | "critical";
    ttl_seconds?: number;         // 有効期限
    retry_count?: number;         // リトライ回数
  };
}

interface AgentIdentifier {
  agent_type: string;             // "orchestrator", "concept", etc.
  agent_id: string;               // インスタンスID
  role?: string;                  // "leader", "worker", etc.
}

type MessageType =
  | "request"           // 処理依頼
  | "response"          // 処理結果
  | "event"             // イベント通知
  | "error"             // エラー通知
  | "heartbeat"         // 生存確認
  | "control";          // 制御命令
```

### メッセージタイプ別ペイロード

#### Request（処理依頼）

```typescript
interface RequestPayload {
  action: string;                 // 実行アクション
  params: Record<string, any>;    // パラメータ
  context?: {
    iteration?: number;
    phase?: string;
    dependencies?: string[];
  };
  timeout_ms?: number;            // タイムアウト
}

// 例: Code LeaderからCode Agentへのタスク依頼
{
  header: {
    message_id: "msg_001",
    timestamp: "2024-01-15T10:00:00Z",
    version: "1.0",
    from: { agent_type: "code_leader", agent_id: "cl_001", role: "leader" },
    to: { agent_type: "code_agent", agent_id: "ca_system_001", role: "worker" },
    type: "request"
  },
  payload: {
    action: "implement",
    params: {
      task_id: "code_002",
      description: "InputSystemの実装",
      acceptance_criteria: ["WASDキー入力を処理", "イベント発火"],
      dependencies: ["EventBus"],
      output_path: "src/systems/InputSystem.ts"
    },
    context: {
      iteration: 1,
      phase: "development"
    },
    timeout_ms: 300000
  },
  metadata: {
    priority: "normal"
  }
}
```

#### Response（処理結果）

```typescript
interface ResponsePayload {
  status: "success" | "partial" | "failed";
  result?: any;                   // 成功時の結果
  error?: ErrorInfo;              // 失敗時のエラー情報
  metrics?: {
    duration_ms: number;
    tokens_used?: number;
  };
}

// 例: Code AgentからCode Leaderへの完了報告
{
  header: {
    message_id: "msg_002",
    timestamp: "2024-01-15T10:05:00Z",
    version: "1.0",
    from: { agent_type: "code_agent", agent_id: "ca_system_001" },
    to: { agent_type: "code_leader", agent_id: "cl_001" },
    type: "response",
    correlation_id: "msg_001"
  },
  payload: {
    status: "success",
    result: {
      files: [
        {
          path: "src/systems/InputSystem.ts",
          content: "...",
          lines: 120
        }
      ],
      tests: [
        {
          path: "src/systems/InputSystem.test.ts",
          content: "..."
        }
      ]
    },
    metrics: {
      duration_ms: 45000,
      tokens_used: 2500
    }
  }
}
```

#### Event（イベント通知）

```typescript
interface EventPayload {
  event_type: string;
  data: Record<string, any>;
  requires_action?: boolean;
}

// 例: Asset LeaderからCode Leaderへのアセット完成通知
{
  header: {
    message_id: "msg_003",
    timestamp: "2024-01-15T10:10:00Z",
    version: "1.0",
    from: { agent_type: "asset_leader", agent_id: "al_001" },
    to: { agent_type: "code_leader", agent_id: "cl_001" },
    type: "event"
  },
  payload: {
    event_type: "asset_ready",
    data: {
      asset_id: "asset_001",
      asset_path: "assets/sprites/player.png",
      version: "final",
      blocked_tasks: ["code_002", "code_005"]
    },
    requires_action: true
  },
  metadata: {
    priority: "high"
  }
}
```

#### Error（エラー通知）

```typescript
interface ErrorPayload {
  error_code: string;
  error_type: ErrorType;
  message: string;
  details?: Record<string, any>;
  recoverable: boolean;
  suggested_action?: string;
}

type ErrorType =
  | "validation"        // 入力検証エラー
  | "execution"         // 実行エラー
  | "timeout"           // タイムアウト
  | "dependency"        // 依存関係エラー
  | "resource"          // リソースエラー
  | "internal";         // 内部エラー

// 例: エラー通知
{
  header: {
    message_id: "msg_004",
    timestamp: "2024-01-15T10:15:00Z",
    version: "1.0",
    from: { agent_type: "code_agent", agent_id: "ca_system_001" },
    to: { agent_type: "code_leader", agent_id: "cl_001" },
    type: "error",
    correlation_id: "msg_001"
  },
  payload: {
    error_code: "E_DEPENDENCY_MISSING",
    error_type: "dependency",
    message: "依存モジュール 'EventBus' が見つかりません",
    details: {
      missing_dependency: "EventBus",
      expected_path: "src/core/EventBus.ts"
    },
    recoverable: true,
    suggested_action: "EventBusタスクの完了を待機"
  },
  metadata: {
    priority: "high"
  }
}
```

#### Control（制御命令）

```typescript
interface ControlPayload {
  command: ControlCommand;
  params?: Record<string, any>;
}

type ControlCommand =
  | "pause"             // 一時停止
  | "resume"            // 再開
  | "cancel"            // キャンセル
  | "retry"             // リトライ
  | "shutdown";         // 終了

// 例: キャンセル命令
{
  header: {
    message_id: "msg_005",
    type: "control",
    from: { agent_type: "orchestrator", agent_id: "orch_001" },
    to: { agent_type: "code_leader", agent_id: "cl_001" }
  },
  payload: {
    command: "cancel",
    params: {
      reason: "Human requested cancellation",
      affected_tasks: ["code_003", "code_004"]
    }
  },
  metadata: {
    priority: "critical"
  }
}
```

---

## 通信パターン

### 1. Request-Response（同期）

```
┌──────────┐                    ┌──────────┐
│  Agent A  │                    │  Agent B  │
└─────┬────┘                    └─────┬────┘
      │                               │
      │  ─────── Request ──────►      │
      │                               │
      │         [処理中...]           │
      │                               │
      │  ◄────── Response ─────       │
      │                               │
```

### 2. Fire-and-Forget（非同期通知）

```
┌──────────┐                    ┌──────────┐
│  Agent A  │                    │  Agent B  │
└─────┬────┘                    └─────┬────┘
      │                               │
      │  ─────── Event ────────►      │
      │  (ACK不要)                    │
      │                               │
```

### 3. Publish-Subscribe（ブロードキャスト）

```
┌──────────┐
│  Agent A  │
└─────┬────┘
      │
      │  ─────── Event ────────┬─────────────┐
      │                        │             │
      ▼                        ▼             ▼
┌──────────┐            ┌──────────┐   ┌──────────┐
│  Agent B  │            │  Agent C  │   │  Agent D  │
└──────────┘            └──────────┘   └──────────┘
```

### 4. Callback Chain（連鎖処理）

```
┌──────────┐    ┌──────────┐    ┌──────────┐
│  Agent A  │───►│  Agent B  │───►│  Agent C  │
└──────────┘    └──────────┘    └──────────┘
      ▲                               │
      │                               │
      └───────── Final Result ────────┘
```

---

## 通信フロー定義

### Orchestrator → Phase1 Agents

```
Orchestrator
     │
     │ Request: execute_phase1
     ▼
  Concept ─── Response ──►
     │
     │ Request: continue
     ▼
  Design ─── Response ──►
     │
     │ ...以下同様
```

### Code Leader ⇄ Asset Leader 連携

```
Code Leader                          Asset Leader
     │                                    │
     │ ─── Event: asset_request ────►     │
     │     { asset_id, priority }         │
     │                                    │
     │ ◄── Event: placeholder_ready ──    │
     │     { asset_id, temp_path }        │
     │                                    │
     │         [Code開発継続]              │
     │                                    │
     │ ◄── Event: asset_ready ────────    │
     │     { asset_id, final_path }       │
     │                                    │
     │ ─── Event: asset_integrated ──►    │
     │     { asset_id, status }           │
```

### エラーエスカレーション

```
SubAgent ──► Leader ──► Orchestrator ──► Human
   │           │            │
   │ Error     │ Error      │ Error
   │ (local)   │ (escalate) │ (escalate)
   │           │            │
   ▼           ▼            ▼
 [Retry]    [Retry]     [interrupt()]
 max 3      max 3       Human判断
```

---

## ACK/NACK プロトコル

### 確認応答

```typescript
interface AckMessage {
  header: {
    type: "ack" | "nack";
    correlation_id: string;       // 元メッセージID
  };
  payload: {
    received_at: string;
    nack_reason?: string;         // NACK時のみ
  };
}
```

### タイムアウト処理

```
送信側                           受信側
  │                                │
  │ ─────── Message ────────►      │
  │                                │
  │  [30秒タイムアウト]             │
  │                                │
  │ ◄─────── ACK ──────────        │
  │                                │
  │ (ACKなし → リトライ or エスカレーション)
```

### リトライポリシー

```typescript
const RETRY_POLICY = {
  max_retries: 3,
  initial_delay_ms: 1000,
  max_delay_ms: 30000,
  backoff_multiplier: 2,          // 指数バックオフ
  jitter: true,                   // ランダム要素追加
};

// リトライ間隔: 1s → 2s → 4s
```

---

## 優先度と順序保証

### 優先度レベル

| レベル | 用途 | 処理 |
|--------|------|------|
| `critical` | エラー、キャンセル | 即時処理、割り込み |
| `high` | ブロッキング解除 | 優先処理 |
| `normal` | 通常タスク | 順次処理 |
| `low` | バックグラウンド | 余剰時間で処理 |

### 順序保証

```typescript
interface OrderingGuarantee {
  // 同一送信者からの同一priority内は順序保証
  same_sender_same_priority: "ordered";

  // 異なるpriorityは順序保証なし（高優先が先）
  different_priority: "priority_based";

  // correlation_id付きは関連メッセージ後に処理
  correlated_messages: "after_correlation";
}
```

---

## セキュリティ考慮

### メッセージ検証

```typescript
function validateMessage(msg: AgentMessage): ValidationResult {
  // 必須フィールド確認
  if (!msg.header?.message_id || !msg.header?.from || !msg.header?.to) {
    return { valid: false, error: "Missing required header fields" };
  }

  // バージョン確認
  if (msg.header.version !== "1.0") {
    return { valid: false, error: "Unsupported protocol version" };
  }

  // 送信者権限確認
  if (!isAuthorizedSender(msg.header.from, msg.header.to, msg.header.type)) {
    return { valid: false, error: "Unauthorized sender" };
  }

  // ペイロードサイズ制限
  if (JSON.stringify(msg.payload).length > MAX_PAYLOAD_SIZE) {
    return { valid: false, error: "Payload too large" };
  }

  return { valid: true };
}
```

### 権限マトリクス

| 送信者 | 受信者 | 許可メッセージ |
|--------|--------|---------------|
| Orchestrator | 全Agent | request, control |
| Leader | SubAgent | request, control |
| Leader | Leader | event |
| SubAgent | Leader | response, error |
| SubAgent | SubAgent | なし（直接通信禁止） |

---

## モニタリング・ログ

### メッセージログ形式

```typescript
interface MessageLog {
  timestamp: string;
  message_id: string;
  direction: "sent" | "received";
  from: string;
  to: string;
  type: MessageType;
  status: "success" | "failed" | "timeout";
  latency_ms?: number;
  error?: string;
}

// 例
{
  timestamp: "2024-01-15T10:00:00.123Z",
  message_id: "msg_001",
  direction: "sent",
  from: "code_leader:cl_001",
  to: "code_agent:ca_system_001",
  type: "request",
  status: "success",
  latency_ms: 45
}
```

### メトリクス

```typescript
interface CommunicationMetrics {
  messages_sent: number;
  messages_received: number;
  avg_latency_ms: number;
  error_rate: number;
  retry_rate: number;
  timeout_rate: number;

  by_type: Record<MessageType, number>;
  by_agent: Record<string, number>;
}
```
