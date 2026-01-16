# LangGraph Studio API仕様

バックエンドサーバーが実装すべきAPI仕様の一覧です。

## 概要

| プロトコル | 用途 |
|-----------|------|
| WebSocket (Socket.IO) | リアルタイム通信・状態更新 |
| REST API | CRUD操作・初期データ取得 |

---

## 1. WebSocket API (Socket.IO)

### 1.1 Server → Client イベント

#### Agent関連

| イベント名 | ペイロード | 説明 |
|-----------|-----------|------|
| `agent:started` | `AgentStartedEvent` | エージェント開始通知 |
| `agent:progress` | `AgentProgressEvent` | 進捗更新 |
| `agent:log` | `AgentLogEvent` | ログエントリ追加 |
| `agent:completed` | `AgentCompletedEvent` | エージェント完了 |
| `agent:failed` | `AgentFailedEvent` | エージェント失敗 |

```typescript
interface AgentStartedEvent {
  agentId: string
  agentType: AgentType
  projectId: string
  timestamp: string
}

interface AgentProgressEvent {
  agentId: string
  progress: number          // 0-100
  currentTask: string
  completedTasks: number
  totalTasks: number
  timestamp: string
}

interface AgentCompletedEvent {
  agentId: string
  duration: number          // ms
  tokensUsed: number
  outputSummary: string
  timestamp: string
}

interface AgentFailedEvent {
  agentId: string
  errorType: 'timeout' | 'llm_error' | 'validation_error' | 'dependency_error'
  errorMessage: string
  canRetry: boolean
  retryCount: number
  maxRetries: number
  timestamp: string
}

interface AgentLogEvent {
  agentId: string
  level: 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'
  message: string
  metadata?: Record<string, unknown>
  timestamp: string
}
```

#### Checkpoint関連

| イベント名 | ペイロード | 説明 |
|-----------|-----------|------|
| `checkpoint:created` | `CheckpointCreatedEvent` | 承認待ちチェックポイント作成 |
| `checkpoint:resolved` | `CheckpointResolvedEvent` | チェックポイント解決済み |

```typescript
interface CheckpointCreatedEvent {
  checkpointId: string
  projectId: string
  agentId: string
  checkpointType: CheckpointType
  title: string
  outputPreview: string
  timestamp: string
}

interface CheckpointResolvedEvent {
  checkpointId: string
  resolution: 'approved' | 'rejected' | 'changes_requested'
  feedback?: string
  timestamp: string
}
```

#### Project関連

| イベント名 | ペイロード | 説明 |
|-----------|-----------|------|
| `project:status_changed` | `ProjectStatusEvent` | ステータス変更 |
| `project:phase_changed` | `PhaseChangeEvent` | フェーズ変更 |

```typescript
interface ProjectStatusEvent {
  projectId: string
  oldStatus: ProjectStatus
  newStatus: ProjectStatus
  timestamp: string
}

interface PhaseChangeEvent {
  projectId: string
  phase: 1 | 2 | 3
  phaseName: string
  timestamp: string
}
```

#### Metrics関連

| イベント名 | ペイロード | 説明 |
|-----------|-----------|------|
| `metrics:update` | `MetricsUpdateEvent` | プロジェクトメトリクス更新 |
| `metrics:tokens` | `TokensUpdateEvent` | トークン使用量更新 |

```typescript
interface MetricsUpdateEvent {
  projectId: string
  totalTokens: number
  estimatedTotalTokens: number
  elapsedSeconds: number
  estimatedRemainingSeconds: number
  completedTasks: number
  totalTasks: number
  timestamp: string
}

interface TokensUpdateEvent {
  agentId: string
  tokensUsed: number
  tokensTotal: number
  timestamp: string
}
```

#### Error関連

| イベント名 | ペイロード | 説明 |
|-----------|-----------|------|
| `error:agent` | `AgentErrorEvent` | エージェントエラー |
| `error:llm` | `LLMErrorEvent` | LLMエラー |
| `error:state` | `StateErrorEvent` | 状態同期エラー |

```typescript
interface AgentErrorEvent {
  agentId: string
  errorType: string
  errorMessage: string
  suggestions: string[]
  actions: Array<{ label: string; action: string }>
  timestamp: string
}

interface LLMErrorEvent {
  errorType: 'rate_limit' | 'token_limit' | 'api_error' | 'invalid_response'
  errorMessage: string
  retryAfter?: number       // seconds
  timestamp: string
}

interface StateErrorEvent {
  errorType: 'sync_failed' | 'checkpoint_failed' | 'restore_failed'
  errorMessage: string
  timestamp: string
}
```

#### Connection関連

| イベント名 | ペイロード | 説明 |
|-----------|-----------|------|
| `connection:state_sync` | `StateSyncEvent` | 状態同期 |

```typescript
interface StateSyncEvent {
  projectId: string
  serverState: {
    currentAgent: string
    progress: number
    completedTasks: number
    totalTasks: number
  }
  hasDiff: boolean
  timestamp: string
}
```

### 1.2 Client → Server イベント

| イベント名 | ペイロード | 説明 |
|-----------|-----------|------|
| `subscribe:project` | `projectId: string` | プロジェクトの更新を購読 |
| `unsubscribe:project` | `projectId: string` | 購読解除 |
| `checkpoint:resolve` | `CheckpointResolution` | チェックポイントを解決 |

```typescript
interface CheckpointResolution {
  checkpointId: string
  resolution: 'approved' | 'rejected' | 'changes_requested'
  feedback?: string
}
```

---

## 2. REST API

### 2.1 Projects API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | `/api/projects` | プロジェクト一覧取得 |
| GET | `/api/projects/:id` | プロジェクト詳細取得 |
| POST | `/api/projects` | プロジェクト作成 |
| PATCH | `/api/projects/:id` | プロジェクト更新 |
| DELETE | `/api/projects/:id` | プロジェクト削除 |
| POST | `/api/projects/:id/start` | プロジェクト開始 |
| POST | `/api/projects/:id/pause` | プロジェクト一時停止 |
| POST | `/api/projects/:id/resume` | プロジェクト再開 |

#### リクエスト/レスポンス型

```typescript
// GET /api/projects/:id レスポンス
interface Project {
  id: string
  name: string
  description?: string
  concept?: GameConcept
  status: 'draft' | 'running' | 'paused' | 'completed' | 'failed'
  currentPhase: 1 | 2 | 3
  state?: Record<string, unknown>
  config?: ProjectConfig
  createdAt: string
  updatedAt: string
}

interface GameConcept {
  description: string
  platform: 'web' | 'desktop' | 'mobile'
  scope: 'mvp' | 'full'
  genre?: string
  targetAudience?: string
}

interface ProjectConfig {
  llmProvider?: 'claude' | 'gpt4'
  maxTokensPerAgent?: number
  enableAssetGeneration?: boolean
}

// POST /api/projects リクエスト
interface CreateProjectInput {
  name: string
  description?: string
  concept: GameConcept
  config?: ProjectConfig
}
```

### 2.2 Agents API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | `/api/projects/:projectId/agents` | プロジェクトのエージェント一覧 |
| GET | `/api/agents/:id` | エージェント詳細取得 |
| GET | `/api/agents/:id/logs` | エージェントログ取得 |
| GET | `/api/agents/:id/outputs` | エージェント出力取得 |
| GET | `/api/agents/:id/metrics` | エージェントメトリクス取得 |

#### リクエスト/レスポンス型

```typescript
interface Agent {
  id: string
  projectId: string
  type: AgentType
  status: 'pending' | 'running' | 'completed' | 'failed' | 'blocked'
  progress: number            // 0-100
  currentTask: string | null
  tokensUsed: number
  startedAt: string | null
  completedAt: string | null
  error: string | null
  parentAgentId: string | null
  metadata: Record<string, unknown>
  createdAt: string
}

type AgentType =
  // Phase 1
  | 'concept' | 'design' | 'scenario' | 'character' | 'world' | 'task_split'
  // Phase 2
  | 'code_leader' | 'asset_leader' | 'code_worker' | 'asset_worker'
  // Phase 3
  | 'integrator' | 'tester' | 'reviewer'

interface AgentLogEntry {
  id: string
  timestamp: string
  level: 'debug' | 'info' | 'warn' | 'error'
  message: string
  progress?: number
  metadata?: Record<string, unknown>
}

interface AgentMetrics {
  agentId: string
  agentType: AgentType
  status: AgentStatus
  progress: number
  currentTask: string | null
  tokensUsed: number
  tokensEstimated: number
  runtimeSeconds: number
  estimatedRemainingSeconds: number
  completedTasks: number
  totalTasks: number
  activeSubAgents: number
  subAgentMetrics: AgentMetrics[]
}

interface AgentOutput {
  id: string
  agentId: string
  outputType: OutputType
  content: Record<string, unknown> | null
  filePath: string | null
  tokensUsed: number
  generationTimeMs: number
  createdAt: string
}

type OutputType =
  // Phase 1
  | 'concept_doc' | 'design_doc' | 'scenario_doc' | 'character_specs' | 'world_design' | 'task_breakdown'
  // Phase 2
  | 'code' | 'asset_image' | 'asset_audio'
  // Phase 3
  | 'build_result' | 'test_result' | 'review_result'
```

### 2.3 Checkpoints API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | `/api/projects/:projectId/checkpoints` | チェックポイント一覧 |
| GET | `/api/checkpoints/:id` | チェックポイント詳細 |
| POST | `/api/checkpoints/:id/resolve` | チェックポイント解決 |

#### リクエスト/レスポンス型

```typescript
interface Checkpoint {
  id: string
  projectId: string
  agentId: string
  type: CheckpointType
  title: string
  description: string | null
  output: CheckpointOutput
  status: 'pending' | 'approved' | 'rejected' | 'revision_requested'
  feedback: string | null
  resolvedAt: string | null
  createdAt: string
  updatedAt: string
}

type CheckpointType =
  // Phase 1
  | 'concept_review' | 'design_review' | 'scenario_review' | 'character_review' | 'world_review' | 'task_split_review'
  // Phase 2
  | 'code_review' | 'asset_review' | 'integration_review'
  // Phase 3
  | 'test_review' | 'final_review' | 'release_decision'

interface CheckpointOutput {
  documentType?: string
  summary?: string
  content?: Record<string, unknown>
  tokensUsed?: number
  generationTimeMs?: number
  previewUrl?: string
}

// POST /api/checkpoints/:id/resolve リクエスト
interface ResolveCheckpointRequest {
  resolution: 'approved' | 'rejected' | 'revision_requested'
  feedback?: string
}
```

### 2.4 Metrics API

| メソッド | エンドポイント | 説明 |
|---------|---------------|------|
| GET | `/api/projects/:projectId/metrics` | プロジェクトメトリクス取得 |

```typescript
interface ProjectMetrics {
  projectId: string
  totalTokensUsed: number
  estimatedTotalTokens: number
  elapsedTimeSeconds: number
  estimatedRemainingSeconds: number
  estimatedEndTime: string | null
  completedTasks: number
  totalTasks: number
  progressPercent: number
  currentPhase: 1 | 2 | 3
  phaseName: string
}
```

---

## 3. 接続情報

### デフォルト設定

| 項目 | 値 |
|-----|-----|
| WebSocket URL | `ws://localhost:{port}` |
| REST API Base URL | `http://localhost:{port}/api` |
| 再接続最大試行回数 | 5 |
| 再接続初期遅延 | 1000ms |
| 再接続最大遅延 | 5000ms |
| 接続タイムアウト | 10000ms |

### トランスポート

Socket.IOは以下の優先順位でトランスポートを使用:
1. WebSocket
2. Polling (フォールバック)
