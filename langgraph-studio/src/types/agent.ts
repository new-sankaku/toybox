export type AgentStatus='pending'|'running'|'completed'|'failed'|'blocked'|'waiting_approval'|'waiting_response'|'paused'|'interrupted'|'cancelled'

export type AgentType=
 |'director_phase1'
 |'director_phase2'
 |'director_phase3'
 |'leader_concept'
 |'leader_scenario'
 |'leader_design'
 |'leader_task_split'
 |'leader_code'
 |'leader_asset'
 |'worker_concept'
 |'worker_scenario'
 |'worker_design'
 |'worker_task_split'
 |'worker_code'
 |'worker_asset'
 |'concept'
 |'task_split_1'
 |'concept_detail'
 |'scenario'
 |'world'
 |'character'
 |'game_design'
 |'tech_spec'
 |'task_split_2'
 |'asset_character'
 |'asset_background'
 |'asset_ui'
 |'asset_effect'
 |'asset_bgm'
 |'asset_voice'
 |'asset_sfx'
 |'task_split_3'
 |'code'
 |'event'
 |'ui_integration'
 |'asset_integration'
 |'task_split_4'
 |'unit_test'
 |'integration_test'
 |'integrator'
 |'reviewer'

export interface Agent{
 id:string
 projectId:string
 type:string
 phase?:number
 status:AgentStatus
 progress:number
 currentTask:string|null
 tokensUsed:number
 inputTokens?:number
 outputTokens?:number
 startedAt:string|null
 completedAt:string|null
 error:string|null
 parentAgentId:string|null
 metadata:Record<string,unknown>
 createdAt:string
}

export interface AgentMetrics{
 agentId:string
 agentType:AgentType
 status:AgentStatus
 progress:number
 currentTask:string|null
 tokensUsed:number
 tokensEstimated:number
 runtimeSeconds:number
 estimatedRemainingSeconds:number
 completedTasks:number
 totalTasks:number
 activeSubAgents:number
 subAgentMetrics:AgentMetrics[]
}

export type LogLevel='debug'|'info'|'warn'|'error'

export interface LogEntry{
 id:string
 agentId:string
 level:LogLevel
 message:string
 metadata?:Record<string,unknown>
 timestamp:string
}

export interface AgentLogEntry{
 id:string
 timestamp:string
 level:LogLevel
 message:string
 progress?:number
 metadata?:Record<string,unknown>
}

export interface AgentOutput{
 id:string
 agentId:string
 outputType:OutputType
 content:Record<string,unknown>|null
 filePath:string|null
 tokensUsed:number
 generationTimeMs:number
 createdAt:string
}

export type OutputType=
 |'concept_doc'
 |'design_doc'
 |'scenario_doc'
 |'character_specs'
 |'world_design'
 |'task_breakdown'
 |'code'
 |'asset_image'
 |'asset_audio'
 |'build_result'
 |'test_result'
 |'review_result'

export interface QualityCheckConfig{
 enabled:boolean
 maxRetries:number
 isHighCost:boolean
}

export interface QualityCheckResult{
 passed:boolean
 issues:string[]
 score:number
 retryNeeded:boolean
 humanReviewNeeded:boolean
}
