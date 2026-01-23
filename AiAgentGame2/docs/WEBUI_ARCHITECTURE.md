# WebUI Architecture Specification

## システムアーキテクチャ

本ドキュメントはLangGraph Game Development SystemのWebUIアーキテクチャを定義する。

---

## 1. Architecture Overview

### 1.1 System Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              SYSTEM ARCHITECTURE                                 │
└─────────────────────────────────────────────────────────────────────────────────┘

                                    ┌─────────────┐
                                    │   Browser   │
                                    │  (WebUI)    │
                                    └──────┬──────┘
                                           │
                                           │ HTTPS / WSS
                                           │
                    ┌──────────────────────┴──────────────────────┐
                    │                                             │
                    ▼                                             ▼
           ┌───────────────┐                            ┌─────────────────┐
           │  REST API     │                            │  WebSocket      │
           │  (FastAPI)    │                            │  Server         │
           │               │                            │  (Real-time)    │
           └───────┬───────┘                            └────────┬────────┘
                   │                                             │
                   └──────────────────┬──────────────────────────┘
                                      │
                                      ▼
                          ┌───────────────────────┐
                          │   Service Layer       │
                          │   ─────────────────   │
                          │   - Project Service   │
                          │   - Agent Service     │
                          │   - Checkpoint Svc    │
                          │   - Metrics Service   │
                          └───────────┬───────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
   ┌─────────────────┐     ┌─────────────────┐      ┌─────────────────┐
   │  LangGraph      │     │  State Manager  │      │  File Storage   │
   │  Orchestrator   │     │  (SQLite/       │      │  (Local)        │
   │                 │     │   Checkpoint)   │      │                 │
   └─────────────────┘     └─────────────────┘      └─────────────────┘
```

### 1.2 Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | React 18 + TypeScript | UI Framework |
| | Vite | Build Tool |
| | Electron | Desktop Application |
| | Tailwind CSS | Styling (NieR theme) |
| | Zustand | State Management |
| | React Query | Server State / Caching (予定) |
| | Socket.io Client | Real-time Communication |
| **Backend** | FastAPI (Python) | REST API Server |
| | Socket.io | WebSocket Server |
| | LangGraph | Agent Orchestration |
| **Storage** | SQLite | Persistent Storage |
| | File System | Asset/Output Storage |

---

## 2. Frontend Architecture

### 2.1 Component Structure

```
src/
├── main.tsx                    # Entry point
├── App.tsx                     # Root component with routing
│
├── views/                      # Page-level components
│   ├── index.ts
│   ├── ProjectView.tsx         # Project dashboard
│   ├── AgentsView.tsx          # Agent list view
│   ├── CheckpointsView.tsx     # Checkpoint list view
│   ├── LogsView.tsx            # System logs view
│   ├── DataView.tsx            # Data/outputs view
│   ├── CostView.tsx            # Cost tracking view
│   └── ConfigView.tsx          # Settings view
│
├── components/
│   ├── ui/                     # Base UI components (NieR styled)
│   │   ├── index.ts
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── Progress.tsx
│   │   ├── CategoryMarker.tsx
│   │   └── DiamondMarker.tsx
│   │   # 予定: Panel, Input, Select, Badge, Modal, Toast
│   │
│   ├── layout/                 # Layout components
│   │   ├── AppLayout.tsx
│   │   ├── HeaderTabs.tsx
│   │   ├── Footer.tsx
│   │   └── ConnectionStatus.tsx
│   │
│   ├── dashboard/              # Dashboard specific
│   │   ├── DashboardView.tsx
│   │   ├── ProjectStatus.tsx
│   │   ├── ActiveAgents.tsx
│   │   ├── PendingApprovals.tsx
│   │   ├── MetricsOverview.tsx
│   │   ├── PhaseProgress.tsx
│   │   ├── TaskList.tsx
│   │   └── AssetStatus.tsx
│   │
│   ├── agents/                 # Agent related
│   │   ├── index.ts
│   │   ├── AgentCard.tsx
│   │   ├── AgentDetailView.tsx
│   │   ├── AgentListView.tsx
│   │   └── AgentLog.tsx
│   │   # 予定: AgentMetrics, SubAgentList, TaskQueue
│   │
│   ├── checkpoints/            # Human checkpoint
│   │   ├── index.ts
│   │   ├── CheckpointCard.tsx
│   │   ├── CheckpointListView.tsx
│   │   ├── CheckpointReviewView.tsx
│   │   ├── FeedbackForm.tsx
│   │   └── ApprovalButtons.tsx
│   │
│   ├── viewers/                # Output viewers
│   │   ├── DocumentViewer.tsx
│   │   └── CodeViewer.tsx
│   │   # 予定: AssetViewer, TestResultViewer
│   │
│   ├── analytics/              # Analytics & cost tracking
│   │   ├── index.ts
│   │   ├── TokenTracker.tsx
│   │   ├── CostEstimator.tsx
│   │   └── DependencyGraph.tsx
│   │
│   ├── errors/                 # Error handling (予定)
│   │   ├── ErrorPanel.tsx
│   │   ├── ErrorToast.tsx
│   │   ├── ConnectionOverlay.tsx
│   │   └── RecoveryModal.tsx
│   │
│   └── project/                # Project related (予定)
│       ├── ProjectCard.tsx
│       ├── ProjectForm.tsx
│       └── ProjectTimeline.tsx
│
├── stores/                     # Zustand stores
│   ├── index.ts
│   ├── projectStore.ts
│   ├── agentStore.ts
│   ├── checkpointStore.ts
│   ├── metricsStore.ts
│   └── connectionStore.ts
│
├── services/                   # API services
│   └── websocketService.ts     # WebSocket + Store連携
│
├── types/                      # TypeScript types
│   ├── index.ts
│   ├── project.ts
│   ├── agent.ts
│   ├── checkpoint.ts
│   └── websocket.ts
│
├── styles/                     # Global styles
│   └── index.css               # Tailwind + NieR theme
│
└── lib/                        # Utilities
    └── utils.ts
```

### 2.1.1 Electron Structure

```
electron/
├── main.ts                     # Electron main process
├── preload.ts                  # Preload script (IPC bridge)
└── backend/
    └── manager.ts              # Backend process manager
```

### 2.2 State Management

```typescript
// stores/projectStore.ts
interface ProjectState {
  // Data
  currentProject: Project | null;
  projects: Project[];

  // UI State
  isLoading: boolean;
  error: string | null;

  // Actions
  fetchProjects: () => Promise<void>;
  fetchProject: (id: string) => Promise<void>;
  createProject: (data: CreateProjectDTO) => Promise<Project>;
  startProject: (id: string) => Promise<void>;
  pauseProject: (id: string) => Promise<void>;
  resumeProject: (id: string) => Promise<void>;
}

// stores/agentStore.ts
interface AgentState {
  // Data
  agents: Record<string, Agent>;          // agentId -> agent
  activeAgents: Agent[];
  agentLogs: Record<string, LogEntry[]>;  // agentId -> logs

  // Real-time updates
  subscribeToAgent: (agentId: string) => void;
  unsubscribeFromAgent: (agentId: string) => void;

  // Actions
  fetchAgents: (projectId: string) => Promise<void>;
  getAgentDetail: (agentId: string) => Promise<Agent>;
}

// stores/metricsStore.ts
interface MetricsState {
  // Project metrics
  projectMetrics: {
    totalTokens: number;
    estimatedTotalTokens: number;
    elapsedTime: number;
    estimatedRemainingTime: number;
    estimatedEndTime: Date | null;
    completedTasks: number;
    totalTasks: number;
  };

  // Agent metrics
  agentMetrics: Record<string, {
    tokens: number;
    runtime: number;
    progress: number;
    currentTask: string;
  }>;

  // Actions
  updateMetrics: (metrics: Partial<MetricsState>) => void;
}

// stores/connectionStore.ts
interface ConnectionState {
  // Status
  status: 'connected' | 'reconnecting' | 'disconnected';
  reconnectAttempts: number;
  lastConnectedAt: Date | null;

  // State sync
  serverState: any | null;
  localState: any | null;
  hasDiff: boolean;

  // Actions
  setStatus: (status: ConnectionState['status']) => void;
  incrementReconnectAttempts: () => void;
  resetReconnectAttempts: () => void;
  syncWithServer: () => Promise<void>;
}
```

### 2.3 WebSocket Integration

```typescript
// services/websocketService.ts

interface WebSocketEvents {
  // Project Events
  'project:status_changed': (data: ProjectStatusEvent) => void;
  'project:phase_changed': (data: PhaseChangeEvent) => void;

  // Agent Events
  'agent:started': (data: AgentStartedEvent) => void;
  'agent:progress': (data: AgentProgressEvent) => void;
  'agent:completed': (data: AgentCompletedEvent) => void;
  'agent:failed': (data: AgentFailedEvent) => void;
  'agent:log': (data: AgentLogEvent) => void;

  // Checkpoint Events
  'checkpoint:created': (data: CheckpointCreatedEvent) => void;
  'checkpoint:resolved': (data: CheckpointResolvedEvent) => void;

  // Metrics Events
  'metrics:update': (data: MetricsUpdateEvent) => void;
  'metrics:tokens': (data: TokensUpdateEvent) => void;

  // Error Events
  'error:agent': (data: AgentErrorEvent) => void;
  'error:llm': (data: LLMErrorEvent) => void;
  'error:state': (data: StateErrorEvent) => void;

  // Connection Events
  'connection:state_sync': (data: StateSyncEvent) => void;
}

class WebSocketService {
  private socket: Socket;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;
  private reconnectDelay: number = 1000; // Exponential backoff

  connect(): void {
    this.socket = io(WS_URL, {
      transports: ['websocket'],
      reconnection: true,
      reconnectionDelay: this.reconnectDelay,
      reconnectionDelayMax: 16000, // Max 16 seconds
      reconnectionAttempts: this.maxReconnectAttempts,
    });

    this.setupEventListeners();
    this.setupReconnectionHandlers();
  }

  private setupReconnectionHandlers(): void {
    this.socket.on('disconnect', (reason) => {
      connectionStore.setStatus('reconnecting');
      console.log('Disconnected:', reason);
    });

    this.socket.on('reconnect_attempt', (attemptNumber) => {
      connectionStore.incrementReconnectAttempts();
      console.log('Reconnect attempt:', attemptNumber);
    });

    this.socket.on('reconnect', () => {
      connectionStore.setStatus('connected');
      connectionStore.resetReconnectAttempts();
      // Request state sync
      this.requestStateSync();
    });

    this.socket.on('reconnect_failed', () => {
      connectionStore.setStatus('disconnected');
      // Show manual reconnect UI
    });
  }

  private requestStateSync(): void {
    this.socket.emit('request:state_sync', {
      projectId: projectStore.currentProject?.id
    });
  }

  // Subscribe to project-specific events
  subscribeToProject(projectId: string): void {
    this.socket.emit('subscribe:project', { projectId });
  }

  // Subscribe to agent-specific events
  subscribeToAgent(agentId: string): void {
    this.socket.emit('subscribe:agent', { agentId });
  }

  // Manual reconnect
  manualReconnect(): void {
    this.reconnectAttempts = 0;
    this.socket.connect();
  }

  // Event listeners
  on<K extends keyof WebSocketEvents>(
    event: K,
    callback: WebSocketEvents[K]
  ): void {
    this.socket.on(event, callback);
  }
}
```

---

## 3. Backend Architecture

### 3.1 API Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application entry
│   ├── config.py               # Configuration
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py             # Dependency injection
│   │   ├── router.py           # API router aggregation
│   │   │
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── projects.py     # Project endpoints
│   │       ├── agents.py       # Agent endpoints
│   │       ├── checkpoints.py  # Checkpoint endpoints
│   │       ├── metrics.py      # Metrics endpoints
│   │       ├── outputs.py      # Output viewer endpoints
│   │       └── websocket.py    # WebSocket handlers
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── agent.py
│   │   ├── checkpoint.py
│   │   ├── metrics.py
│   │   └── log.py
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── agent.py
│   │   ├── checkpoint.py
│   │   ├── metrics.py
│   │   └── websocket.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── project_service.py
│   │   ├── agent_service.py
│   │   ├── checkpoint_service.py
│   │   ├── metrics_service.py
│   │   └── state_service.py
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── graph.py            # LangGraph definition
│   │   ├── state.py            # State management
│   │   ├── nodes/              # Agent nodes
│   │   └── callbacks/          # Progress callbacks
│   │
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
│
└── tests/
```

### 3.2 API Endpoints & WebSocket Events

**→ [WebUI_API.md](./WebUI_API.md) を参照**

REST APIエンドポイントおよびWebSocketイベントの詳細仕様は `WebUI_API.md` に記載。

---

## 4. Database Schema

### 4.1 Tables

```sql
-- Projects table
CREATE TABLE projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    concept TEXT,                -- User's initial game concept (JSON)
    status TEXT DEFAULT 'draft', -- draft, running, paused, completed, failed
    current_phase INTEGER DEFAULT 0,
    state TEXT DEFAULT '{}',     -- LangGraph state snapshot (JSON)
    config TEXT DEFAULT '{}',    -- Project config (JSON)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agents table
CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type TEXT NOT NULL,          -- concept, design, code_leader, etc.
    status TEXT DEFAULT 'pending', -- pending, running, completed, failed
    progress INTEGER DEFAULT 0,  -- 0-100
    current_task TEXT,
    tokens_used INTEGER DEFAULT 0,
    started_at TIMESTAMP,
    completed_at TIMESTAMP,
    error TEXT,
    parent_agent_id TEXT REFERENCES agents(id),
    metadata TEXT DEFAULT '{}',  -- JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Checkpoints table
CREATE TABLE checkpoints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    type TEXT NOT NULL,          -- concept_review, design_review, etc.
    title TEXT NOT NULL,
    description TEXT,
    output TEXT NOT NULL,        -- Agent output to review (JSON)
    status TEXT DEFAULT 'pending', -- pending, approved, rejected, changes_requested
    feedback TEXT,
    resolved_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agent logs table
CREATE TABLE agent_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    level TEXT NOT NULL,         -- DEBUG, INFO, WARN, ERROR
    message TEXT NOT NULL,
    metadata TEXT,               -- JSON
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Agent outputs table
CREATE TABLE agent_outputs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    output_type TEXT NOT NULL,   -- concept_doc, design_doc, code, asset, test_result
    content TEXT,                -- JSON content
    file_path TEXT,              -- For file-based outputs
    tokens_used INTEGER DEFAULT 0,
    generation_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Metrics history table
CREATE TABLE metrics_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id TEXT REFERENCES agents(id),
    total_tokens INTEGER,
    elapsed_seconds INTEGER,
    completed_tasks INTEGER,
    total_tasks INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes
CREATE INDEX idx_agents_project_id ON agents(project_id);
CREATE INDEX idx_agents_status ON agents(status);
CREATE INDEX idx_checkpoints_project_id ON checkpoints(project_id);
CREATE INDEX idx_checkpoints_status ON checkpoints(status);
CREATE INDEX idx_agent_logs_agent_id ON agent_logs(agent_id);
CREATE INDEX idx_agent_logs_timestamp ON agent_logs(timestamp);
CREATE INDEX idx_agent_outputs_agent_id ON agent_outputs(agent_id);
CREATE INDEX idx_metrics_history_project_id ON metrics_history(project_id);
```

---

## 5. Real-time Communication

### 5.1 WebSocket Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     WEBSOCKET ARCHITECTURE                                   │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────────────────┐
                              │      WebSocket Server       │
                              │      (Socket.io)            │
                              └──────────────┬──────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
                    ▼                        ▼                        ▼
           ┌────────────────┐      ┌────────────────┐      ┌────────────────┐
           │   Room:        │      │   Room:        │      │   Room:        │
           │   project:123  │      │   project:456  │      │   agent:789    │
           │                │      │                │      │                │
           │  Subscribers:  │      │  Subscribers:  │      │  Subscribers:  │
           │  - Client A    │      │  - Client B    │      │  - Client A    │
           └───────┬────────┘      └───────┬────────┘      └───────┬────────┘
                   │                       │                       │
                   └───────────────────────┼───────────────────────┘
                                           │
                                           ▼
                              ┌─────────────────────────────┐
                              │   LangGraph Orchestrator    │
                              │   (Event Publisher)         │
                              └─────────────────────────────┘
```

### 5.2 Connection Management

```python
# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self.client_rooms: Dict[str, Set[str]] = defaultdict(set)  # client_id -> rooms

    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id].add(websocket)

    async def disconnect(self, websocket: WebSocket, client_id: str):
        self.active_connections[client_id].discard(websocket)
        # Unsubscribe from all rooms
        for room in self.client_rooms[client_id]:
            await self._leave_room(client_id, room)
        self.client_rooms[client_id].clear()

    async def subscribe_to_project(self, client_id: str, project_id: str):
        room = f"project:{project_id}"
        self.client_rooms[client_id].add(room)

    async def subscribe_to_agent(self, client_id: str, agent_id: str):
        room = f"agent:{agent_id}"
        self.client_rooms[client_id].add(room)

    async def broadcast_to_project(self, project_id: str, message: dict):
        room = f"project:{project_id}"
        await self._broadcast_to_room(room, message)

    async def broadcast_to_agent(self, agent_id: str, message: dict):
        room = f"agent:{agent_id}"
        await self._broadcast_to_room(room, message)

    async def _broadcast_to_room(self, room: str, message: dict):
        for client_id, rooms in self.client_rooms.items():
            if room in rooms:
                for connection in self.active_connections[client_id]:
                    await connection.send_json(message)
```

---

## 6. Resilience & Recovery

### 6.1 State Persistence

```python
# State checkpointing for recovery
class StateManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.checkpoint_interval = 30  # seconds

    async def save_checkpoint(self, project_id: str, state: dict):
        """Save state checkpoint for recovery."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE projects
                SET state = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (json.dumps(state), project_id))
            await db.commit()

    async def restore_state(self, project_id: str) -> dict:
        """Restore state from last checkpoint."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT state FROM projects WHERE id = ?",
                (project_id,)
            )
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else {}

    async def get_state_diff(
        self,
        project_id: str,
        client_state: dict
    ) -> dict:
        """Compare client state with server state."""
        server_state = await self.restore_state(project_id)
        return {
            'server': {
                'currentAgent': server_state.get('current_agent'),
                'progress': server_state.get('progress', 0),
                'completedTasks': len(server_state.get('completed_tasks', [])),
                'totalTasks': server_state.get('total_tasks', 0),
            },
            'client': client_state,
            'hasDiff': server_state != client_state
        }
```

### 6.2 Connection Recovery Flow

```python
# WebSocket reconnection handler
class ReconnectionHandler:
    def __init__(self, ws_manager: ConnectionManager, state_manager: StateManager):
        self.ws_manager = ws_manager
        self.state_manager = state_manager

    async def handle_reconnection(
        self,
        client_id: str,
        project_id: str,
        last_known_state: dict
    ):
        """Handle client reconnection and state sync."""

        # Get current server state
        server_state = await self.state_manager.restore_state(project_id)

        # Calculate diff
        diff = await self.state_manager.get_state_diff(
            project_id,
            last_known_state
        )

        # Send state sync event
        await self.ws_manager.send_to_client(client_id, {
            'event': 'connection:state_sync',
            'data': {
                'projectId': project_id,
                'serverState': diff['server'],
                'hasDiff': diff['hasDiff'],
                'timestamp': datetime.utcnow().isoformat()
            }
        })

        # Re-subscribe to project
        await self.ws_manager.subscribe_to_project(client_id, project_id)

        # If project is running, subscribe to active agents
        if server_state.get('status') == 'running':
            active_agents = server_state.get('active_agents', [])
            for agent_id in active_agents:
                await self.ws_manager.subscribe_to_agent(client_id, agent_id)
```

### 6.3 Error Recovery

```python
# Error recovery strategies
class ErrorRecovery:
    RETRY_CONFIG = {
        'llm_error': {
            'max_retries': 3,
            'base_delay': 2.0,
            'max_delay': 30.0,
            'exponential_base': 2
        },
        'timeout': {
            'max_retries': 2,
            'base_delay': 5.0,
            'max_delay': 30.0,
            'exponential_base': 2
        },
        'rate_limit': {
            'max_retries': 5,
            'base_delay': 60.0,  # Wait longer for rate limits
            'max_delay': 300.0,
            'exponential_base': 2
        }
    }

    async def handle_error(
        self,
        error_type: str,
        agent_id: str,
        task: dict,
        retry_count: int
    ) -> dict:
        """Handle error and determine recovery action."""

        config = self.RETRY_CONFIG.get(error_type, {})
        max_retries = config.get('max_retries', 3)

        if retry_count < max_retries:
            # Calculate delay with exponential backoff
            delay = min(
                config.get('base_delay', 2.0) *
                (config.get('exponential_base', 2) ** retry_count),
                config.get('max_delay', 30.0)
            )

            return {
                'action': 'retry',
                'delay': delay,
                'retryCount': retry_count + 1,
                'maxRetries': max_retries
            }
        else:
            # Max retries exceeded, escalate to human
            return {
                'action': 'escalate',
                'reason': f'Max retries ({max_retries}) exceeded',
                'suggestions': [
                    'Retry the task manually',
                    'Skip this task and continue',
                    'Pause the project'
                ]
            }
```

---

## 7. Metrics Collection

### 7.1 Metrics Schema

```typescript
// Types for metrics

interface ProjectMetrics {
  projectId: string;

  // Token metrics
  totalTokensUsed: number;
  estimatedTotalTokens: number;
  tokensByAgent: Record<string, number>;

  // Time metrics
  elapsedTimeSeconds: number;
  estimatedRemainingSeconds: number;
  estimatedEndTime: string; // ISO8601

  // Progress metrics
  completedTasks: number;
  totalTasks: number;
  progressPercent: number;

  // Phase metrics
  currentPhase: number;
  phaseName: string;
  phaseProgress: number;
}

interface AgentMetrics {
  agentId: string;
  agentType: string;

  // Status
  status: 'pending' | 'running' | 'completed' | 'failed';
  progress: number;
  currentTask: string;

  // Token metrics
  tokensUsed: number;
  tokensEstimated: number;

  // Time metrics
  runtimeSeconds: number;
  estimatedRemainingSeconds: number;

  // Task metrics
  completedTasks: number;
  totalTasks: number;

  // Sub-agents
  activeSubAgents: number;
  subAgentMetrics: AgentMetrics[];
}
```

### 7.2 Metrics Calculation

```python
# Metrics service
class MetricsService:
    def __init__(self, db):
        self.db = db

    async def calculate_project_metrics(self, project_id: str) -> dict:
        """Calculate comprehensive project metrics."""

        # Get all agents for project
        agents = await self.db.get_agents(project_id)

        # Calculate token totals
        total_tokens = sum(a.tokens_used for a in agents)

        # Estimate remaining tokens based on historical data
        completed_agents = [a for a in agents if a.status == 'completed']
        if completed_agents:
            avg_tokens_per_agent = total_tokens / len(completed_agents)
            remaining_agents = len(agents) - len(completed_agents)
            estimated_remaining_tokens = avg_tokens_per_agent * remaining_agents
        else:
            estimated_remaining_tokens = total_tokens * 2  # Initial estimate

        # Calculate time metrics
        start_time = min(a.started_at for a in agents if a.started_at)
        elapsed_seconds = (datetime.utcnow() - start_time).total_seconds()

        # Estimate remaining time
        if completed_agents:
            avg_time_per_agent = elapsed_seconds / len(completed_agents)
            remaining_agents = len(agents) - len(completed_agents)
            estimated_remaining_seconds = avg_time_per_agent * remaining_agents
        else:
            estimated_remaining_seconds = elapsed_seconds * 2

        # Calculate progress
        completed_tasks = sum(a.completed_tasks for a in agents)
        total_tasks = sum(a.total_tasks for a in agents)
        progress_percent = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0

        return {
            'projectId': project_id,
            'totalTokensUsed': total_tokens,
            'estimatedTotalTokens': total_tokens + estimated_remaining_tokens,
            'elapsedTimeSeconds': int(elapsed_seconds),
            'estimatedRemainingSeconds': int(estimated_remaining_seconds),
            'estimatedEndTime': (
                datetime.utcnow() +
                timedelta(seconds=estimated_remaining_seconds)
            ).isoformat(),
            'completedTasks': completed_tasks,
            'totalTasks': total_tasks,
            'progressPercent': round(progress_percent, 1)
        }

    async def calculate_agent_metrics(self, agent_id: str) -> dict:
        """Calculate metrics for a specific agent."""

        agent = await self.db.get_agent(agent_id)
        sub_agents = await self.db.get_sub_agents(agent_id)

        runtime = 0
        if agent.started_at:
            end_time = agent.completed_at or datetime.utcnow()
            runtime = (end_time - agent.started_at).total_seconds()

        return {
            'agentId': agent_id,
            'agentType': agent.type,
            'status': agent.status,
            'progress': agent.progress,
            'currentTask': agent.current_task,
            'tokensUsed': agent.tokens_used,
            'runtimeSeconds': int(runtime),
            'completedTasks': agent.completed_tasks,
            'totalTasks': agent.total_tasks,
            'activeSubAgents': len([s for s in sub_agents if s.status == 'running']),
            'subAgentMetrics': [
                await self.calculate_agent_metrics(s.id)
                for s in sub_agents
            ]
        }
```

---

## 8. Error Handling

### 8.1 Error Categories

```python
# Error type definitions
class ErrorCategory(Enum):
    CONNECTION = "connection"
    LLM = "llm"
    AGENT = "agent"
    STATE = "state"
    USER = "user"

class ErrorType(Enum):
    # Connection errors
    WEBSOCKET_DISCONNECT = "websocket_disconnect"
    SERVER_UNREACHABLE = "server_unreachable"
    NETWORK_TIMEOUT = "network_timeout"

    # LLM errors
    API_ERROR = "api_error"
    RATE_LIMIT = "rate_limit"
    TOKEN_LIMIT = "token_limit"
    INVALID_RESPONSE = "invalid_response"

    # Agent errors
    TASK_FAILED = "task_failed"
    DEPENDENCY_ERROR = "dependency_error"
    TIMEOUT = "timeout"
    VALIDATION_ERROR = "validation_error"

    # State errors
    SYNC_FAILED = "sync_failed"
    CHECKPOINT_FAILED = "checkpoint_failed"
    RESTORE_FAILED = "restore_failed"

    # User errors
    INPUT_VALIDATION = "input_validation"
    RESOURCE_NOT_FOUND = "resource_not_found"
```

### 8.2 Error Response Format

```python
# Error response schema
class ErrorResponse(BaseModel):
    error: ErrorDetail

class ErrorDetail(BaseModel):
    code: str                    # Error code (e.g., "AGENT_TIMEOUT")
    category: ErrorCategory      # Error category
    type: ErrorType             # Specific error type
    message: str                 # Human-readable message
    details: Optional[dict]      # Additional details
    suggestions: List[str]       # Suggested actions
    actions: List[ErrorAction]   # Available actions
    timestamp: datetime
    requestId: Optional[str]

class ErrorAction(BaseModel):
    label: str                   # Button label (e.g., "Retry")
    action: str                  # Action identifier (e.g., "retry_task")
    data: Optional[dict]         # Action parameters
```

### 8.3 Error Handling in WebSocket

```python
# WebSocket error broadcasting
async def broadcast_error(
    ws_manager: ConnectionManager,
    project_id: str,
    error: Exception,
    context: dict
):
    """Broadcast error to all subscribers."""

    error_response = create_error_response(error, context)

    await ws_manager.broadcast_to_project(project_id, {
        'event': f'error:{error_response.error.category.value}',
        'data': error_response.dict()
    })
```

---

## 9. LangGraph Integration

### 9.1 Progress Callback

```python
# LangGraph callback for WebUI updates
class WebUIProgressCallback:
    def __init__(
        self,
        project_id: str,
        ws_manager: ConnectionManager,
        metrics_service: MetricsService
    ):
        self.project_id = project_id
        self.ws_manager = ws_manager
        self.metrics_service = metrics_service

    async def on_agent_start(self, agent_id: str, agent_type: str):
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                'event': 'agent:started',
                'data': {
                    'agentId': agent_id,
                    'agentType': agent_type,
                    'projectId': self.project_id,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
        )

    async def on_agent_progress(
        self,
        agent_id: str,
        progress: int,
        current_task: str,
        completed_tasks: int,
        total_tasks: int
    ):
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                'event': 'agent:progress',
                'data': {
                    'agentId': agent_id,
                    'progress': progress,
                    'currentTask': current_task,
                    'completedTasks': completed_tasks,
                    'totalTasks': total_tasks,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
        )

        # Also broadcast to agent-specific room
        await self.ws_manager.broadcast_to_agent(agent_id, {
            'event': 'agent:progress',
            'data': {
                'agentId': agent_id,
                'progress': progress,
                'currentTask': current_task,
                'timestamp': datetime.utcnow().isoformat()
            }
        })

    async def on_agent_complete(
        self,
        agent_id: str,
        duration: float,
        tokens_used: int,
        output_summary: str
    ):
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                'event': 'agent:completed',
                'data': {
                    'agentId': agent_id,
                    'duration': duration,
                    'tokensUsed': tokens_used,
                    'outputSummary': output_summary,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
        )

        # Update metrics
        metrics = await self.metrics_service.calculate_project_metrics(
            self.project_id
        )
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                'event': 'metrics:update',
                'data': metrics
            }
        )

    async def on_agent_error(
        self,
        agent_id: str,
        error_type: str,
        error_message: str,
        can_retry: bool,
        retry_count: int,
        max_retries: int
    ):
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                'event': 'agent:failed',
                'data': {
                    'agentId': agent_id,
                    'errorType': error_type,
                    'errorMessage': error_message,
                    'canRetry': can_retry,
                    'retryCount': retry_count,
                    'maxRetries': max_retries,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
        )

    async def on_checkpoint_created(
        self,
        checkpoint_id: str,
        agent_id: str,
        checkpoint_type: str,
        title: str,
        output_preview: str
    ):
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                'event': 'checkpoint:created',
                'data': {
                    'checkpointId': checkpoint_id,
                    'projectId': self.project_id,
                    'agentId': agent_id,
                    'checkpointType': checkpoint_type,
                    'title': title,
                    'outputPreview': output_preview,
                    'timestamp': datetime.utcnow().isoformat()
                }
            }
        )

    async def on_log(
        self,
        agent_id: str,
        level: str,
        message: str,
        metadata: Optional[dict] = None
    ):
        await self.ws_manager.broadcast_to_agent(agent_id, {
            'event': 'agent:log',
            'data': {
                'agentId': agent_id,
                'level': level,
                'message': message,
                'metadata': metadata,
                'timestamp': datetime.utcnow().isoformat()
            }
        })
```

---

## 10. Output Viewers

### 10.1 Output Types

```python
# Output type definitions
class OutputType(Enum):
    # Phase 1
    CONCEPT_DOCUMENT = "concept_doc"
    DESIGN_DOCUMENT = "design_doc"
    SCENARIO_DOCUMENT = "scenario_doc"
    CHARACTER_SPECS = "character_specs"
    WORLD_DESIGN = "world_design"
    TASK_BREAKDOWN = "task_breakdown"

    # Phase 2
    CODE = "code"
    ASSET_IMAGE = "asset_image"
    ASSET_AUDIO = "asset_audio"

    # Phase 3
    BUILD_RESULT = "build_result"
    TEST_RESULT = "test_result"
    REVIEW_RESULT = "review_result"

# Output viewer endpoints
@router.get("/outputs/{output_id}")
async def get_output(output_id: str):
    """Get output with metadata."""
    output = await db.get_output(output_id)
    return {
        'id': output.id,
        'type': output.output_type,
        'agentId': output.agent_id,
        'content': json.loads(output.content) if output.content else None,
        'filePath': output.file_path,
        'tokensUsed': output.tokens_used,
        'generationTimeMs': output.generation_time_ms,
        'createdAt': output.created_at.isoformat()
    }

@router.get("/outputs/{output_id}/preview")
async def get_output_preview(output_id: str):
    """Get rendered preview of output."""
    output = await db.get_output(output_id)

    if output.output_type in ['concept_doc', 'design_doc', 'scenario_doc']:
        # Render markdown
        content = json.loads(output.content)
        return {
            'type': 'markdown',
            'html': markdown_to_html(content.get('markdown', '')),
            'raw': content
        }
    elif output.output_type == 'code':
        # Return with syntax highlighting info
        content = json.loads(output.content)
        return {
            'type': 'code',
            'language': content.get('language', 'typescript'),
            'code': content.get('code', ''),
            'filename': content.get('filename', ''),
            'lineCount': len(content.get('code', '').split('\n'))
        }
    elif output.output_type == 'asset_image':
        # Return image info
        return {
            'type': 'image',
            'url': f'/api/v1/files/{output.file_path}',
            'mimeType': 'image/png',
            'dimensions': output.metadata.get('dimensions')
        }
    elif output.output_type == 'asset_audio':
        # Return audio info
        return {
            'type': 'audio',
            'url': f'/api/v1/files/{output.file_path}',
            'mimeType': 'audio/mpeg',
            'duration': output.metadata.get('duration')
        }
    elif output.output_type == 'test_result':
        # Return test result summary
        content = json.loads(output.content)
        return {
            'type': 'test_result',
            'summary': content.get('summary'),
            'passRate': content.get('pass_rate'),
            'results': content.get('results')
        }
```

---

## Appendix A: API Response Examples

### Project Creation Response
```json
{
  "id": "proj_abc123",
  "name": "My Awesome RPG",
  "status": "draft",
  "currentPhase": 0,
  "createdAt": "2024-01-15T14:30:00Z",
  "concept": {
    "description": "A 2D pixel art RPG...",
    "platform": "web",
    "scope": "mvp"
  }
}
```

### Agent Status Response
```json
{
  "id": "agent_xyz789",
  "type": "code_leader",
  "status": "running",
  "progress": 45,
  "currentTask": "Implementing player controller",
  "tokensUsed": 12450,
  "runtimeSeconds": 2723,
  "completedTasks": 12,
  "totalTasks": 28,
  "startedAt": "2024-01-15T14:35:00Z",
  "subAgents": [
    {
      "id": "agent_sub001",
      "type": "code_worker",
      "status": "running",
      "progress": 78,
      "currentTask": "PlayerController.ts"
    }
  ]
}
```

### Metrics Response
```json
{
  "projectId": "proj_abc123",
  "totalTokensUsed": 45230,
  "estimatedTotalTokens": 78000,
  "elapsedTimeSeconds": 2723,
  "estimatedRemainingSeconds": 1920,
  "estimatedEndTime": "2024-01-15T15:17:23Z",
  "completedTasks": 12,
  "totalTasks": 28,
  "progressPercent": 42.9,
  "currentPhase": 2,
  "phaseName": "Development"
}
```

### Checkpoint Response
```json
{
  "id": "ckpt_def456",
  "type": "design_review",
  "title": "Technical Design Document Review",
  "status": "pending",
  "agentId": "agent_abc123",
  "output": {
    "documentType": "design",
    "summary": "Complete technical architecture...",
    "sections": ["architecture", "tech_stack", "components"],
    "tokensUsed": 3245,
    "generationTimeMs": 45200
  },
  "createdAt": "2024-01-15T14:40:00Z",
  "waitingTimeMinutes": 83
}
```

### Error Response
```json
{
  "error": {
    "code": "AGENT_TIMEOUT",
    "category": "agent",
    "type": "timeout",
    "message": "Task execution exceeded time limit",
    "details": {
      "agentId": "agent_xyz789",
      "task": "PlayerController.ts",
      "timeoutSeconds": 300
    },
    "suggestions": [
      "Retry the task",
      "Skip this task and continue",
      "Pause the project"
    ],
    "actions": [
      {"label": "Retry", "action": "retry_task", "data": {"taskId": "task_123"}},
      {"label": "Skip", "action": "skip_task", "data": {"taskId": "task_123"}},
      {"label": "Pause", "action": "pause_project"}
    ],
    "timestamp": "2024-01-15T14:45:23Z",
    "requestId": "req_abc123"
  }
}
```

---

## Appendix B: WebSocket Message Examples

### Agent Progress Event
```json
{
  "event": "agent:progress",
  "data": {
    "agentId": "agent_xyz789",
    "progress": 67,
    "currentTask": "Generating sprite animations",
    "completedTasks": 15,
    "totalTasks": 28,
    "timestamp": "2024-01-15T14:45:30.123Z"
  }
}
```

### Metrics Update Event
```json
{
  "event": "metrics:update",
  "data": {
    "projectId": "proj_abc123",
    "totalTokens": 48500,
    "estimatedTotalTokens": 78000,
    "elapsedSeconds": 2850,
    "estimatedRemainingSeconds": 1800,
    "completedTasks": 14,
    "totalTasks": 28,
    "timestamp": "2024-01-15T14:47:00Z"
  }
}
```

### State Sync Event (After Reconnection)
```json
{
  "event": "connection:state_sync",
  "data": {
    "projectId": "proj_abc123",
    "serverState": {
      "currentAgent": "CodeLeader",
      "progress": 78,
      "completedTasks": 15,
      "totalTasks": 28
    },
    "hasDiff": true,
    "timestamp": "2024-01-15T14:50:00Z"
  }
}
```

### Error Event
```json
{
  "event": "error:agent",
  "data": {
    "agentId": "agent_xyz789",
    "errorType": "timeout",
    "errorMessage": "Task execution exceeded time limit (5 minutes)",
    "suggestions": [
      "Retry the task",
      "Skip this task",
      "Pause project"
    ],
    "actions": [
      {"label": "Retry", "action": "retry"},
      {"label": "Skip", "action": "skip"},
      {"label": "Pause", "action": "pause"}
    ],
    "timestamp": "2024-01-15T14:45:23Z"
  }
}
```
