export interface ProjectStatusEvent{
 projectId:string
 oldStatus:string
 newStatus:string
 timestamp:string
}

export interface PhaseChangeEvent{
 projectId:string
 phase:number
 phaseName:string
 timestamp:string
}

export interface AgentStartedEvent{
 agentId:string
 agentType:string
 projectId:string
 timestamp:string
}

export interface AgentProgressEvent{
 agentId:string
 progress:number
 currentTask:string
 completedTasks:number
 totalTasks:number
 timestamp:string
}

export interface AgentCompletedEvent{
 agentId:string
 duration:number
 tokensUsed:number
 outputSummary:string
 timestamp:string
}

export interface AgentFailedEvent{
 agentId:string
 errorType:'timeout'|'llm_error'|'validation_error'|'dependency_error'
 errorMessage:string
 canRetry:boolean
 retryCount:number
 maxRetries:number
 timestamp:string
}

export interface AgentLogEvent{
 agentId:string
 level:'DEBUG'|'INFO'|'WARN'|'ERROR'
 message:string
 metadata?:Record<string,unknown>
 timestamp:string
}

export interface CheckpointCreatedEvent{
 checkpointId:string
 projectId:string
 agentId:string
 checkpointType:string
 title:string
 outputPreview:string
 timestamp:string
}

export interface CheckpointResolvedEvent{
 checkpointId:string
 resolution:'approved'|'rejected'|'changes_requested'
 feedback?:string
 timestamp:string
}

export interface MetricsUpdateEvent{
 projectId:string
 totalTokens:number
 estimatedTotalTokens:number
 elapsedSeconds:number
 estimatedRemainingSeconds:number
 completedTasks:number
 totalTasks:number
 timestamp:string
}

export interface TokensUpdateEvent{
 agentId:string
 tokensUsed:number
 tokensTotal:number
 timestamp:string
}

export interface AgentErrorEvent{
 agentId:string
 errorType:string
 errorMessage:string
 suggestions:string[]
 actions:Array<{label:string;action:string}>
 timestamp:string
}

export interface LLMErrorEvent{
 errorType:'rate_limit'|'token_limit'|'api_error'|'invalid_response'
 errorMessage:string
 retryAfter?:number
 timestamp:string
}

export interface StateErrorEvent{
 errorType:'sync_failed'|'checkpoint_failed'|'restore_failed'
 errorMessage:string
 timestamp:string
}

export interface StateSyncEvent{
 projectId:string
 serverState:{
  currentAgent:string
  progress:number
  completedTasks:number
  totalTasks:number
 }
 hasDiff:boolean
 timestamp:string
}

export interface WebSocketEventMap{
 'project:status_changed':ProjectStatusEvent
 'project:phase_changed':PhaseChangeEvent

 'agent:started':AgentStartedEvent
 'agent:progress':AgentProgressEvent
 'agent:completed':AgentCompletedEvent
 'agent:failed':AgentFailedEvent
 'agent:log':AgentLogEvent

 'checkpoint:created':CheckpointCreatedEvent
 'checkpoint:resolved':CheckpointResolvedEvent

 'metrics:update':MetricsUpdateEvent
 'metrics:tokens':TokensUpdateEvent

 'error:agent':AgentErrorEvent
 'error:llm':LLMErrorEvent
 'error:state':StateErrorEvent

 'connection:state_sync':StateSyncEvent
}

export type WebSocketEventName=keyof WebSocketEventMap
