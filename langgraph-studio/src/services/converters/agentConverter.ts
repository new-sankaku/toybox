import type{ApiAgent,ApiAgentLog}from'@/services/apiService'
import type{Agent,AgentLogEntry}from'@/types/agent'

export function convertApiAgent(apiAgent:ApiAgent):Agent{
 return{
  id:apiAgent.id,
  projectId:apiAgent.projectId,
  type:apiAgent.type,
  phase:apiAgent.phase??0,
  status:apiAgent.status,
  progress:apiAgent.progress,
  currentTask:apiAgent.currentTask,
  tokensUsed:apiAgent.tokensUsed,
  inputTokens:apiAgent.inputTokens,
  outputTokens:apiAgent.outputTokens,
  startedAt:apiAgent.startedAt,
  completedAt:apiAgent.completedAt,
  error:apiAgent.error,
  parentAgentId:apiAgent.parentAgentId,
  metadata:apiAgent.metadata,
  createdAt:apiAgent.createdAt
 }
}

export function convertApiAgents(apiAgents:ApiAgent[]):Agent[]{
 return apiAgents.map(convertApiAgent)
}

export function convertApiLog(apiLog:ApiAgentLog):AgentLogEntry{
 return{
  id:apiLog.id,
  timestamp:apiLog.timestamp,
  level:apiLog.level,
  message:apiLog.message,
  progress:apiLog.progress??undefined,
  metadata:apiLog.metadata
 }
}

export function convertApiLogs(apiLogs:ApiAgentLog[]):AgentLogEntry[]{
 return apiLogs.map(convertApiLog)
}
