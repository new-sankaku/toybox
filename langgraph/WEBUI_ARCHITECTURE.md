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
                          │   API Gateway Layer   │
                          │   ─────────────────   │
                          │   - Authentication    │
                          │   - Rate Limiting     │
                          │   - Request Routing   │
                          └───────────┬───────────┘
                                      │
            ┌─────────────────────────┼─────────────────────────┐
            │                         │                         │
            ▼                         ▼                         ▼
   ┌─────────────────┐     ┌─────────────────┐      ┌─────────────────┐
   │  Project        │     │  Agent          │      │  Notification   │
   │  Service        │     │  Orchestrator   │      │  Service        │
   │                 │     │  (LangGraph)    │      │                 │
   └────────┬────────┘     └────────┬────────┘      └────────┬────────┘
            │                       │                        │
            └───────────────────────┼────────────────────────┘
                                    │
                                    ▼
                          ┌───────────────────────┐
                          │    State Manager      │
                          │    ───────────────    │
                          │    - Checkpointing    │
                          │    - State Sync       │
                          │    - Event Sourcing   │
                          └───────────┬───────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    │                 │                 │
                    ▼                 ▼                 ▼
           ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
           │  PostgreSQL   │ │    Redis      │ │  File Storage │
           │  (Projects,   │ │  (Cache,      │ │  (Assets,     │
           │   State)      │ │   Sessions)   │ │   Outputs)    │
           └───────────────┘ └───────────────┘ └───────────────┘
```

### 1.2 Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | React 18 + TypeScript | UI Framework |
| | Tailwind CSS | Styling (customized for NieR theme) |
| | Zustand | State Management |
| | React Query | Server State / Caching |
| | Socket.io Client | Real-time Communication |
| | Framer Motion | Animations |
| **Backend** | FastAPI (Python) | REST API Server |
| | Socket.io | WebSocket Server |
| | LangGraph | Agent Orchestration |
| | Celery | Background Tasks |
| **Database** | PostgreSQL | Persistent Storage |
| | Redis | Cache & Session Store |
| | MinIO / S3 | File Storage |
| **Infrastructure** | Docker | Containerization |
| | Nginx | Reverse Proxy |
| | Let's Encrypt | SSL Certificates |

---

## 2. Frontend Architecture

### 2.1 Component Structure

```
src/
├── app/
│   ├── layout.tsx              # Root layout with NieR theme
│   ├── page.tsx                # Dashboard (main page)
│   ├── projects/
│   │   ├── page.tsx            # Project list
│   │   ├── [id]/
│   │   │   ├── page.tsx        # Project detail
│   │   │   ├── agents/
│   │   │   │   └── [agentId]/
│   │   │   │       └── page.tsx # Agent detail view
│   │   │   └── checkpoints/
│   │   │       └── [checkpointId]/
│   │   │           └── page.tsx # Checkpoint review
│   │   └── new/
│   │       └── page.tsx        # Create project
│   └── settings/
│       └── page.tsx            # User settings
│
├── components/
│   ├── ui/                     # Base UI components (NieR styled)
│   │   ├── Button.tsx
│   │   ├── Card.tsx
│   │   ├── Panel.tsx
│   │   ├── Input.tsx
│   │   ├── Select.tsx
│   │   ├── Progress.tsx
│   │   ├── Badge.tsx
│   │   ├── Modal.tsx
│   │   ├── Toast.tsx
│   │   └── Skeleton.tsx
│   │
│   ├── effects/                # Visual effects
│   │   ├── Scanlines.tsx
│   │   ├── GlitchText.tsx
│   │   ├── PulseGlow.tsx
│   │   └── NoiseOverlay.tsx
│   │
│   ├── layout/                 # Layout components
│   │   ├── Header.tsx
│   │   ├── Sidebar.tsx
│   │   ├── Footer.tsx
│   │   └── Navigation.tsx
│   │
│   ├── dashboard/              # Dashboard specific
│   │   ├── ProjectStatus.tsx
│   │   ├── ActiveAgents.tsx
│   │   ├── PendingApprovals.tsx
│   │   ├── RecentActivity.tsx
│   │   └── PhaseProgress.tsx
│   │
│   ├── agents/                 # Agent related
│   │   ├── AgentCard.tsx
│   │   ├── AgentDetail.tsx
│   │   ├── AgentProgress.tsx
│   │   ├── AgentLog.tsx
│   │   └── SubAgentList.tsx
│   │
│   ├── checkpoints/            # Human checkpoint
│   │   ├── CheckpointCard.tsx
│   │   ├── CheckpointReview.tsx
│   │   ├── FeedbackForm.tsx
│   │   └── ApprovalButtons.tsx
│   │
│   └── project/                # Project related
│       ├── ProjectCard.tsx
│       ├── ProjectForm.tsx
│       ├── ProjectTimeline.tsx
│       └── OutputViewer.tsx
│
├── hooks/                      # Custom hooks
│   ├── useWebSocket.ts
│   ├── useProject.ts
│   ├── useAgents.ts
│   ├── useCheckpoints.ts
│   ├── useNotifications.ts
│   └── useTheme.ts
│
├── stores/                     # Zustand stores
│   ├── projectStore.ts
│   ├── agentStore.ts
│   ├── notificationStore.ts
│   └── uiStore.ts
│
├── services/                   # API services
│   ├── api.ts                  # Axios instance
│   ├── projectService.ts
│   ├── agentService.ts
│   ├── checkpointService.ts
│   └── websocketService.ts
│
├── types/                      # TypeScript types
│   ├── project.ts
│   ├── agent.ts
│   ├── checkpoint.ts
│   ├── websocket.ts
│   └── api.ts
│
├── styles/                     # Global styles
│   ├── globals.css
│   ├── nier-theme.css
│   ├── animations.css
│   └── fonts.css
│
└── lib/                        # Utilities
    ├── utils.ts
    ├── constants.ts
    └── formatters.ts
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
  updateProject: (id: string, data: UpdateProjectDTO) => Promise<void>;
  deleteProject: (id: string) => Promise<void>;
}

// stores/agentStore.ts
interface AgentState {
  // Data
  agents: Record<string, Agent>;          // projectId -> agents
  activeAgents: Agent[];
  agentLogs: Record<string, LogEntry[]>;  // agentId -> logs

  // Real-time updates
  subscribeToAgent: (agentId: string) => void;
  unsubscribeFromAgent: (agentId: string) => void;

  // Actions
  fetchAgents: (projectId: string) => Promise<void>;
  getAgentDetail: (agentId: string) => Promise<Agent>;
}

// stores/notificationStore.ts
interface NotificationState {
  notifications: Notification[];
  unreadCount: number;

  // Actions
  addNotification: (notification: Notification) => void;
  markAsRead: (id: string) => void;
  markAllAsRead: () => void;
  clearNotifications: () => void;
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
  'checkpoint:reminder': (data: CheckpointReminderEvent) => void;

  // System Events
  'system:error': (data: SystemErrorEvent) => void;
  'system:maintenance': (data: MaintenanceEvent) => void;
}

class WebSocketService {
  private socket: Socket;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;

  connect(token: string): void {
    this.socket = io(WS_URL, {
      auth: { token },
      transports: ['websocket'],
      reconnection: true,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
    });

    this.setupEventListeners();
  }

  // Subscribe to project-specific events
  subscribeToProject(projectId: string): void {
    this.socket.emit('subscribe:project', { projectId });
  }

  // Subscribe to agent-specific events
  subscribeToAgent(agentId: string): void {
    this.socket.emit('subscribe:agent', { agentId });
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
│   ├── config.py               # Configuration management
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
│   │       ├── logs.py         # Log endpoints
│   │       └── websocket.py    # WebSocket handlers
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py         # Authentication/Authorization
│   │   ├── exceptions.py       # Custom exceptions
│   │   └── middleware.py       # Custom middleware
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── project.py          # Project SQLAlchemy model
│   │   ├── agent.py            # Agent model
│   │   ├── checkpoint.py       # Checkpoint model
│   │   ├── user.py             # User model
│   │   └── log.py              # Log model
│   │
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── project.py          # Project Pydantic schemas
│   │   ├── agent.py            # Agent schemas
│   │   ├── checkpoint.py       # Checkpoint schemas
│   │   └── websocket.py        # WebSocket event schemas
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── project_service.py
│   │   ├── agent_service.py
│   │   ├── checkpoint_service.py
│   │   ├── notification_service.py
│   │   └── file_service.py
│   │
│   ├── orchestrator/
│   │   ├── __init__.py
│   │   ├── graph.py            # LangGraph definition
│   │   ├── state.py            # State management
│   │   ├── nodes/              # Agent nodes
│   │   │   ├── concept.py
│   │   │   ├── design.py
│   │   │   ├── scenario.py
│   │   │   ├── character.py
│   │   │   ├── world.py
│   │   │   ├── task_split.py
│   │   │   ├── code_leader.py
│   │   │   ├── asset_leader.py
│   │   │   ├── integrator.py
│   │   │   ├── tester.py
│   │   │   └── reviewer.py
│   │   └── callbacks/          # LangGraph callbacks
│   │       ├── progress.py
│   │       └── logging.py
│   │
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── celery_app.py       # Celery configuration
│   │   └── agent_tasks.py      # Background agent tasks
│   │
│   └── utils/
│       ├── __init__.py
│       └── helpers.py
│
├── alembic/                    # Database migrations
│   ├── versions/
│   └── env.py
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_projects.py
│   ├── test_agents.py
│   └── test_checkpoints.py
│
└── requirements.txt
```

### 3.2 API Endpoints

```yaml
# REST API Endpoints

# Projects
GET     /api/v1/projects                    # List all projects
POST    /api/v1/projects                    # Create new project
GET     /api/v1/projects/{id}               # Get project details
PUT     /api/v1/projects/{id}               # Update project
DELETE  /api/v1/projects/{id}               # Delete project
POST    /api/v1/projects/{id}/start         # Start project execution
POST    /api/v1/projects/{id}/pause         # Pause project
POST    /api/v1/projects/{id}/resume        # Resume project
POST    /api/v1/projects/{id}/cancel        # Cancel project

# Agents
GET     /api/v1/projects/{id}/agents        # List agents for project
GET     /api/v1/agents/{id}                 # Get agent details
GET     /api/v1/agents/{id}/logs            # Get agent logs
GET     /api/v1/agents/{id}/outputs         # Get agent outputs

# Checkpoints
GET     /api/v1/projects/{id}/checkpoints   # List checkpoints for project
GET     /api/v1/checkpoints/{id}            # Get checkpoint details
POST    /api/v1/checkpoints/{id}/approve    # Approve checkpoint
POST    /api/v1/checkpoints/{id}/reject     # Reject checkpoint
POST    /api/v1/checkpoints/{id}/request-changes  # Request changes

# Logs
GET     /api/v1/projects/{id}/logs          # Get project logs
GET     /api/v1/logs/stream                 # SSE log stream

# Files/Assets
GET     /api/v1/projects/{id}/files         # List project files
GET     /api/v1/files/{id}                  # Download file
POST    /api/v1/projects/{id}/files         # Upload file

# User
GET     /api/v1/users/me                    # Get current user
PUT     /api/v1/users/me                    # Update user settings
GET     /api/v1/users/me/notifications      # Get notifications
```

### 3.3 WebSocket Events

```yaml
# WebSocket Event Specifications

# Client → Server Events
subscribe:project:
  payload:
    projectId: string
  description: Subscribe to project updates

unsubscribe:project:
  payload:
    projectId: string
  description: Unsubscribe from project updates

subscribe:agent:
  payload:
    agentId: string
  description: Subscribe to specific agent updates

# Server → Client Events
project:status_changed:
  payload:
    projectId: string
    oldStatus: ProjectStatus
    newStatus: ProjectStatus
    timestamp: ISO8601

project:phase_changed:
  payload:
    projectId: string
    phase: number
    phaseName: string
    timestamp: ISO8601

agent:started:
  payload:
    agentId: string
    agentType: string
    projectId: string
    timestamp: ISO8601

agent:progress:
  payload:
    agentId: string
    progress: number (0-100)
    currentTask: string
    timestamp: ISO8601

agent:completed:
  payload:
    agentId: string
    duration: number (seconds)
    outputSummary: string
    timestamp: ISO8601

agent:failed:
  payload:
    agentId: string
    error: string
    errorType: string
    canRetry: boolean
    timestamp: ISO8601

agent:log:
  payload:
    agentId: string
    level: "DEBUG" | "INFO" | "WARN" | "ERROR"
    message: string
    timestamp: ISO8601
    metadata: object (optional)

checkpoint:created:
  payload:
    checkpointId: string
    projectId: string
    agentId: string
    checkpointType: string
    title: string
    timestamp: ISO8601

checkpoint:resolved:
  payload:
    checkpointId: string
    resolution: "approved" | "rejected" | "changes_requested"
    feedback: string (optional)
    resolvedBy: string
    timestamp: ISO8601

checkpoint:reminder:
  payload:
    checkpointId: string
    waitingTime: number (hours)
    reminderLevel: "first" | "escalation"
    timestamp: ISO8601
```

---

## 4. Database Schema

### 4.1 Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATABASE SCHEMA                                    │
└─────────────────────────────────────────────────────────────────────────────┘

┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
│      users       │       │     projects     │       │      agents      │
├──────────────────┤       ├──────────────────┤       ├──────────────────┤
│ id          PK   │──┐    │ id          PK   │──┐    │ id          PK   │
│ email            │  │    │ user_id     FK   │◄─┘    │ project_id  FK   │◄─┐
│ name             │  │    │ name             │  │    │ type             │  │
│ password_hash    │  │    │ description      │  │    │ status           │  │
│ settings (JSON)  │  │    │ concept (JSON)   │  │    │ progress         │  │
│ created_at       │  │    │ status           │  │    │ current_task     │  │
│ updated_at       │  └───►│ current_phase    │  │    │ started_at       │  │
└──────────────────┘       │ state (JSON)     │  │    │ completed_at     │  │
                           │ created_at       │  │    │ error            │  │
                           │ updated_at       │  │    │ parent_agent_id  │──┤
                           └──────────────────┘  │    │ created_at       │  │
                                    │            │    └──────────────────┘  │
                                    │            │             │            │
                                    │            └─────────────┼────────────┘
                                    │                          │
                                    ▼                          ▼
                           ┌──────────────────┐       ┌──────────────────┐
                           │   checkpoints    │       │    agent_logs    │
                           ├──────────────────┤       ├──────────────────┤
                           │ id          PK   │       │ id          PK   │
                           │ project_id  FK   │       │ agent_id    FK   │
                           │ agent_id    FK   │       │ level            │
                           │ type             │       │ message          │
                           │ title            │       │ metadata (JSON)  │
                           │ description      │       │ timestamp        │
                           │ output (JSON)    │       └──────────────────┘
                           │ status           │
                           │ feedback         │       ┌──────────────────┐
                           │ resolved_by      │       │   agent_outputs  │
                           │ resolved_at      │       ├──────────────────┤
                           │ created_at       │       │ id          PK   │
                           └──────────────────┘       │ agent_id    FK   │
                                                      │ output_type      │
                                                      │ content (JSON)   │
                                                      │ file_path        │
                                                      │ created_at       │
                                                      └──────────────────┘
```

### 4.2 Table Definitions

```sql
-- Users table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Projects table
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    concept JSONB,                -- User's initial game concept
    status VARCHAR(50) DEFAULT 'draft',  -- draft, running, paused, completed, failed
    current_phase INTEGER DEFAULT 0,
    state JSONB DEFAULT '{}',    -- LangGraph state snapshot
    config JSONB DEFAULT '{}',   -- Project-specific configuration
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agents table
CREATE TABLE agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type VARCHAR(100) NOT NULL,  -- concept, design, code_leader, etc.
    status VARCHAR(50) DEFAULT 'pending',  -- pending, running, completed, failed
    progress INTEGER DEFAULT 0,  -- 0-100
    current_task TEXT,
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error TEXT,
    parent_agent_id UUID REFERENCES agents(id),  -- For sub-agents
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Checkpoints table (Human-in-the-loop)
CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    type VARCHAR(100) NOT NULL,  -- concept_review, design_review, etc.
    title VARCHAR(255) NOT NULL,
    description TEXT,
    output JSONB NOT NULL,       -- Agent output to review
    status VARCHAR(50) DEFAULT 'pending',  -- pending, approved, rejected, changes_requested
    feedback TEXT,
    resolved_by UUID REFERENCES users(id),
    resolved_at TIMESTAMP WITH TIME ZONE,
    reminder_sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agent logs table
CREATE TABLE agent_logs (
    id BIGSERIAL PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    level VARCHAR(20) NOT NULL,  -- DEBUG, INFO, WARN, ERROR
    message TEXT NOT NULL,
    metadata JSONB,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Agent outputs table
CREATE TABLE agent_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    output_type VARCHAR(100) NOT NULL,  -- concept_doc, design_doc, code, asset, etc.
    content JSONB,
    file_path VARCHAR(500),      -- For file-based outputs
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_projects_user_id ON projects(user_id);
CREATE INDEX idx_projects_status ON projects(status);
CREATE INDEX idx_agents_project_id ON agents(project_id);
CREATE INDEX idx_agents_status ON agents(status);
CREATE INDEX idx_checkpoints_project_id ON checkpoints(project_id);
CREATE INDEX idx_checkpoints_status ON checkpoints(status);
CREATE INDEX idx_agent_logs_agent_id ON agent_logs(agent_id);
CREATE INDEX idx_agent_logs_timestamp ON agent_logs(timestamp);
```

---

## 5. Authentication & Security

### 5.1 Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        AUTHENTICATION FLOW                                   │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────┐                    ┌──────────┐                    ┌──────────┐
  │  Client  │                    │  Server  │                    │   Redis  │
  └────┬─────┘                    └────┬─────┘                    └────┬─────┘
       │                               │                               │
       │  1. POST /auth/login          │                               │
       │  {email, password}            │                               │
       │──────────────────────────────►│                               │
       │                               │                               │
       │                               │  2. Validate credentials      │
       │                               │  (bcrypt verify)              │
       │                               │                               │
       │                               │  3. Generate tokens           │
       │                               │  - Access Token (JWT, 15min)  │
       │                               │  - Refresh Token (UUID, 7d)   │
       │                               │                               │
       │                               │  4. Store refresh token       │
       │                               │──────────────────────────────►│
       │                               │                               │
       │  5. Return tokens             │                               │
       │◄──────────────────────────────│                               │
       │  {access_token,               │                               │
       │   refresh_token}              │                               │
       │                               │                               │
       │  6. API Request               │                               │
       │  Authorization: Bearer {JWT}  │                               │
       │──────────────────────────────►│                               │
       │                               │                               │
       │                               │  7. Verify JWT signature      │
       │                               │  & expiration                 │
       │                               │                               │
       │  8. Response                  │                               │
       │◄──────────────────────────────│                               │
       │                               │                               │
```

### 5.2 Security Measures

```yaml
Authentication:
  - JWT with RS256 signature
  - Access token: 15 minute expiry
  - Refresh token: 7 day expiry, stored in Redis
  - Token rotation on refresh

Authorization:
  - Role-based access control (RBAC)
  - Resource-level permissions
  - API rate limiting per user

Data Protection:
  - All passwords hashed with bcrypt (cost factor 12)
  - Sensitive data encrypted at rest (AES-256)
  - TLS 1.3 for all connections
  - CORS whitelist configuration

Input Validation:
  - Pydantic schemas for all inputs
  - SQL injection prevention via ORM
  - XSS prevention via output encoding
  - CSRF tokens for state-changing operations

Audit:
  - All authentication events logged
  - API access logs retained 90 days
  - Checkpoint actions require re-authentication
```

---

## 6. Real-time Communication

### 6.1 WebSocket Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     WEBSOCKET ARCHITECTURE                                   │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────────────────┐
                              │      Load Balancer          │
                              │   (Sticky Sessions)         │
                              └──────────────┬──────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    │                        │                        │
                    ▼                        ▼                        ▼
           ┌────────────────┐      ┌────────────────┐      ┌────────────────┐
           │   WS Server 1  │      │   WS Server 2  │      │   WS Server 3  │
           │                │      │                │      │                │
           │  Connections:  │      │  Connections:  │      │  Connections:  │
           │  - User A      │      │  - User C      │      │  - User E      │
           │  - User B      │      │  - User D      │      │  - User F      │
           └───────┬────────┘      └───────┬────────┘      └───────┬────────┘
                   │                       │                       │
                   └───────────────────────┼───────────────────────┘
                                           │
                                           ▼
                              ┌─────────────────────────────┐
                              │      Redis Pub/Sub          │
                              │   (Message Broker)          │
                              │                             │
                              │  Channels:                  │
                              │  - project:{id}             │
                              │  - agent:{id}               │
                              │  - user:{id}                │
                              └─────────────────────────────┘
                                           │
                                           │
                              ┌────────────┴────────────┐
                              │                         │
                              ▼                         ▼
                    ┌─────────────────┐      ┌─────────────────┐
                    │  Agent Workers  │      │  Notification   │
                    │  (Publishers)   │      │  Service        │
                    └─────────────────┘      └─────────────────┘
```

### 6.2 Connection Management

```python
# WebSocket connection manager
class ConnectionManager:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        self.active_connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        self.user_rooms: Dict[str, Set[str]] = defaultdict(set)

    async def connect(self, websocket: WebSocket, user_id: str):
        await websocket.accept()
        self.active_connections[user_id].add(websocket)

        # Subscribe to user's personal channel
        await self._subscribe_to_channel(f"user:{user_id}")

    async def disconnect(self, websocket: WebSocket, user_id: str):
        self.active_connections[user_id].discard(websocket)

        # Unsubscribe from all rooms
        for room in self.user_rooms[user_id]:
            await self._unsubscribe_from_channel(room)
        self.user_rooms[user_id].clear()

    async def subscribe_to_project(self, user_id: str, project_id: str):
        channel = f"project:{project_id}"
        self.user_rooms[user_id].add(channel)
        await self._subscribe_to_channel(channel)

    async def broadcast_to_project(self, project_id: str, message: dict):
        channel = f"project:{project_id}"
        await self.redis.publish(channel, json.dumps(message))

    async def send_to_user(self, user_id: str, message: dict):
        for connection in self.active_connections[user_id]:
            await connection.send_json(message)
```

---

## 7. LangGraph Integration

### 7.1 Graph Definition

```python
# orchestrator/graph.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from .state import GameDevState
from .nodes import (
    concept_node, design_node, scenario_node,
    character_node, world_node, task_split_node,
    code_leader_node, asset_leader_node,
    integrator_node, tester_node, reviewer_node
)

def create_game_dev_graph() -> StateGraph:
    """Create the main game development orchestration graph."""

    workflow = StateGraph(GameDevState)

    # Phase 1: Planning Nodes
    workflow.add_node("concept", concept_node)
    workflow.add_node("design", design_node)
    workflow.add_node("scenario", scenario_node)
    workflow.add_node("character", character_node)
    workflow.add_node("world", world_node)
    workflow.add_node("task_split", task_split_node)

    # Phase 2: Development Nodes
    workflow.add_node("code_leader", code_leader_node)
    workflow.add_node("asset_leader", asset_leader_node)

    # Phase 3: Quality Nodes
    workflow.add_node("integrator", integrator_node)
    workflow.add_node("tester", tester_node)
    workflow.add_node("reviewer", reviewer_node)

    # Human checkpoint nodes
    workflow.add_node("checkpoint_concept", checkpoint_handler)
    workflow.add_node("checkpoint_design", checkpoint_handler)
    workflow.add_node("checkpoint_code", checkpoint_handler)
    workflow.add_node("checkpoint_final", checkpoint_handler)

    # Phase 1 edges (sequential)
    workflow.add_edge("concept", "checkpoint_concept")
    workflow.add_conditional_edges(
        "checkpoint_concept",
        lambda s: "continue" if s["checkpoint_approved"] else "revise",
        {"continue": "design", "revise": "concept"}
    )
    workflow.add_edge("design", "checkpoint_design")
    workflow.add_conditional_edges(
        "checkpoint_design",
        lambda s: "continue" if s["checkpoint_approved"] else "revise",
        {"continue": "scenario", "revise": "design"}
    )
    workflow.add_edge("scenario", "character")
    workflow.add_edge("character", "world")
    workflow.add_edge("world", "task_split")

    # Phase 2 edges (parallel)
    workflow.add_edge("task_split", "code_leader")
    workflow.add_edge("task_split", "asset_leader")

    # Synchronization point
    workflow.add_node("sync_development", sync_node)
    workflow.add_edge("code_leader", "sync_development")
    workflow.add_edge("asset_leader", "sync_development")

    # Phase 3 edges
    workflow.add_edge("sync_development", "integrator")
    workflow.add_edge("integrator", "tester")
    workflow.add_edge("tester", "reviewer")
    workflow.add_edge("reviewer", "checkpoint_final")
    workflow.add_conditional_edges(
        "checkpoint_final",
        lambda s: "complete" if s["checkpoint_approved"] else "iterate",
        {"complete": END, "iterate": "tester"}
    )

    # Set entry point
    workflow.set_entry_point("concept")

    return workflow

# Compile with checkpointing
def create_compiled_graph(db_path: str):
    workflow = create_game_dev_graph()
    checkpointer = SqliteSaver.from_conn_string(db_path)
    return workflow.compile(checkpointer=checkpointer)
```

### 7.2 State Schema

```python
# orchestrator/state.py
from typing import TypedDict, List, Dict, Optional, Any
from enum import Enum

class ProjectPhase(Enum):
    PLANNING = 1
    DEVELOPMENT = 2
    QUALITY = 3

class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"

class GameDevState(TypedDict):
    # Project Info
    project_id: str
    project_name: str
    user_concept: str

    # Current Status
    current_phase: ProjectPhase
    current_agent: str

    # Phase 1 Outputs
    concept_document: Optional[Dict[str, Any]]
    design_document: Optional[Dict[str, Any]]
    scenario_document: Optional[Dict[str, Any]]
    character_specs: Optional[List[Dict[str, Any]]]
    world_design: Optional[Dict[str, Any]]
    task_breakdown: Optional[Dict[str, Any]]

    # Phase 2 Outputs
    code_artifacts: Optional[Dict[str, Any]]
    asset_artifacts: Optional[Dict[str, Any]]

    # Phase 3 Outputs
    build_result: Optional[Dict[str, Any]]
    test_results: Optional[Dict[str, Any]]
    review_result: Optional[Dict[str, Any]]

    # Human Checkpoints
    pending_checkpoint: Optional[str]
    checkpoint_approved: bool
    checkpoint_feedback: Optional[str]

    # Metadata
    agent_statuses: Dict[str, AgentStatus]
    errors: List[Dict[str, Any]]
    messages: List[Dict[str, Any]]
```

### 7.3 Callback Integration

```python
# orchestrator/callbacks/progress.py
from typing import Any, Dict
from langgraph.callbacks import BaseCallbackHandler

class WebUIProgressCallback(BaseCallbackHandler):
    """Callback to send progress updates to WebUI via WebSocket."""

    def __init__(self, project_id: str, websocket_manager):
        self.project_id = project_id
        self.ws_manager = websocket_manager

    async def on_chain_start(
        self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs
    ):
        agent_name = serialized.get("name", "unknown")
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                "event": "agent:started",
                "data": {
                    "agentId": kwargs.get("run_id"),
                    "agentType": agent_name,
                    "projectId": self.project_id,
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        )

    async def on_chain_end(
        self, outputs: Dict[str, Any], **kwargs
    ):
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                "event": "agent:completed",
                "data": {
                    "agentId": kwargs.get("run_id"),
                    "outputSummary": str(outputs)[:200],
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        )

    async def on_tool_start(
        self, serialized: Dict[str, Any], input_str: str, **kwargs
    ):
        # Send progress update
        await self.ws_manager.broadcast_to_project(
            self.project_id,
            {
                "event": "agent:progress",
                "data": {
                    "agentId": kwargs.get("parent_run_id"),
                    "currentTask": serialized.get("name"),
                    "timestamp": datetime.utcnow().isoformat()
                }
            }
        )
```

---

## 8. Deployment Architecture

### 8.1 Docker Compose Configuration

```yaml
# docker-compose.yml
version: '3.8'

services:
  # Frontend
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://api:8000
      - NEXT_PUBLIC_WS_URL=ws://api:8000
    depends_on:
      - api

  # Backend API
  api:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:password@postgres:5432/langgraph
      - REDIS_URL=redis://redis:6379
      - SECRET_KEY=${SECRET_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      - postgres
      - redis
    volumes:
      - ./storage:/app/storage

  # Celery Worker
  celery:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A app.tasks.celery_app worker --loglevel=info
    environment:
      - DATABASE_URL=postgresql://user:password@postgres:5432/langgraph
      - REDIS_URL=redis://redis:6379
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    depends_on:
      - postgres
      - redis

  # PostgreSQL
  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=langgraph
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  # Redis
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  # Nginx (Production)
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf
      - ./nginx/ssl:/etc/nginx/ssl
    depends_on:
      - frontend
      - api

volumes:
  postgres_data:
  redis_data:
```

### 8.2 Production Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PRODUCTION DEPLOYMENT                                   │
└─────────────────────────────────────────────────────────────────────────────┘

                              ┌─────────────────┐
                              │   CloudFlare    │
                              │   (CDN + WAF)   │
                              └────────┬────────┘
                                       │
                              ┌────────▼────────┐
                              │  Load Balancer  │
                              │   (HAProxy)     │
                              └────────┬────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
           ┌────────▼────────┐ ┌───────▼───────┐ ┌───────▼───────┐
           │    Frontend     │ │   API Server  │ │  WebSocket    │
           │   (Next.js)     │ │   (FastAPI)   │ │   Server      │
           │   x3 replicas   │ │  x3 replicas  │ │  x2 replicas  │
           └─────────────────┘ └───────┬───────┘ └───────┬───────┘
                                       │                 │
                                       └────────┬────────┘
                                                │
                    ┌───────────────────────────┼───────────────────────────┐
                    │                           │                           │
           ┌────────▼────────┐         ┌────────▼────────┐         ┌───────▼───────┐
           │   PostgreSQL    │         │     Redis       │         │    MinIO      │
           │   (Primary)     │         │   (Cluster)     │         │  (Storage)    │
           │     + Replica   │         │                 │         │               │
           └─────────────────┘         └─────────────────┘         └───────────────┘

                    ┌─────────────────────────────────────────────────────────┐
                    │                    Celery Workers                        │
                    │            (Auto-scaling: 2-10 replicas)                │
                    └─────────────────────────────────────────────────────────┘
```

---

## 9. Monitoring & Observability

### 9.1 Metrics Collection

```yaml
# Prometheus metrics to collect

Application Metrics:
  - http_requests_total (counter)
  - http_request_duration_seconds (histogram)
  - websocket_connections_active (gauge)
  - websocket_messages_total (counter)

Business Metrics:
  - projects_created_total (counter)
  - projects_completed_total (counter)
  - agents_executed_total (counter, by type)
  - agent_execution_duration_seconds (histogram, by type)
  - checkpoints_pending (gauge)
  - checkpoints_resolved_total (counter, by resolution)
  - llm_tokens_used_total (counter, by model)
  - llm_request_duration_seconds (histogram)

Infrastructure Metrics:
  - database_connections_active (gauge)
  - redis_memory_used_bytes (gauge)
  - celery_tasks_queued (gauge)
  - celery_tasks_processed_total (counter)
```

### 9.2 Logging Configuration

```python
# Structured logging configuration
LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "format": "%(asctime)s %(levelname)s %(name)s %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
            "stream": "ext://sys.stdout"
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "json",
            "filename": "/var/log/langgraph/app.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5
        }
    },
    "loggers": {
        "app": {"level": "INFO", "handlers": ["console", "file"]},
        "uvicorn": {"level": "INFO", "handlers": ["console"]},
        "langgraph": {"level": "DEBUG", "handlers": ["console", "file"]}
    }
}
```

### 9.3 Health Checks

```python
# Health check endpoints

@app.get("/health")
async def health_check():
    """Basic health check."""
    return {"status": "healthy"}

@app.get("/health/ready")
async def readiness_check(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis)
):
    """Readiness check with dependency verification."""
    checks = {}

    # Database check
    try:
        await db.execute(text("SELECT 1"))
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"

    # Redis check
    try:
        await redis.ping()
        checks["redis"] = "healthy"
    except Exception as e:
        checks["redis"] = f"unhealthy: {str(e)}"

    # Overall status
    all_healthy = all(v == "healthy" for v in checks.values())

    return {
        "status": "ready" if all_healthy else "not_ready",
        "checks": checks
    }
```

---

## 10. Error Handling Strategy

### 10.1 Error Categories

```yaml
Client Errors (4xx):
  400 Bad Request:
    - Invalid input data
    - Schema validation failure
  401 Unauthorized:
    - Missing/invalid token
    - Expired token
  403 Forbidden:
    - Insufficient permissions
    - Resource access denied
  404 Not Found:
    - Resource doesn't exist
  409 Conflict:
    - Resource state conflict
    - Concurrent modification
  429 Too Many Requests:
    - Rate limit exceeded

Server Errors (5xx):
  500 Internal Server Error:
    - Unexpected error
    - Unhandled exception
  502 Bad Gateway:
    - LLM API failure
    - External service error
  503 Service Unavailable:
    - Database connection failure
    - Redis connection failure
  504 Gateway Timeout:
    - LLM request timeout
    - Long-running operation timeout
```

### 10.2 Error Response Format

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid project configuration",
    "details": [
      {
        "field": "concept",
        "message": "Concept must be at least 50 characters"
      }
    ],
    "request_id": "req_abc123",
    "timestamp": "2024-01-15T14:30:00Z"
  }
}
```

### 10.3 Retry Strategy

```python
# Retry configuration for different operations

RETRY_CONFIG = {
    "llm_requests": {
        "max_retries": 3,
        "base_delay": 1.0,
        "max_delay": 30.0,
        "exponential_base": 2,
        "retryable_errors": [
            "rate_limit_exceeded",
            "server_error",
            "timeout"
        ]
    },
    "database_operations": {
        "max_retries": 3,
        "base_delay": 0.5,
        "max_delay": 5.0,
        "retryable_errors": [
            "connection_error",
            "deadlock"
        ]
    },
    "websocket_reconnect": {
        "max_retries": 5,
        "base_delay": 1.0,
        "max_delay": 30.0,
        "exponential_base": 2
    }
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
  "current_phase": 0,
  "created_at": "2024-01-15T14:30:00Z",
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
  "current_task": "Implementing player controller",
  "started_at": "2024-01-15T14:35:00Z",
  "sub_agents": [
    {
      "id": "agent_sub001",
      "type": "code_worker",
      "status": "running",
      "progress": 78
    }
  ]
}
```

### Checkpoint Response
```json
{
  "id": "ckpt_def456",
  "type": "design_review",
  "title": "Technical Design Document Review",
  "status": "pending",
  "agent_id": "agent_abc123",
  "output": {
    "document_type": "design",
    "summary": "Complete technical architecture...",
    "sections": ["architecture", "tech_stack", "components"]
  },
  "created_at": "2024-01-15T14:40:00Z",
  "waiting_time_hours": 1.5
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
    "timestamp": "2024-01-15T14:45:30.123Z"
  }
}
```

### Checkpoint Created Event
```json
{
  "event": "checkpoint:created",
  "data": {
    "checkpointId": "ckpt_def456",
    "projectId": "proj_abc123",
    "agentId": "agent_xyz789",
    "checkpointType": "code_review",
    "title": "Code Implementation Review",
    "timestamp": "2024-01-15T14:50:00Z"
  }
}
```
