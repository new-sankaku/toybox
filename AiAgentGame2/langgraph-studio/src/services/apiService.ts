import axios,{AxiosError}from'axios'
import type{Project}from'@/types/project'
import type{Agent,AgentLogEntry}from'@/types/agent'
import type{Checkpoint}from'@/types/checkpoint'

const API_BASE_URL='http://localhost:5000'

export interface ApiErrorDetail{
 message:string
 statusCode?:number
 originalError?:unknown
}

export function extractApiError(error:unknown):ApiErrorDetail{
 if(axios.isAxiosError(error)){
  const axiosError=error as AxiosError<{error?:string;message?:string}>

  if(!axiosError.response){
   return{
    message:'サーバーに接続できません。バックエンドが起動しているか確認してください。',
    originalError:error
   }
  }

  const statusCode=axiosError.response.status
  const data=axiosError.response.data
  const serverMessage=data?.error||data?.message

  if(serverMessage){
   return{
    message:serverMessage,
    statusCode,
    originalError:error
   }
  }

  const statusMessages:Record<number,string>={
   400:'リクエストが不正です',
   401:'認証が必要です',
   403:'アクセスが拒否されました',
   404:'リソースが見つかりません',
   500:'サーバー内部エラーが発生しました',
   502:'サーバーが応答しません',
   503:'サービスが一時的に利用できません'
  }

  return{
   message:statusMessages[statusCode]||`エラーが発生しました (HTTP ${statusCode})`,
   statusCode,
   originalError:error
  }
 }

 if(error instanceof Error){
  return{
   message:error.message,
   originalError:error
  }
 }

 return{
  message:'予期しないエラーが発生しました',
  originalError:error
 }
}

const api=axios.create({
 baseURL:API_BASE_URL,
 timeout:10000,
 headers:{
  'Content-Type':'application/json'
 }
})

function toFullUrl(path:string|null):string|null{
 if(!path)return null
 if(path.startsWith('http://')||path.startsWith('https://'))return path
 return`${API_BASE_URL}${path}`
}

export const projectApi={
 list:async():Promise<Project[]>=>{
  const response=await api.get('/api/projects')
  return response.data
 },

 create:async(data:Partial<Project>):Promise<Project>=>{
  const response=await api.post('/api/projects',data)
  return response.data
 },

 update:async(projectId:string,data:Partial<Project>):Promise<Project>=>{
  const response=await api.patch(`/api/projects/${projectId}`,data)
  return response.data
 },

 delete:async(projectId:string):Promise<void>=>{
  await api.delete(`/api/projects/${projectId}`)
 },

 start:async(projectId:string):Promise<Project>=>{
  const response=await api.post(`/api/projects/${projectId}/start`)
  return response.data
 },

 pause:async(projectId:string):Promise<Project>=>{
  const response=await api.post(`/api/projects/${projectId}/pause`)
  return response.data
 },

 resume:async(projectId:string):Promise<Project>=>{
  const response=await api.post(`/api/projects/${projectId}/resume`)
  return response.data
 },

 initialize:async(projectId:string):Promise<Project>=>{
  const response=await api.post(`/api/projects/${projectId}/initialize`)
  return response.data
 }
}

export interface ApiAgent{
 id:string
 projectId:string
 type:string
 status:'pending'|'running'|'completed'|'failed'|'blocked'
 progress:number
 currentTask:string|null
 tokensUsed:number
 inputTokens:number
 outputTokens:number
 startedAt:string|null
 completedAt:string|null
 error:string|null
 parentAgentId:string|null
 metadata:Record<string,unknown>
 createdAt:string
}

export interface ApiAgentLog{
 id:string
 timestamp:string
 level:'debug'|'info'|'warn'|'error'
 message:string
 progress:number|null
 metadata:Record<string,unknown>
}

export const agentApi={
 listByProject:async(projectId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(`/api/projects/${projectId}/agents`)
  return response.data
 },

 getLogs:async(agentId:string):Promise<ApiAgentLog[]>=>{
  const response=await api.get(`/api/agents/${agentId}/logs`)
  return response.data
 }
}

export interface ApiCheckpoint{
 id:string
 projectId:string
 agentId:string
 type:string
 title:string
 description:string
 output:{
  type:string
  format:string
  content:string
  artifacts?:unknown[]
 }
 status:'pending'|'approved'|'rejected'|'revision_requested'
 feedback:string|null
 resolvedAt:string|null
 createdAt:string
 updatedAt:string
}

export const checkpointApi={
 listByProject:async(projectId:string):Promise<ApiCheckpoint[]>=>{
  const response=await api.get(`/api/projects/${projectId}/checkpoints`)
  return response.data
 },

 resolve:async(checkpointId:string,resolution:'approved'|'rejected'|'revision_requested',feedback?:string):Promise<ApiCheckpoint>=>{
  const response=await api.post(`/api/checkpoints/${checkpointId}/resolve`,{
   resolution,
   feedback
  })
  return response.data
 }
}

export interface TokensByTypeEntry{
 input:number
 output:number
}

export interface ApiProjectMetrics{
 projectId:string
 totalTokensUsed:number
 totalInputTokens:number
 totalOutputTokens:number
 estimatedTotalTokens:number
 tokensByType?:Record<string,TokensByTypeEntry>
 elapsedTimeSeconds:number
 estimatedRemainingSeconds:number
 estimatedEndTime:string|null
 completedTasks:number
 totalTasks:number
 progressPercent:number
 currentPhase:number
 phaseName:string
 activeGenerations:number
}

export const metricsApi={
 getByProject:async(projectId:string):Promise<ApiProjectMetrics>=>{
  const response=await api.get(`/api/projects/${projectId}/metrics`)
  return response.data
 }
}

export interface ApiSystemLog{
 id:string
 timestamp:string
 level:'debug'|'info'|'warn'|'error'
 source:string
 message:string
 details:string|null
}

export const logsApi={
 getByProject:async(projectId:string):Promise<ApiSystemLog[]>=>{
  const response=await api.get(`/api/projects/${projectId}/logs`)
  return response.data
 }
}

export interface ApiAsset{
 id:string
 name:string
 type:'image'|'audio'|'document'|'code'|'other'
 agent:string
 size:string
 createdAt:string
 url:string|null
 thumbnail:string|null
 duration:string|null
 content:string|null
 approvalStatus:'approved'|'pending'|'rejected'
}

export const assetApi={
 listByProject:async(projectId:string):Promise<ApiAsset[]>=>{
  const response=await api.get(`/api/projects/${projectId}/assets`)
  return response.data.map((asset:ApiAsset)=>({
   ...asset,
   url:toFullUrl(asset.url),
   thumbnail:toFullUrl(asset.thumbnail),
  }))
 },

 updateStatus:async(projectId:string,assetId:string,status:'approved'|'rejected'):Promise<ApiAsset>=>{
  const response=await api.patch(`/api/projects/${projectId}/assets/${assetId}`,{
   approvalStatus:status
  })
  return{
   ...response.data,
   url:toFullUrl(response.data.url),
   thumbnail:toFullUrl(response.data.thumbnail),
  }
 }
}

export interface QualityCheckConfig{
 enabled:boolean
 maxRetries:number
 isHighCost:boolean
}

export interface QualitySettingsResponse{
 settings:Record<string,QualityCheckConfig>
 phases:Record<string,string[]>
 displayNames:Record<string,string>
}

export interface QualitySettingsDefaultsResponse extends QualitySettingsResponse{
 highCostAgents:string[]
}

export const qualitySettingsApi={
 getByProject:async(projectId:string):Promise<QualitySettingsResponse>=>{
  const response=await api.get(`/api/projects/${projectId}/settings/quality-check`)
  return response.data
 },

 updateSingle:async(
  projectId:string,
  agentType:string,
  config:Partial<QualityCheckConfig>
):Promise<{agentType:string;config:QualityCheckConfig}>=>{
  const response=await api.patch(
   `/api/projects/${projectId}/settings/quality-check/${agentType}`,
   config
)
  return response.data
 },

 bulkUpdate:async(
  projectId:string,
  settings:Record<string,Partial<QualityCheckConfig>>
):Promise<{updated:Record<string,QualityCheckConfig>;count:number}>=>{
  const response=await api.patch(
   `/api/projects/${projectId}/settings/quality-check/bulk`,
   {settings}
)
  return response.data
 },

 getDefaults:async():Promise<QualitySettingsDefaultsResponse>=>{
  const response=await api.get('/api/settings/quality-check/defaults')
  return response.data
 },

 resetToDefaults:async(projectId:string):Promise<{message:string;settings:Record<string,QualityCheckConfig>}>=>{
  const response=await api.post(`/api/projects/${projectId}/settings/quality-check/reset`)
  return response.data
 }
}

export interface ApiAIRequestStats{
 total:number
 processing:number
 pending:number
 completed:number
 failed:number
}

export const aiRequestApi={
 getStats:async(_projectId:string):Promise<ApiAIRequestStats>=>{
  return{
   total:16,
   processing:4,
   pending:4,
   completed:8,
   failed:0
  }
 }
}

export interface AgentDefinition{
 label:string
 shortLabel:string
 phase:number
 speechBubble:string
}

export const agentDefinitionApi={
 getAll:async():Promise<Record<string,AgentDefinition>>=>{
  const response=await api.get('/api/agent-definitions')
  return response.data
 }
}

export{api}
