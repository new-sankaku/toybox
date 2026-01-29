import type{Agent,AgentLogEntry}from'./agent'
import type{Checkpoint}from'./checkpoint'
import type{Project,ProjectMetrics}from'./project'
import type{MessagePriority}from'@/stores/navigatorStore'
import type{Intervention}from'./intervention'
import type{components}from'./api-generated'

type AssetSchema=components['schemas']['AssetSchema']

export interface StateSyncData{
 status?:string
 sid?:string
 project?:Project
 agents?:Agent[]
 checkpoints?:Checkpoint[]
 metrics?:ProjectMetrics
}

export interface AgentEventData{
 agent:Agent
 agentId:string
 projectId:string
 parentAgentId?:string
}

export interface AgentProgressData{
 agentId:string
 projectId:string
 progress?:number
 currentTask?:string
 tokensUsed?:number
 message?:string
}

export interface AgentFailedData{
 agentId:string
 projectId:string
 agent?:Agent
 error?:string
 reason?:string
}

export interface AgentActivatedData{
 agentId:string
 projectId:string
 agent:Agent
 previousStatus?:string
 interventionId:string
}

export interface AgentBudgetExceededData{
 agentId:string
 projectId:string
 used:number
 limit:number
 error:string
}

export interface AgentRetryData{
 agentId:string
 projectId:string
 agent:Agent
 previousStatus:string
}

export interface AgentPausedData{
 agentId:string
 projectId:string
 agent:Agent
 reason?:string
}

export interface AgentResumedData{
 agentId:string
 projectId:string
 agent:Agent
 reason?:string
}

export interface AgentWaitingProviderData{
 agentId:string
 projectId:string
 providerId:string
 attempt:number
}

export interface AgentWaitingResponseData{
 agentId:string
 projectId:string
 agent:Agent
 interventionId?:string
 question?:string
 interventionCount?:number
}

export interface AgentSpeechData{
 agentId:string
 projectId:string
 message:string
 source:'llm'|'pool'
 timestamp:string
}

export interface CheckpointCreatedData{
 checkpoint:Checkpoint
 checkpointId?:string
 projectId:string
 agentId:string
 agentStatus?:string
 autoApproved?:boolean
}

export interface CheckpointResolvedData{
 checkpoint:Checkpoint
 checkpointId?:string
 projectId?:string
 agentId?:string
 agentStatus?:string
 resolution?:string
 feedback?:string
}

export interface AssetCreatedData{
 projectId:string
 asset:AssetSchema
 autoApproved?:boolean
}

export interface AssetUpdatedData{
 projectId:string
 asset:AssetSchema
 autoApproved?:boolean
}

export interface InterventionCreatedData{
 interventionId:string
 projectId:string
 intervention:Intervention
}

export interface InterventionAcknowledgedData{
 interventionId:string
 projectId:string
 intervention?:Intervention
 agentId?:string
}

export interface InterventionProcessedData{
 interventionId:string
 projectId:string
 intervention?:Intervention
}

export interface InterventionDeletedData{
 interventionId:string
 projectId:string
}

export interface InterventionRespondedData{
 interventionId:string
 projectId:string
 message:string
}

export interface InterventionResponseAddedData{
 interventionId:string
 projectId:string
 intervention:Intervention
 sender:'agent'|'operator'
 agentId?:string
}

export interface NavigateData{
 path:string
 params:Record<string,unknown>
}

export interface ProjectInitializedData{
 projectId:string
}

export interface ProjectPausedData{
 projectId:string
 reason:string
 interventionId:string
}

export interface ProjectStatusChangedData{
 projectId:string
 status:string
 previousStatus:string
 retriedAgents?:number
}

export interface AgentLogData{
 agentId:string
 entry:AgentLogEntry
}

export interface ErrorStateData{
 message:string
 code:string
}

export interface WebSocketEventMap{
 'error:state':ErrorStateData
 'connection:state_sync':StateSyncData
 'agent:started':AgentEventData
 'agent:created':AgentEventData
 'agent:progress':AgentProgressData
 'agent:log':AgentLogData
 'agent:completed':AgentEventData
 'agent:failed':AgentFailedData
 'agent:waiting_provider':AgentWaitingProviderData
 'agent:paused':AgentPausedData
 'agent:resumed':AgentResumedData
 'agent:activated':AgentActivatedData
 'agent:waiting_response':AgentWaitingResponseData
 'agent:budget_exceeded':AgentBudgetExceededData
 'agent:retry':AgentRetryData
 'agent:speech':AgentSpeechData
 'checkpoint:created':CheckpointCreatedData
 'checkpoint:resolved':CheckpointResolvedData
 'asset:created':AssetCreatedData
 'asset:updated':AssetUpdatedData
 'intervention:created':InterventionCreatedData
 'intervention:acknowledged':InterventionAcknowledgedData
 'intervention:processed':InterventionProcessedData
 'intervention:deleted':InterventionDeletedData
 'intervention:responded':InterventionRespondedData
 'intervention:response_added':InterventionResponseAddedData
 'navigate':NavigateData
 'project:initialized':ProjectInitializedData
 'project:paused':ProjectPausedData
 'project:status_changed':ProjectStatusChangedData
 'project:updated':Project
 'metrics:update':{projectId:string;metrics:ProjectMetrics}
 'navigator:message':{text:string;priority:MessagePriority;speaker?:string;source?:'server'}
}

export type WebSocketEventName=keyof WebSocketEventMap
