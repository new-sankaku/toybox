# REST API Data Flow


## Project

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/projects` | list_projects | - | ProjectSchema[] | `Project[]` | - |
| POST | `/api/projects` | create_project | ProjectCreateSchema | ProjectSchema | `Project` | project:updated |
| PATCH | `/api/projects/<project_id>` | update_project | ProjectUpdateSchema | ProjectSchema | `Project` | project:updated |
| DELETE | `/api/projects/<project_id>` | delete_project | - | **UNTYPED** | `void` | - |
| POST | `/api/projects/<project_id>/start` | start_project | - | ProjectSchema | `Project` | project:status_changed |
| POST | `/api/projects/<project_id>/pause` | pause_project | - | ProjectSchema | `Project` | project:status_changed |
| POST | `/api/projects/<project_id>/resume` | resume_project | - | ProjectSchema | `Project` | project:status_changed |
| POST | `/api/projects/<project_id>/initialize` | initialize_project | - | ProjectSchema | `Project` | project:initialized |
| POST | `/api/projects/<project_id>/brushup` | brushup_project | - | ProjectSchema | `Project` | project:status_changed |
| GET | `/api/projects/<project_id>/ai-services` | get_project_ai_services | - | **UNTYPED** | `Record<AIServiceType, ProjectAIServiceConfig>` | - |
| PUT | `/api/projects/<project_id>/ai-services` | update_project_ai_services | - | **UNTYPED** | `Record<AIServiceType, ProjectAIServiceConfig>` | project:updated |
| PATCH | `/api/projects/<project_id>/ai-services/<service_type>` | update_project_ai_service | - | **UNTYPED** | `ProjectAIServiceConfig` | project:updated |

## Agent

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/projects/<project_id>/agents` | list_project_agents | - | AgentSchema[] | `Agent[]` | - |
| GET | `/api/projects/<project_id>/agents/leaders` | list_project_leaders | - | AgentSchema[] | `Agent[]` | - |
| GET | `/api/agents/<agent_id>` | get_agent | - | AgentSchema | `Agent` | - |
| GET | `/api/agents/<agent_id>/workers` | list_agent_workers | - | AgentSchema[] | `Agent[]` | - |
| GET | `/api/agents/<agent_id>/logs` | get_agent_logs | - | **UNTYPED** | `AgentLogEntry[]` | - |
| POST | `/api/agents/<agent_id>/execute` | execute_agent | - | **UNTYPED** | `{success: boolean; output: unknown}` | - |
| POST | `/api/agents/<agent_id>/execute-with-workers` | execute_leader_with_workers | - | **UNTYPED** | `{success: boolean; results: unknown}` | - |
| POST | `/api/agents/<agent_id>/cancel` | cancel_agent | - | **UNTYPED** | `{success: boolean; message: string}` | - |
| POST | `/api/agents/<agent_id>/retry` | retry_agent | - | **UNTYPED** | `{success: boolean; agent: Agent}` | - |
| POST | `/api/agents/<agent_id>/pause` | pause_agent | - | **UNTYPED** | `{success: boolean; agent: Agent}` | agent:paused |
| POST | `/api/agents/<agent_id>/resume` | resume_agent | - | **UNTYPED** | `{success: boolean; agent: Agent}` | agent:resumed |
| GET | `/api/projects/<project_id>/agents/retryable` | get_retryable_agents | - | AgentSchema[] | `Agent[]` | - |
| GET | `/api/projects/<project_id>/agents/interrupted` | get_interrupted_agents | - | AgentSchema[] | `Agent[]` | - |

## Checkpoint

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/projects/<project_id>/checkpoints` | list_project_checkpoints | - | CheckpointSchema[] | `Checkpoint[]` | - |
| POST | `/api/checkpoints/<checkpoint_id>/resolve` | resolve_checkpoint | CheckpointResolveSchema | CheckpointSchema | `Checkpoint` | checkpoint:resolved |

## Metrics

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/projects/<project_id>/ai-requests/stats` | get_ai_request_stats | - | **UNTYPED** | `ApiAIRequestStats` | - |
| GET | `/api/projects/<project_id>/metrics` | get_project_metrics | - | **UNTYPED** | `ProjectMetrics` | - |
| GET | `/api/projects/<project_id>/logs` | get_project_logs | - | **UNTYPED** | `ApiSystemLog[]` | - |
| GET | `/api/projects/<project_id>/assets` | get_project_assets | - | **UNTYPED** | `ApiAsset[]` | - |
| PATCH | `/api/projects/<project_id>/assets/<asset_id>` | update_project_asset | - | **UNTYPED** | `ApiAsset` | asset:updated |
| PATCH | `/api/projects/<project_id>/assets/bulk` | bulk_update_assets | - | **UNTYPED** | `{updated: number; assets: ApiAsset[]}` | assets:bulk_updated |
| POST | `/api/projects/<project_id>/assets/<asset_id>/regenerate` | request_asset_regeneration | - | **UNTYPED** | `{success: boolean; message: string}` | asset:regeneration_requested |

## Intervention

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/projects/<project_id>/interventions` | list_interventions | - | **UNTYPED** | `Intervention[]` | - |
| POST | `/api/projects/<project_id>/interventions` | create_intervention | - | **UNTYPED** | `Intervention` | intervention:created, project:paused, agent:activated, agent:paused |
| GET | `/api/interventions/<intervention_id>` | get_intervention | - | **UNTYPED** | `Intervention` | - |
| POST | `/api/interventions/<intervention_id>/acknowledge` | acknowledge_intervention | - | **UNTYPED** | `Intervention` | intervention:acknowledged |
| POST | `/api/interventions/<intervention_id>/process` | process_intervention | - | **UNTYPED** | `Intervention` | intervention:processed |
| DELETE | `/api/interventions/<intervention_id>` | delete_intervention | - | **UNTYPED** | `void` | intervention:deleted |
| POST | `/api/interventions/<intervention_id>/respond` | respond_to_intervention | - | **UNTYPED** | `Intervention` | intervention:response_added, agent:resumed |
| POST | `/api/interventions/<intervention_id>/agent-question` | agent_question | - | **UNTYPED** | `Intervention` | intervention:response_added, agent:waiting_response |

## File Upload

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/projects/<project_id>/files` | list_uploaded_files | - | **UNTYPED** | `UploadedFile[]` | - |
| POST | `/api/projects/<project_id>/files` | upload_file | - | **UNTYPED** | `UploadedFile` | - |
| POST | `/api/projects/<project_id>/files/batch` | upload_files_batch | - | **UNTYPED** | `{success: UploadedFile[]; errors: object[]; totalUploaded: number; totalErrors: number}` | - |
| GET | `/api/files/<file_id>` | get_uploaded_file_info | - | **UNTYPED** | `UploadedFile` | - |
| DELETE | `/api/files/<file_id>` | delete_uploaded_file | - | **UNTYPED** | `{success: boolean}` | - |
| GET | `/api/files/<file_id>/download` | download_file | - | **UNTYPED** | `Blob` | - |

## Ai Provider

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/ai-providers` | get_ai_providers | - | **UNTYPED** | `AIProviderInfo[]` | - |
| GET | `/api/ai-service-types` | get_ai_service_types | - | **UNTYPED** | `AIServiceTypesInfo` | - |
| GET | `/api/ai-providers/<provider_id>` | get_ai_provider | - | **UNTYPED** | `AIProviderInfo` | - |
| GET | `/api/ai-providers/<provider_id>/models` | get_ai_provider_models | - | **UNTYPED** | `AIProviderModel[]` | - |
| POST | `/api/ai-providers/test` | test_ai_provider | - | **UNTYPED** | `{success: boolean; message: string; latency: number}` | - |
| POST | `/api/ai/chat` | ai_chat | - | **UNTYPED** | `AIChatResponse` | - |
| POST | `/api/ai/chat/stream` | ai_chat_stream | - | **UNTYPED** | `SSE({content} | {done, usage} | {error})` | - |
| GET | `/api/providers/health` | get_providers_health | - | **UNTYPED** | `Record<string, ApiProviderHealth>` | - |
| GET | `/api/providers/monitor` | get_providers_monitor | - | **UNTYPED** | `Record<string, ProviderMonitorInfo>` | - |
| GET | `/api/providers/<provider_id>/logs` | get_provider_logs | - | **UNTYPED** | `ProviderLogEntry[]` | - |
| GET | `/api/providers/<provider_id>/health` | get_provider_health | - | **UNTYPED** | `ApiProviderHealth` | - |
| GET | `/api/api-keys` | get_api_keys | - | **UNTYPED** | `Record<string, {hint: string; isValid: boolean; lastValidatedAt: string | null}>` | - |
| PUT | `/api/api-keys/<provider_id>` | save_api_key | - | **UNTYPED** | `{success: boolean; hint: string; message: string}` | - |
| DELETE | `/api/api-keys/<provider_id>` | delete_api_key | - | **UNTYPED** | `{success: boolean; message: string}` | - |
| POST | `/api/api-keys/<provider_id>/validate` | validate_api_key | - | **UNTYPED** | `{success: boolean; message: string; latency: number}` | - |

## Ai Service

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/ai-services` | get_ai_services | - | **UNTYPED** | `Record<AIServiceType, AIServiceConfig>` | - |
| GET | `/api/ai-services/<service_type>` | get_ai_service | - | **UNTYPED** | `AIServiceConfig` | - |
| GET | `/api/config/ai-services` | get_ai_services_master | - | **UNTYPED** | `AIServiceMasterData` | - |
| GET | `/api/config/ai-providers` | get_ai_providers_master | - | **UNTYPED** | `Record<string, AIProviderMasterInfo>` | - |
| GET | `/api/config/pricing` | get_pricing | - | **UNTYPED** | `PricingConfig` | - |

## Quality Settings

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/projects/<project_id>/settings/quality-check` | get_quality_settings | - | **UNTYPED** | `QualitySettingsResponse` | - |
| PATCH | `/api/projects/<project_id>/settings/quality-check/<agent_type>` | update_quality_setting | - | **UNTYPED** | `{agentType: string; config: QualityCheckConfig}` | - |
| PATCH | `/api/projects/<project_id>/settings/quality-check/bulk` | bulk_update_quality_settings | - | **UNTYPED** | `{updated: Record<string, QualityCheckConfig>; count: number}` | - |
| GET | `/api/settings/quality-check/defaults` | get_default_settings | - | **UNTYPED** | `QualitySettingsDefaultsResponse` | - |
| POST | `/api/projects/<project_id>/settings/quality-check/reset` | reset_quality_settings | - | **UNTYPED** | `{message: string; settings: Record<string, QualityCheckConfig>}` | - |
| GET | `/api/agent-definitions` | get_agent_definitions | - | **UNTYPED** | `AgentDefinitionsResponse` | - |

## Static Config

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/config/project-options` | get_project_options_api | - | **UNTYPED** | `ProjectOptionsConfig` | - |
| GET | `/api/config/file-extensions` | get_file_extensions_api | - | **UNTYPED** | `FileExtensionsConfig` | - |
| GET | `/api/config/agents` | get_agents_config_api | - | **UNTYPED** | `Record<string, unknown>` | - |
| GET | `/api/config/ui-settings` | get_ui_settings_api | - | **UNTYPED** | `UISettingsResponse` | - |
| GET | `/api/config/websocket` | get_websocket_config_api | - | WebSocketSettingsSchema | `WebSocketConfig` | - |

## Backup

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/backups` | list_backups | - | **UNTYPED** | `{backups: ApiBackupEntry[]; info: object}` | - |
| POST | `/api/backups` | create_backup | - | **UNTYPED** | `{success: boolean; path: string}` | - |
| POST | `/api/backups/<backup_name>/restore` | restore_backup | - | **UNTYPED** | `{success: boolean; message: string}` | - |
| DELETE | `/api/backups/<backup_name>` | delete_backup | - | **UNTYPED** | `{success: boolean}` | - |
| GET | `/api/archive/stats` | get_archive_stats | - | **UNTYPED** | `ApiArchiveStats` | - |
| POST | `/api/archive/cleanup` | cleanup_old_data | - | **UNTYPED** | `{success: boolean; deleted: number}` | - |
| GET | `/api/archive/estimate` | estimate_cleanup | - | **UNTYPED** | `ApiCleanupEstimate` | - |
| PUT | `/api/archive/retention` | set_retention | - | **UNTYPED** | `{success: boolean; retentionDays: number}` | - |
| POST | `/api/archive/export` | export_traces | - | **UNTYPED** | `{success: boolean; zipPath: string; zipName: string; zipSize: number}` | - |
| POST | `/api/archive/export-and-cleanup` | export_and_cleanup | - | **UNTYPED** | `{success: boolean; zipPath: string; deleted: number}` | - |
| POST | `/api/archive/auto-archive` | auto_archive_old | - | **UNTYPED** | `{archived: number}` | - |
| GET | `/api/archives` | list_archives | - | **UNTYPED** | `{archives: ApiArchiveEntry[]; info: object}` | - |
| DELETE | `/api/archives/<archive_name>` | delete_archive | - | **UNTYPED** | `{success: boolean}` | - |
| GET | `/api/archives/<archive_name>/download` | download_archive | - | **UNTYPED** | `Blob` | - |

## Global Cost Settings

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/config/global-cost-settings` | get_global_cost_settings | - | GlobalCostSettingsSchema | `GlobalCostSettings` | - |
| PUT | `/api/config/global-cost-settings` | update_global_cost_settings | GlobalCostSettingsUpdateSchema | GlobalCostSettingsSchema | `GlobalCostSettings` | - |
| GET | `/api/cost/budget-status` | get_budget_status | - | BudgetStatusSchema | `BudgetStatus` | - |

## Cost Reports

| Method | Endpoint | Handler | Req Schema | Res Schema | TS Response | WS Events |
|--------|----------|---------|------------|------------|-------------|-----------|
| GET | `/api/cost/history` | get_cost_history | - | CostHistoryResponseSchema | `CostHistoryResponse` | - |
| GET | `/api/cost/summary` | get_cost_summary | - | CostSummarySchema | `CostSummary` | - |
| GET | `/api/cost/export/csv` | export_cost_csv | - | **UNTYPED** | `Blob(text/csv)` | - |
| GET | `/api/cost/export/json` | export_cost_json | - | **UNTYPED** | `Blob(application/json)` | - |

# WebSocket Events

## Server → Client

| Event | TS Type | Data Fields | Room | Emit Sources |
|-------|---------|-------------|------|-------------|
| `connection:state_sync` | `StateSyncData` | status: Optional[str], sid: Optional[str], project: Optional[dict], agents: Optional[list], checkpoints: Optional[list], metrics: Optional[dict] | sid | connect, subscribe_project |
| `error:state` | `**UNTYPED**` | message: str, code: str | sid | subscribe_project, checkpoint_resolve |
| `project:updated` | `{projectId: string; updates: Partial<Project>}` | id: str, name: str, status: str | global | create_project, update_project, update_project_ai_services, update_project_ai_service |
| `project:status_changed` | `**UNTYPED**` | projectId: str, status: str, previousStatus: str, retriedAgents: Optional[int] | global | start_project, pause_project, resume_project, brushup_project |
| `project:initialized` | `**UNTYPED**` | projectId: str | global | initialize_project |
| `project:paused` | `**UNTYPED**` | projectId: str, reason: str, interventionId: str | project:{id} | create_intervention |
| `agent:paused` | `AgentEventData` | agentId: str, projectId: str, agent: dict, reason: Optional[str] | project:{id} | pause_agent, create_intervention |
| `agent:resumed` | `AgentEventData` | agentId: str, projectId: str, agent: dict, reason: Optional[str] | project:{id} | resume_agent, respond_to_intervention |
| `agent:activated` | `AgentEventData` | agentId: str, projectId: str, agent: dict, previousStatus: Optional[str], interventionId: str | project:{id} | create_intervention |
| `agent:waiting_response` | `AgentEventData` | agentId: str, projectId: str, agent: dict, interventionId: str, question: str | project:{id} | agent_question |
| `checkpoint:resolved` | `CheckpointResolvedData` | checkpointId: str, projectId: str, agentId: str, resolution: str, feedback: Optional[str], agentStatus: Optional[str], checkpoint: Optional[dict] | project:{id} | resolve_checkpoint, checkpoint_resolve |
| `asset:updated` | `**UNTYPED**` | projectId: str, asset: dict | project:{id} | update_project_asset |
| `assets:bulk_updated` | `**UNTYPED**` | projectId: str, assets: list, status: str | project:{id} | bulk_update_assets |
| `asset:regeneration_requested` | `**UNTYPED**` | projectId: str, assetId: str, feedback: str | project:{id} | request_asset_regeneration |
| `intervention:created` | `**UNTYPED**` | interventionId: str, projectId: str, intervention: dict | project:{id} | create_intervention |
| `intervention:acknowledged` | `**UNTYPED**` | interventionId: str, projectId: str, intervention: dict | project:{id} | acknowledge_intervention |
| `intervention:processed` | `**UNTYPED**` | interventionId: str, projectId: str, intervention: dict | project:{id} | process_intervention |
| `intervention:deleted` | `**UNTYPED**` | interventionId: str, projectId: str | project:{id} | delete_intervention |
| `intervention:response_added` | `**UNTYPED**` | interventionId: str, projectId: str, intervention: dict, sender: str, agentId: Optional[str] | project:{id} | respond_to_intervention, agent_question |
| `navigator:message` | `{speaker: string; text: string; priority: MessagePriority; source: 'server'}` | speaker: str, text: str, priority: str, source: str | project:{id} | global | broadcast_navigator_message |

## Client → Server

| Event | TS Type | Data Fields |
|-------|---------|-------------|
| `subscribe:project` | `{projectId: string}` | projectId: str |
| `unsubscribe:project` | `{projectId: string}` | projectId: str |
| `checkpoint:resolve` | `{checkpointId: string; resolution: string; feedback?: string}` | checkpointId: str, resolution: str, feedback: Optional[str] |

# Schema Coverage Report

- Total endpoints: **100**
- With Pydantic schema: **22** (22%)
- Without schema (UNTYPED): **78** (78%)

## Untyped Endpoints (need Pydantic schemas)

| Method | Endpoint | Handler | TS Expected |
|--------|----------|---------|-------------|
| DELETE | `/api/projects/<project_id>` | delete_project | `void` |
| GET | `/api/projects/<project_id>/ai-services` | get_project_ai_services | `Record<AIServiceType, ProjectAIServiceConfig>` |
| PUT | `/api/projects/<project_id>/ai-services` | update_project_ai_services | `Record<AIServiceType, ProjectAIServiceConfig>` |
| PATCH | `/api/projects/<project_id>/ai-services/<service_type>` | update_project_ai_service | `ProjectAIServiceConfig` |
| GET | `/api/agents/<agent_id>/logs` | get_agent_logs | `AgentLogEntry[]` |
| POST | `/api/agents/<agent_id>/execute` | execute_agent | `{success: boolean; output: unknown}` |
| POST | `/api/agents/<agent_id>/execute-with-workers` | execute_leader_with_workers | `{success: boolean; results: unknown}` |
| POST | `/api/agents/<agent_id>/cancel` | cancel_agent | `{success: boolean; message: string}` |
| POST | `/api/agents/<agent_id>/retry` | retry_agent | `{success: boolean; agent: Agent}` |
| POST | `/api/agents/<agent_id>/pause` | pause_agent | `{success: boolean; agent: Agent}` |
| POST | `/api/agents/<agent_id>/resume` | resume_agent | `{success: boolean; agent: Agent}` |
| GET | `/api/projects/<project_id>/ai-requests/stats` | get_ai_request_stats | `ApiAIRequestStats` |
| GET | `/api/projects/<project_id>/metrics` | get_project_metrics | `ProjectMetrics` |
| GET | `/api/projects/<project_id>/logs` | get_project_logs | `ApiSystemLog[]` |
| GET | `/api/projects/<project_id>/assets` | get_project_assets | `ApiAsset[]` |
| PATCH | `/api/projects/<project_id>/assets/<asset_id>` | update_project_asset | `ApiAsset` |
| PATCH | `/api/projects/<project_id>/assets/bulk` | bulk_update_assets | `{updated: number; assets: ApiAsset[]}` |
| POST | `/api/projects/<project_id>/assets/<asset_id>/regenerate` | request_asset_regeneration | `{success: boolean; message: string}` |
| GET | `/api/projects/<project_id>/interventions` | list_interventions | `Intervention[]` |
| POST | `/api/projects/<project_id>/interventions` | create_intervention | `Intervention` |
| GET | `/api/interventions/<intervention_id>` | get_intervention | `Intervention` |
| POST | `/api/interventions/<intervention_id>/acknowledge` | acknowledge_intervention | `Intervention` |
| POST | `/api/interventions/<intervention_id>/process` | process_intervention | `Intervention` |
| DELETE | `/api/interventions/<intervention_id>` | delete_intervention | `void` |
| POST | `/api/interventions/<intervention_id>/respond` | respond_to_intervention | `Intervention` |
| POST | `/api/interventions/<intervention_id>/agent-question` | agent_question | `Intervention` |
| GET | `/api/projects/<project_id>/files` | list_uploaded_files | `UploadedFile[]` |
| POST | `/api/projects/<project_id>/files` | upload_file | `UploadedFile` |
| POST | `/api/projects/<project_id>/files/batch` | upload_files_batch | `{success: UploadedFile[]; errors: object[]; totalUploaded: number; totalErrors: number}` |
| GET | `/api/files/<file_id>` | get_uploaded_file_info | `UploadedFile` |
| DELETE | `/api/files/<file_id>` | delete_uploaded_file | `{success: boolean}` |
| GET | `/api/files/<file_id>/download` | download_file | `Blob` |
| GET | `/api/ai-providers` | get_ai_providers | `AIProviderInfo[]` |
| GET | `/api/ai-service-types` | get_ai_service_types | `AIServiceTypesInfo` |
| GET | `/api/ai-providers/<provider_id>` | get_ai_provider | `AIProviderInfo` |
| GET | `/api/ai-providers/<provider_id>/models` | get_ai_provider_models | `AIProviderModel[]` |
| POST | `/api/ai-providers/test` | test_ai_provider | `{success: boolean; message: string; latency: number}` |
| POST | `/api/ai/chat` | ai_chat | `AIChatResponse` |
| POST | `/api/ai/chat/stream` | ai_chat_stream | `SSE({content} | {done, usage} | {error})` |
| GET | `/api/providers/health` | get_providers_health | `Record<string, ApiProviderHealth>` |
| GET | `/api/providers/monitor` | get_providers_monitor | `Record<string, ProviderMonitorInfo>` |
| GET | `/api/providers/<provider_id>/logs` | get_provider_logs | `ProviderLogEntry[]` |
| GET | `/api/providers/<provider_id>/health` | get_provider_health | `ApiProviderHealth` |
| GET | `/api/api-keys` | get_api_keys | `Record<string, {hint: string; isValid: boolean; lastValidatedAt: string | null}>` |
| PUT | `/api/api-keys/<provider_id>` | save_api_key | `{success: boolean; hint: string; message: string}` |
| DELETE | `/api/api-keys/<provider_id>` | delete_api_key | `{success: boolean; message: string}` |
| POST | `/api/api-keys/<provider_id>/validate` | validate_api_key | `{success: boolean; message: string; latency: number}` |
| GET | `/api/ai-services` | get_ai_services | `Record<AIServiceType, AIServiceConfig>` |
| GET | `/api/ai-services/<service_type>` | get_ai_service | `AIServiceConfig` |
| GET | `/api/config/ai-services` | get_ai_services_master | `AIServiceMasterData` |
| GET | `/api/config/ai-providers` | get_ai_providers_master | `Record<string, AIProviderMasterInfo>` |
| GET | `/api/config/pricing` | get_pricing | `PricingConfig` |
| GET | `/api/projects/<project_id>/settings/quality-check` | get_quality_settings | `QualitySettingsResponse` |
| PATCH | `/api/projects/<project_id>/settings/quality-check/<agent_type>` | update_quality_setting | `{agentType: string; config: QualityCheckConfig}` |
| PATCH | `/api/projects/<project_id>/settings/quality-check/bulk` | bulk_update_quality_settings | `{updated: Record<string, QualityCheckConfig>; count: number}` |
| GET | `/api/settings/quality-check/defaults` | get_default_settings | `QualitySettingsDefaultsResponse` |
| POST | `/api/projects/<project_id>/settings/quality-check/reset` | reset_quality_settings | `{message: string; settings: Record<string, QualityCheckConfig>}` |
| GET | `/api/agent-definitions` | get_agent_definitions | `AgentDefinitionsResponse` |
| GET | `/api/config/project-options` | get_project_options_api | `ProjectOptionsConfig` |
| GET | `/api/config/file-extensions` | get_file_extensions_api | `FileExtensionsConfig` |
| GET | `/api/config/agents` | get_agents_config_api | `Record<string, unknown>` |
| GET | `/api/config/ui-settings` | get_ui_settings_api | `UISettingsResponse` |
| GET | `/api/backups` | list_backups | `{backups: ApiBackupEntry[]; info: object}` |
| POST | `/api/backups` | create_backup | `{success: boolean; path: string}` |
| POST | `/api/backups/<backup_name>/restore` | restore_backup | `{success: boolean; message: string}` |
| DELETE | `/api/backups/<backup_name>` | delete_backup | `{success: boolean}` |
| GET | `/api/archive/stats` | get_archive_stats | `ApiArchiveStats` |
| POST | `/api/archive/cleanup` | cleanup_old_data | `{success: boolean; deleted: number}` |
| GET | `/api/archive/estimate` | estimate_cleanup | `ApiCleanupEstimate` |
| PUT | `/api/archive/retention` | set_retention | `{success: boolean; retentionDays: number}` |
| POST | `/api/archive/export` | export_traces | `{success: boolean; zipPath: string; zipName: string; zipSize: number}` |
| POST | `/api/archive/export-and-cleanup` | export_and_cleanup | `{success: boolean; zipPath: string; deleted: number}` |
| POST | `/api/archive/auto-archive` | auto_archive_old | `{archived: number}` |
| GET | `/api/archives` | list_archives | `{archives: ApiArchiveEntry[]; info: object}` |
| DELETE | `/api/archives/<archive_name>` | delete_archive | `{success: boolean}` |
| GET | `/api/archives/<archive_name>/download` | download_archive | `Blob` |
| GET | `/api/cost/export/csv` | export_cost_csv | `Blob(text/csv)` |
| GET | `/api/cost/export/json` | export_cost_json | `Blob(application/json)` |

# WebSocket Type Coverage

- Total server→client events: **20**
- With TS type in WebSocketEventMap: **8** (40%)
- Without TS type: **12** (60%)

## Untyped WS Events

| Event | Server Fields | Sources |
|-------|---------------|---------|
| `error:state` | message: str, code: str | subscribe_project, checkpoint_resolve |
| `project:status_changed` | projectId: str, status: str, previousStatus: str, retriedAgents: Optional[int] | start_project, pause_project, resume_project, brushup_project |
| `project:initialized` | projectId: str | initialize_project |
| `project:paused` | projectId: str, reason: str, interventionId: str | create_intervention |
| `asset:updated` | projectId: str, asset: dict | update_project_asset |
| `assets:bulk_updated` | projectId: str, assets: list, status: str | bulk_update_assets |
| `asset:regeneration_requested` | projectId: str, assetId: str, feedback: str | request_asset_regeneration |
| `intervention:created` | interventionId: str, projectId: str, intervention: dict | create_intervention |
| `intervention:acknowledged` | interventionId: str, projectId: str, intervention: dict | acknowledge_intervention |
| `intervention:processed` | interventionId: str, projectId: str, intervention: dict | process_intervention |
| `intervention:deleted` | interventionId: str, projectId: str | delete_intervention |
| `intervention:response_added` | interventionId: str, projectId: str, intervention: dict, sender: str, agentId: Optional[str] | respond_to_intervention, agent_question |

# Type Mismatch Report

## ProjectSchema ↔ Project — 8 issue(s)

| Field | Issue | Python | TypeScript |
|-------|-------|--------|------------|
| `concept` | TYPE_MISMATCH | Optional[Dict[str, Any]] → Record<string, unknown> | null | GameConcept |
| `status` | TYPE_MISMATCH | str → string | ProjectStatus |
| `currentPhase` | TYPE_MISMATCH | int → number | PhaseNumber |
| `config` | TYPE_MISMATCH | Optional[Dict[str, Any]] → Record<string, unknown> | null | ProjectConfig |
| `aiServices` | MISSING_IN_TS | Optional[Dict[str, Any]] | - |
| `createdAt` | NULLABLE_MISMATCH | nullable (Optional[datetime]) | non-null (string) |
| `updatedAt` | NULLABLE_MISMATCH | nullable (Optional[datetime]) | non-null (string) |
| `outputSettings` | MISSING_IN_TS | Optional[Dict[str, Any]] | - |

## AgentSchema ↔ Agent — 4 issue(s)

| Field | Issue | Python | TypeScript |
|-------|-------|--------|------------|
| `phase` | NULLABLE_MISMATCH | non-null (int) | nullable (number) |
| `status` | TYPE_MISMATCH | str → string | AgentStatus |
| `metadata` | NULLABLE_MISMATCH | nullable (Optional[Dict[str, Any]]) | non-null (Record<string,unknown>) |
| `createdAt` | NULLABLE_MISMATCH | nullable (Optional[datetime]) | non-null (string) |

## CheckpointSchema ↔ Checkpoint — 8 issue(s)

| Field | Issue | Python | TypeScript |
|-------|-------|--------|------------|
| `type` | NULLABLE_MISMATCH | nullable (Optional[str]) | non-null (string) |
| `title` | NULLABLE_MISMATCH | nullable (Optional[str]) | non-null (string) |
| `contentCategory` | MISSING_IN_TS | Optional[str] | - |
| `output` | TYPE_MISMATCH | Optional[Dict[str, Any]] → Record<string, unknown> | null | CheckpointOutput |
| `output` | NULLABLE_MISMATCH | nullable (Optional[Dict[str, Any]]) | non-null (CheckpointOutput) |
| `status` | TYPE_MISMATCH | str → string | CheckpointStatus |
| `createdAt` | NULLABLE_MISMATCH | nullable (Optional[datetime]) | non-null (string) |
| `updatedAt` | NULLABLE_MISMATCH | nullable (Optional[datetime]) | non-null (string) |

## CheckpointResolveSchema ↔ CheckpointResolution — 2 issue(s)

| Field | Issue | Python | TypeScript |
|-------|-------|--------|------------|
| `resolution` | TYPE_MISMATCH | str → string | 'approved'|'rejected'|'revision_requested' |
| `checkpointId` | MISSING_IN_PY | - | string |

## GlobalCostSettingsSchema ↔ GlobalCostSettings — OK

## BudgetStatusSchema ↔ BudgetStatus — OK

## CostHistoryItemSchema ↔ CostHistoryItem — OK

## CostHistoryResponseSchema ↔ CostHistoryResponse — OK

## CostSummarySchema ↔ CostSummary — OK

## CostSummaryByServiceSchema ↔ CostSummaryByService — OK

## CostSummaryByProjectSchema ↔ CostSummaryByProject — OK

## PromptComponentSchema ↔ PromptComponent — OK

## AgentSystemPromptSchema ↔ AgentSystemPrompt — OK


**Summary:** 13 schemas checked, 22 total issues found
