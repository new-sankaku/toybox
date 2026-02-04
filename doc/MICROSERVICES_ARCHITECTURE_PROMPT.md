# Microservices Architecture - Image Generation Prompt

## 構成概要

7つのマイクロサービス + API Gateway + WebSocket Hub + Message Queue + 外部API + DB群

## プロンプト（英語）

```
Create a clean, professional software architecture diagram on a white background with dark gray (#333333) text. The diagram uses rectangular boxes with rounded corners for services, cylinder shapes for databases, and a cloud shape for external APIs. All connection lines are solid with arrowheads indicating data flow direction. The overall layout is organized in 6 horizontal rows.

--- ROW 1 (Top center) ---
At the top center of the diagram, there is a large rounded rectangle labeled "Client (React + Vite)" with a monitor icon. It is colored light blue (#E3F2FD) with a dark blue (#1565C0) border. This box spans about 40% of the diagram width.

--- ROW 2 (Gateway layer) ---
Below the Client, two rounded rectangles are placed side by side, centered horizontally with a small gap between them.

The left box is labeled "API Gateway" colored light green (#E8F5E9) with a dark green (#2E7D32) border. It handles REST API routing, authentication, and rate limiting.

The right box is labeled "WebSocket Hub" colored light green (#E8F5E9) with a dark green (#2E7D32) border. It handles real-time event distribution to clients via Socket.IO rooms.

A vertical solid arrow extends downward from the Client box, splits into two branches: the left branch connects to "API Gateway" labeled "REST API (HTTP)", and the right branch connects to "WebSocket Hub" labeled "WebSocket (Socket.IO)".

--- ROW 3 (Application Services) ---
Below the gateway layer, four rounded rectangles are arranged in a horizontal row, evenly spaced across the full width of the diagram. All four boxes are colored light orange (#FFF3E0) with a dark orange (#E65100) border.

From left to right:

Box 1: "Project Service" — Owns project lifecycle, settings, quality config, system logs. Below the label in smaller text: "Tables: projects, quality_settings, project_ai_configs, system_logs".

Box 2: "Agent Service" — Owns agent execution, DAG scheduling, retry, recovery. Below the label in smaller text: "Tables: agents, agent_logs".

Box 3: "Checkpoint & Asset Service" — Owns human review workflow, asset approval. Below the label in smaller text: "Tables: checkpoints, assets".

Box 4: "Operations Service" — Owns interventions, file uploads, traces, metrics, backups. Below the label in smaller text: "Tables: interventions, uploaded_files, agent_traces, metrics".

The "API Gateway" box has four downward arrows, each connecting to one of these four service boxes. These arrows are labeled respectively: "/api/projects/*", "/api/agents/*", "/api/checkpoints/* /api/assets/*", "/api/interventions/* /api/files/* /api/traces/*".

--- Inter-service connections in ROW 3 ---

A horizontal bidirectional arrow connects "Project Service" and "Agent Service", labeled "reset agents, get status (HTTP)".

A horizontal bidirectional arrow connects "Agent Service" and "Checkpoint & Asset Service", labeled "create checkpoint, check deps (HTTP)".

A horizontal bidirectional arrow connects "Agent Service" and "Operations Service", labeled "update trace, check intervention (HTTP)".

A dashed arrow from "Checkpoint & Asset Service" curves upward-left to "Project Service", labeled "check phase advancement (HTTP)".

--- ROW 4 (Center, spanning full width) ---
A wide horizontal rectangle with a dashed border is placed below Row 3, spanning the full width. It is colored light purple (#F3E5F5) with a dark purple (#6A1B9A) border. It is labeled "Message Queue (Redis Pub/Sub)" with a queue icon.

From each of the four application services in Row 3, a downward arrow connects to this Message Queue box. These arrows are labeled from left to right: "project.started, project.initialized", "agent.completed, agent.started", "checkpoint.resolved, asset.approved", "metrics.update, intervention.created".

The "WebSocket Hub" in Row 2 has a downward dashed arrow connecting to the Message Queue, labeled "subscribe all events". This indicates the WebSocket Hub consumes events from the queue and pushes them to clients.

--- ROW 5 (Infrastructure Services) ---
Below the Message Queue, three rounded rectangles are arranged in a horizontal row, centered. All three boxes are colored light teal (#E0F2F1) with a dark teal (#00695C) border.

From left to right:

Box 1: "AI Provider Service" — Owns provider registry, health monitoring, API keys. Below the label in smaller text: "Tables: api_key_store, local_provider_configs, global_execution_settings".

Box 2: "LLM Job Queue Service" — Owns job scheduling, concurrency control, token budget check. Below the label in smaller text: "Tables: llm_jobs".

Box 3: "Cost & Budget Service" — Owns cost tracking, budget enforcement, reports. Below the label in smaller text: "Tables: cost_history, global_cost_settings".

Upward arrows from the Message Queue connect to each of these three infrastructure services. The arrows are labeled: "provider.health_changed", "llm_job.submit, llm_job.completed", "llm_job.completed (record cost)".

A horizontal arrow from "LLM Job Queue Service" points left to "AI Provider Service", labeled "get provider, check health (HTTP)".

A horizontal arrow from "LLM Job Queue Service" points right to "Cost & Budget Service", labeled "check budget (HTTP)".

An upward arrow from "LLM Job Queue Service" goes to the Message Queue, labeled "job.result → Agent Service callback".

The "API Gateway" in Row 2 also has three thinner downward arrows that bypass Row 3 and Row 4, connecting directly to these three infrastructure services. These are labeled: "/api/ai-providers/* /api/api-keys/*", "/api/llm-jobs/*", "/api/cost/* /api/config/global-cost-settings".

--- ROW 6 (Bottom) ---
At the bottom-left area, seven small cylinder shapes represent individual PostgreSQL databases, one for each service. They are colored light gray (#F5F5F5) with dark gray (#616161) borders. Each cylinder is labeled with the owning service name: "Project DB", "Agent DB", "Checkpoint & Asset DB", "Operations DB", "AI Provider DB", "LLM Job DB", "Cost DB". Thin downward arrows connect each service in Rows 3 and 5 to its respective database cylinder.

At the bottom-right area, a cloud shape is placed, colored light red (#FFEBEE) with a dark red (#C62828) border, labeled "External LLM APIs". Inside the cloud, three smaller labels read "OpenAI", "Anthropic Claude", "OpenRouter". A thick downward arrow from "LLM Job Queue Service" connects to this cloud shape, labeled "chat / chat_stream (HTTPS)".

--- LEGEND (Bottom-right corner) ---
A small legend box contains:
- Solid arrow: "Synchronous HTTP call"
- Dashed arrow: "Asynchronous message (Redis Pub/Sub)"
- Orange box: "Application Service"
- Teal box: "Infrastructure Service"
- Green box: "Gateway / Hub"
- Cylinder: "PostgreSQL Database"
- Cloud: "External API"

The overall style is minimal, professional, and uses consistent spacing. All text is in English. The diagram title at the very top reads "Toybox - Microservices Architecture" in bold, 24pt font.
```

## サービス一覧と責務

| # | サービス | 責務 | 所有テーブル |
|---|---------|------|-------------|
| 1 | API Gateway | ルーティング、認証、レート制限 | なし |
| 2 | WebSocket Hub | イベント配信、Socket.IO room管理 | なし |
| 3 | Project Service | プロジェクトCRUD、ライフサイクル、設定 | projects, quality_settings, project_ai_configs, system_logs |
| 4 | Agent Service | エージェント実行、DAGスケジューリング、リトライ | agents, agent_logs |
| 5 | Checkpoint & Asset Service | チェックポイント承認、アセット管理 | checkpoints, assets |
| 6 | Operations Service | 介入、ファイル、トレース、メトリクス、バックアップ | interventions, uploaded_files, agent_traces, metrics |
| 7 | AI Provider Service | プロバイダ管理、ヘルスモニタ、APIキー | api_key_store, local_provider_configs, global_execution_settings |
| 8 | LLM Job Queue Service | ジョブスケジューリング、同時実行制御 | llm_jobs |
| 9 | Cost & Budget Service | コスト追跡、予算管理、レポート | cost_history, global_cost_settings |

## 主要データフロー

### エージェント実行フロー
```
Client → API Gateway → Agent Service → Message Queue → LLM Job Queue Service → AI Provider Service → External LLM APIs
                                                     → Cost & Budget Service (record cost)
                                                     → Agent Service (callback with result)
                                                     → WebSocket Hub → Client
```

### チェックポイント承認フロー
```
Client → API Gateway → Checkpoint & Asset Service → Agent Service (update status)
                                                  → Project Service (phase check)
                                                  → Message Queue → WebSocket Hub → Client
```
