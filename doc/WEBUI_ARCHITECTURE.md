# WebUI Architecture Specification

## 1. Architecture Overview

```
Browser(WebUI) ─── HTTPS/WSS ─┬─ REST API (FastAPI)
                              └─ WebSocket (Socket.io)
                                        │
                              ┌─────────┴─────────┐
                              │   Service Layer   │
                              │ Project/Agent/    │
                              │ Checkpoint/Metrics│
                              └─────────┬─────────┘
                   ┌──────────┬─────────┴──────────┐
            LangGraph    State Manager      File Storage
           Agent Runner  (SQLite/Checkpoint)   (Local)
```

### Technology Stack

| Layer | Technology |
|-------|------------|
| Frontend | React 18 + TypeScript, Vite, Electron, Tailwind, Zustand, Socket.io Client |
| Backend | FastAPI, Socket.io, LangGraph |
| Storage | SQLite, File System |

## 2. Frontend Architecture

### Directory Structure

```
src/
├── views/              # Page-level: ProjectView, AgentsView, CheckpointsView, etc.
├── components/
│   ├── ui/             # Base UI: Button, Card, Progress, CategoryMarker, etc.
│   ├── layout/         # AppLayout, HeaderTabs, Footer, ConnectionStatus
│   ├── dashboard/      # DashboardView, ProjectStatus, ActiveAgents, etc.
│   ├── agents/         # AgentCard, AgentDetailView, AgentListView, AgentLog
│   ├── checkpoints/    # CheckpointCard, CheckpointReviewView, FeedbackForm
│   ├── viewers/        # DocumentViewer, CodeViewer
│   └── analytics/      # TokenTracker, CostEstimator, DependencyGraph
├── stores/             # Zustand: projectStore, agentStore, checkpointStore, etc.
├── services/           # websocketService.ts
├── types/              # TypeScript types
└── styles/             # index.css (Tailwind + NieR theme)

electron/
├── main.ts             # Electron main process
├── preload.ts          # Preload script (IPC bridge)
└── backend/manager.ts  # Backend process manager
```

### State Management (Zustand)

| Store | 責務 |
|-------|------|
| projectStore | プロジェクトCRUD、開始/停止 |
| agentStore | Agent一覧、ログ、リアルタイム更新 |
| checkpointStore | 承認待ち一覧、承認/却下処理 |
| metricsStore | トークン、時間、進捗メトリクス |
| connectionStore | 接続状態、再接続、状態同期 |

### WebSocket Events

**Project:** `project:status_changed`, `project:phase_changed`

**Agent:** `agent:started`, `agent:progress`, `agent:completed`, `agent:failed`, `agent:log`

**Checkpoint:** `checkpoint:created`, `checkpoint:resolved`

**Metrics:** `metrics:update`, `metrics:tokens`

**Error:** `error:agent`, `error:llm`, `error:state`

**Connection:** `connection:state_sync`

## 3. Backend Architecture

### Directory Structure

```
backend/
├── app/
│   ├── main.py         # FastAPI entry
│   ├── config.py
│   ├── api/v1/         # projects, agents, checkpoints, metrics, outputs, websocket
│   ├── models/         # SQLAlchemy models
│   ├── schemas/        # Pydantic schemas
│   ├── services/       # Business logic
│   └── agents/         # LangGraph integration
```

### API Endpoints

**→ WebUI_API.md を参照**

## 4. Database Schema

### Tables

| Table | 主要カラム |
|-------|-----------|
| projects | id, name, status, current_phase, state(JSON), config(JSON) |
| agents | id, project_id, type, status, progress, tokens_used, parent_agent_id |
| checkpoints | id, project_id, agent_id, type, status, output(JSON), feedback |
| agent_logs | id, agent_id, level, message, timestamp |
| agent_outputs | id, agent_id, output_type, content(JSON), file_path |
| metrics_history | id, project_id, total_tokens, elapsed_seconds, timestamp |

### Indexes

- agents: project_id, status
- checkpoints: project_id, status
- agent_logs: agent_id, timestamp
- agent_outputs: agent_id

## 5. Real-time Communication

### WebSocket Architecture

```
WebSocket Server (Socket.io)
        │
┌───────┼───────┬───────────────┐
│       │       │               │
Room:   Room:   Room:           Room:
project:123  project:456  agent:789
```

**Room管理:** プロジェクト/Agent単位でsubscribe

**接続管理:** client_id → rooms マッピング

## 6. Resilience & Recovery

### State Persistence

- checkpoint_interval: 30秒
- プロジェクト状態をJSONでDB保存
- 切断後の状態差分検出・同期

### Connection Recovery

1. 切断検知
2. Exponential Backoff再接続 (1s→2s→4s...最大16s)
3. 5回失敗 → 手動再接続UI表示
4. 復旧後 → 状態同期リクエスト

### Error Recovery Config

| Error Type | Max Retries | Base Delay |
|------------|-------------|------------|
| llm_error | 3 | 2s |
| timeout | 2 | 5s |
| rate_limit | 5 | 60s |
| auth_error | 0 | - |

## 7. Metrics Collection

### Project Metrics

- totalTokensUsed / estimatedTotalTokens
- elapsedTimeSeconds / estimatedRemainingSeconds
- completedTasks / totalTasks / progressPercent
- currentPhase / phaseName

### Agent Metrics

- status, progress, currentTask
- tokensUsed / tokensEstimated
- runtimeSeconds
- activeSubAgents / subAgentMetrics[]

## 8. Error Handling

### Error Categories

| Category | Types |
|----------|-------|
| CONNECTION | websocket_disconnect, server_unreachable, network_timeout |
| LLM | api_error, rate_limit, token_limit, invalid_response |
| AGENT | task_failed, dependency_error, timeout, validation_error |
| STATE | sync_failed, checkpoint_failed, restore_failed |
| USER | input_validation, resource_not_found |

### Error Response Format

```
{
  error: {
    code, category, type, message,
    details, suggestions[], actions[]
  }
}
```

## 9. LangGraph Integration

### Progress Callback Events

| Callback | データ |
|----------|--------|
| on_agent_start | agentId, agentType, projectId |
| on_agent_progress | agentId, progress, currentTask, completedTasks, totalTasks |
| on_agent_complete | agentId, duration, tokensUsed, outputSummary |
| on_agent_error | agentId, errorType, errorMessage, canRetry, retryCount |
| on_checkpoint_created | checkpointId, agentId, type, title, outputPreview |
| on_log | agentId, level, message, metadata |

## 10. Output Types

| Type | 用途 |
|------|------|
| concept_doc | 企画書 |
| design_doc | 設計書 |
| scenario_doc | シナリオ |
| character_specs | キャラクター仕様 |
| world_design | 世界観設計 |
| task_breakdown | タスク分解 |
| code | ソースコード |
| asset_image | 画像アセット |
| asset_audio | 音声アセット |
| build_result | ビルド結果 |
| test_result | テスト結果 |
| review_result | レビュー結果 |
