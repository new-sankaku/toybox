import type{Agent,AgentLogEntry}from'./agent'
import type{Checkpoint}from'./checkpoint'
import type{Project,ProjectMetrics,PhaseNumber}from'./project'
import type{MessagePriority}from'@/stores/navigatorStore'

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
 progress:number
 currentTask:string
 tokensUsed:number
 message:string
}

export interface AgentFailedData{
 agentId:string
 projectId?:string
 agent?:Agent
 error:string
}

export interface CheckpointCreatedData{
 checkpoint:Checkpoint
 checkpointId:string
 projectId:string
 agentId:string
 agentStatus?:string
}

export interface CheckpointResolvedData{
 checkpoint:Checkpoint
 checkpointId?:string
 agentId?:string
 agentStatus?:string
}

export interface WebSocketEventMap{
 'connection:state_sync':StateSyncData
 'agent:started':AgentEventData
 'agent:created':AgentEventData
 'agent:running':AgentEventData
 'agent:progress':AgentProgressData
 'agent:log':{agentId:string;entry:AgentLogEntry}
 'agent:completed':AgentEventData
 'agent:failed':AgentFailedData
 'agent:waiting_provider':AgentEventData
 'agent:paused':AgentEventData
 'agent:resumed':AgentEventData
 'agent:activated':AgentEventData
 'agent:waiting_response':AgentEventData
 'checkpoint:created':CheckpointCreatedData
 'checkpoint:resolved':CheckpointResolvedData
 'project:updated':{projectId:string;updates:Partial<Project>}
 'phase:changed':{projectId:string;phase:PhaseNumber;phaseName:string}
 'metrics:update':{projectId:string;metrics:ProjectMetrics}
 'navigator:message':{speaker:string;text:string;priority:MessagePriority;source:'server'}
 'agent:speech':{agentId:string;message:string;source:'llm'|'pool'}
}

export type WebSocketEventName=keyof WebSocketEventMap
