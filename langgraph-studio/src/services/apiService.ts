import axios,{AxiosError}from'axios'
import type{Project}from'@/types/project'
import type{BrushupOptionsConfig,BrushupSuggestImage}from'@/types/brushup'

const API_BASE_URL=(import.meta as unknown as{env:Record<string,string>}).env.VITE_API_BASE_URL||''

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
 },

 brushup:async(projectId:string,options?:{
  selectedAgents?:string[]
  agentOptions?:Record<string,string[]>
  clearAssets?:boolean
  customInstruction?:string
  referenceImageIds?:string[]
 }):Promise<Project>=>{
  const response=await api.post(`/api/projects/${projectId}/brushup`,options||{})
  return response.data
 },

 getBrushupOptions:async():Promise<BrushupOptionsConfig>=>{
  const response=await api.get('/api/brushup/options')
  return response.data
 },

 suggestBrushupImages:async(projectId:string,options:{
  customInstruction?:string
  count?:number
 }):Promise<{images:BrushupSuggestImage[]}>=>{
  const response=await api.post(`/api/projects/${projectId}/brushup/suggest-images`,options)
  return response.data
 }
}

export interface ApiAgent{
 id:string
 projectId:string
 type:string
 phase?:number
 status:'pending'|'running'|'completed'|'failed'|'blocked'|'waiting_approval'|'waiting_response'|'waiting_provider'|'paused'|'interrupted'|'cancelled'
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

 listWorkers:async(agentId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(`/api/agents/${agentId}/workers`)
  return response.data
 },

 getLogs:async(agentId:string):Promise<ApiAgentLog[]>=>{
  const response=await api.get(`/api/agents/${agentId}/logs`)
  return response.data
 },

 retry:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(`/api/agents/${agentId}/retry`)
  return response.data
 },

 getRetryable:async(projectId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(`/api/projects/${projectId}/agents/retryable`)
  return response.data
 },

 getInterrupted:async(projectId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(`/api/projects/${projectId}/agents/interrupted`)
  return response.data
 },

 pause:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(`/api/agents/${agentId}/pause`)
  return response.data
 },

 resume:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(`/api/agents/${agentId}/resume`)
  return response.data
 },

 cancel:async(agentId:string):Promise<{success:boolean;message:string}>=>{
  const response=await api.post(`/api/agents/${agentId}/cancel`)
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

export interface GenerationCount{
 count:number
 unit:string
 calls:number
}

export interface ApiProjectMetrics{
 projectId:string
 totalTokensUsed:number
 totalInputTokens:number
 totalOutputTokens:number
 estimatedTotalTokens:number
 tokensByType?:Record<string,TokensByTypeEntry>
 generationCounts?:Record<string,GenerationCount>
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
 getStats:async(projectId:string):Promise<ApiAIRequestStats>=>{
  const response=await api.get(`/api/projects/${projectId}/ai-requests/stats`)
  return response.data
 }
}

export interface AgentDefinition{
 label:string
 shortLabel:string
 phase:number
 speechBubble:string
 role?:string
 highCost?:boolean
}

export interface UIPhase{
 id:string
 label:string
 agents:string[]
}

export interface AgentDefinitionsResponse{
 agents:Record<string,AgentDefinition>
 uiPhases:UIPhase[]
 agentAssetMapping:Record<string,string[]>
 workflowDependencies:Record<string,string[]>
}

export const agentDefinitionApi={
 getAll:async():Promise<AgentDefinitionsResponse>=>{
  const response=await api.get('/api/agent-definitions')
  return response.data
 }
}

export interface UISettingsAgent{
 label:string
 shortLabel:string
 phase:number
 role:string
 highCost:boolean
}

export interface UISettingsResponse{
 uiPhases:UIPhase[]
 agentServiceMap:Record<string,string>
 serviceLabels:Record<string,string>
 statusLabels:Record<string,string>
 agentStatusLabels:Record<string,string>
 approvalStatusLabels:Record<string,string>
 resolutionLabels:Record<string,string>
 roleLabels:Record<string,string>
 agentRoles:Record<string,string>
 agents:Record<string,UISettingsAgent>
 assetTypeLabels?:Record<string,string>
}

export const uiSettingsApi={
 get:async():Promise<UISettingsResponse>=>{
  const response=await api.get('/api/config/ui-settings')
  return response.data
 }
}


export type InterventionPriority='normal'|'urgent'
export type InterventionTarget='all'|'specific'
export type InterventionStatus='pending'|'delivered'|'acknowledged'|'processed'|'waiting_response'

export interface InterventionResponse{
 sender:'agent'|'operator'
 agentId:string|null
 message:string
 createdAt:string
}

export interface ApiIntervention{
 id:string
 projectId:string
 targetType:InterventionTarget
 targetAgentId:string|null
 priority:InterventionPriority
 message:string
 attachedFileIds:string[]
 status:InterventionStatus
 responses:InterventionResponse[]
 createdAt:string
 deliveredAt:string|null
 acknowledgedAt:string|null
 processedAt:string|null
}

export interface CreateInterventionInput{
 targetType:InterventionTarget
 targetAgentId?:string
 priority:InterventionPriority
 message:string
 attachedFileIds?:string[]
}

export const interventionApi={
 listByProject:async(projectId:string):Promise<ApiIntervention[]>=>{
  const response=await api.get(`/api/projects/${projectId}/interventions`)
  return response.data
 },

 create:async(projectId:string,data:CreateInterventionInput):Promise<ApiIntervention>=>{
  const response=await api.post(`/api/projects/${projectId}/interventions`,data)
  return response.data
 },

 get:async(interventionId:string):Promise<ApiIntervention>=>{
  const response=await api.get(`/api/interventions/${interventionId}`)
  return response.data
 },

 acknowledge:async(interventionId:string):Promise<ApiIntervention>=>{
  const response=await api.post(`/api/interventions/${interventionId}/acknowledge`)
  return response.data
 },

 process:async(interventionId:string):Promise<ApiIntervention>=>{
  const response=await api.post(`/api/interventions/${interventionId}/process`)
  return response.data
 },

 delete:async(interventionId:string):Promise<void>=>{
  await api.delete(`/api/interventions/${interventionId}`)
 },

 respond:async(interventionId:string,message:string):Promise<ApiIntervention>=>{
  const response=await api.post(`/api/interventions/${interventionId}/respond`,{message})
  return response.data
 }
}


export type FileCategory='code'|'image'|'audio'|'video'|'document'|'archive'|'other'
export type UploadedFileStatus='uploading'|'ready'|'processing'|'error'

export interface ApiUploadedFile{
 id:string
 projectId:string
 filename:string
 originalFilename:string
 mimeType:string
 category:FileCategory
 sizeBytes:number
 status:UploadedFileStatus
 description:string
 uploadedAt:string
 url:string
}

export interface BatchUploadResult{
 success:ApiUploadedFile[]
 errors:{filename:string;error:string}[]
 totalUploaded:number
 totalErrors:number
}

export const fileUploadApi={
 listByProject:async(projectId:string):Promise<ApiUploadedFile[]>=>{
  const response=await api.get(`/api/projects/${projectId}/files`)
  return response.data.map((file:ApiUploadedFile)=>({
   ...file,
   url:toFullUrl(file.url)
  }))
 },

 upload:async(projectId:string,file:File,description?:string):Promise<ApiUploadedFile>=>{
  const formData=new FormData()
  formData.append('file',file)
  if(description){
   formData.append('description',description)
  }
  const response=await api.post(`/api/projects/${projectId}/files`,formData,{
   headers:{'Content-Type':'multipart/form-data'}
  })
  return{
   ...response.data,
   url:toFullUrl(response.data.url)
  }
 },

 uploadBatch:async(projectId:string,files:File[]):Promise<BatchUploadResult>=>{
  const formData=new FormData()
  files.forEach(file=>{
   formData.append('files',file)
  })
  const response=await api.post(`/api/projects/${projectId}/files/batch`,formData,{
   headers:{'Content-Type':'multipart/form-data'}
  })
  return{
   ...response.data,
   success:response.data.success.map((file:ApiUploadedFile)=>({
    ...file,
    url:toFullUrl(file.url)
   }))
  }
 },

 get:async(fileId:string):Promise<ApiUploadedFile>=>{
  const response=await api.get(`/api/files/${fileId}`)
  return{
   ...response.data,
   url:toFullUrl(response.data.url)
  }
 },

 delete:async(fileId:string):Promise<void>=>{
  await api.delete(`/api/files/${fileId}`)
 },

 getDownloadUrl:(fileId:string):string=>{
  return`${API_BASE_URL}/api/files/${fileId}/download`
 }
}

export interface ProjectTreeNode{
 id:string
 name:string
 type:'file'|'directory'
 path:string
 modified?:boolean
 children?:ProjectTreeNode[]
 size?:number
 mimeType?:string
}

export const projectTreeApi={
 getTree:async(projectId:string):Promise<ProjectTreeNode>=>{
  const response=await api.get(`/api/projects/${projectId}/tree`)
  return response.data
 },

 downloadFile:async(projectId:string,filePath:string):Promise<Blob>=>{
  const response=await api.get(`/api/projects/${projectId}/tree/download`,{
   params:{path:filePath},
   responseType:'blob'
  })
  return response.data
 },

 replaceFile:async(projectId:string,filePath:string,file:File):Promise<void>=>{
  const formData=new FormData()
  formData.append('file',file)
  formData.append('path',filePath)
  await api.post(`/api/projects/${projectId}/tree/replace`,formData,{
   headers:{'Content-Type':'multipart/form-data'}
  })
 },

 downloadAll:async(projectId:string):Promise<Blob>=>{
  const response=await api.get(`/api/projects/${projectId}/tree/download-all`,{
   responseType:'blob'
  })
  return response.data
 }
}

export interface AIProviderTestResult{
 success:boolean
 message:string
 latency?:number
}

export interface AIProviderModel{
 id:string
 name:string
 maxTokens:number
 supportsVision:boolean
 supportsTools:boolean
 inputCostPer1k:number|null
 outputCostPer1k:number|null
}

export interface AIProviderInfo{
 id:string
 name:string
 models:string[]|AIProviderModel[]
}

export interface AIChatMessage{
 role:'system'|'user'|'assistant'
 content:string
}

export interface AIChatRequest{
 provider?:string
 model?:string
 messages:AIChatMessage[]
 maxTokens?:number
 temperature?:number
 apiKey?:string
}

export interface AIChatResponse{
 content:string
 model:string
 usage:{
  inputTokens:number
  outputTokens:number
  totalTokens:number
 }
 finishReason:string|null
 latency:number
}

export const aiProviderApi={
 list:async():Promise<AIProviderInfo[]>=>{
  const response=await api.get('/api/ai-providers')
  return response.data
 },

 get:async(providerId:string):Promise<AIProviderInfo>=>{
  const response=await api.get(`/api/ai-providers/${providerId}`)
  return response.data
 },

 getModels:async(providerId:string):Promise<AIProviderModel[]>=>{
  const response=await api.get(`/api/ai-providers/${providerId}/models`)
  return response.data
 },

 testConnection:async(providerType:string,config:Record<string,unknown>):Promise<AIProviderTestResult>=>{
  const response=await api.post('/api/ai-providers/test',{providerType,config})
  return response.data
 },

 chat:async(request:AIChatRequest):Promise<AIChatResponse>=>{
  const response=await api.post('/api/ai/chat',request)
  return response.data
 },

 chatStream:async function*(request:AIChatRequest):AsyncGenerator<{content?:string;done?:boolean;usage?:{inputTokens:number;outputTokens:number};error?:string}>{
  const response=await fetch(`${API_BASE_URL}/api/ai/chat/stream`,{
   method:'POST',
   headers:{'Content-Type':'application/json'},
   body:JSON.stringify(request)
  })
  if(!response.ok){
   throw new Error(`HTTP ${response.status}`)
  }
  const reader=response.body?.getReader()
  if(!reader)return
  const decoder=new TextDecoder()
  let buffer=''
  while(true){
   const{done,value}=await reader.read()
   if(done)break
   buffer+=decoder.decode(value,{stream:true})
   const lines=buffer.split('\n')
   buffer=lines.pop()||''
   for(const line of lines){
    if(line.startsWith('data: ')){
     const data=JSON.parse(line.slice(6))
     yield data
    }
   }
  }
 }
}

export interface AIServiceConfig{
 label:string
 description:string
 provider:string
 model:string
}

export type AIServiceType='llm'|'image'|'audio'|'music'

export interface ProjectAIServiceConfig{
 enabled:boolean
 provider:string
 model:string
}

export interface AIServiceMasterModel{
 id:string
 label:string
 recommended?:boolean
}

export interface AIServiceMasterProvider{
 id:string
 label:string
 models:AIServiceMasterModel[]
 defaultModel:string
}

export interface AIServiceMasterService{
 label:string
 providers:AIServiceMasterProvider[]
 default:{provider:string;model:string}
}

export interface UsageCategory{
 id:string
 label:string
 service_type:AIServiceType
 default:{
  provider:string
  model:string
 }
}

export interface AIServiceMasterData{
 serviceTypes:AIServiceType[]
 usageCategories:UsageCategory[]
 services:Record<AIServiceType,AIServiceMasterService>
 providers:Record<string,{
  label:string
  serviceTypes:string[]
  models:AIServiceMasterModel[]
  defaultModel:string
 }>
 providerTypeMapping?:Record<string,string>
 reverseProviderTypeMapping?:Record<string,string>
}

export const aiServiceApi={
 list:async():Promise<Record<AIServiceType,AIServiceConfig>>=>{
  const response=await api.get('/api/ai-services')
  return response.data
 },
 get:async(serviceType:AIServiceType):Promise<AIServiceConfig>=>{
  const response=await api.get(`/api/ai-services/${serviceType}`)
  return response.data
 },
 getMaster:async():Promise<AIServiceMasterData>=>{
  const response=await api.get('/api/config/ai-services')
  return response.data
 },
 getByProject:async(projectId:string):Promise<Record<AIServiceType,ProjectAIServiceConfig>>=>{
  const response=await api.get(`/api/projects/${projectId}/ai-services`)
  return response.data
 },
 updateByProject:async(projectId:string,aiServices:Record<AIServiceType,Partial<ProjectAIServiceConfig>>):Promise<Record<AIServiceType,ProjectAIServiceConfig>>=>{
  const response=await api.put(`/api/projects/${projectId}/ai-services`,aiServices)
  return response.data
 },
 updateServiceByProject:async(projectId:string,serviceType:AIServiceType,config:Partial<ProjectAIServiceConfig>):Promise<ProjectAIServiceConfig>=>{
  const response=await api.patch(`/api/projects/${projectId}/ai-services/${serviceType}`,config)
  return response.data
 }
}

export interface ModelInfo{
 id:string
 label:string
 recommended?:boolean
}

export interface ProviderConfig{
 label:string
 models:ModelInfo[]
 defaultModel:string
 endpoint:string
}

export interface TokenPricing{
 input:number
 output:number
 unit:string
}

export interface ModelsConfig{
 providers:Record<string,ProviderConfig>
 tokenPricing:Record<string,TokenPricing>
 defaults:{temperature:number;maxTokens:number}
 currency:string
}

export interface PlatformOption{
 value:string
 label:string
 description:string
}

export interface ScopeOption{
 value:string
 label:string
 description:string
}

export interface ProjectOptionsConfig{
 platforms:PlatformOption[]
 scopes:ScopeOption[]
 projectTemplates:{value:string;label:string}[]
 scaleOptions?:import('@/config/projectOptions').ProjectScaleOption[]
 assetServiceOptions?:import('@/config/projectOptions').AssetServiceOption[]
 violenceRatingOptions?:import('@/config/projectOptions').ContentRatingOption[]
 sexualRatingOptions?:import('@/config/projectOptions').ContentRatingOption[]
 projectDefaults?:{assetGeneration:import('@/config/projectOptions').AssetGenerationOptions;contentPermissions:import('@/config/projectOptions').ContentPermissions}
 defaults:{platform:string;scope:string;projectTemplate:string}
}

export interface FileExtensionCategory{
 extensions:string[]
 label:string
 mimeTypes:string[]
}

export interface FileExtensionsConfig{
 categories:Record<string,FileExtensionCategory>
 scanDirectories:string[]
 defaultCategory:string
}

export interface WebSocketConfig{
 maxReconnectAttempts:number
 reconnectDelay:number
 reconnectDelayMax:number
 timeout:number
}

export const configApi={
 getModels:async():Promise<ModelsConfig>=>{
  const response=await api.get('/api/config/models')
  return response.data
 },

 getModelPricing:async(modelId:string):Promise<{modelId:string;pricing:TokenPricing}>=>{
  const response=await api.get(`/api/config/models/pricing/${modelId}`)
  return response.data
 },

 getProjectOptions:async():Promise<ProjectOptionsConfig>=>{
  const response=await api.get('/api/config/project-options')
  return response.data
 },

 getFileExtensions:async():Promise<FileExtensionsConfig>=>{
  const response=await api.get('/api/config/file-extensions')
  return response.data
 },

 getAgentsConfig:async():Promise<Record<string,unknown>>=>{
  const response=await api.get('/api/config/agents')
  return response.data
 },

 getBrushupOptions:async():Promise<BrushupOptionsConfig>=>{
  const response=await api.get('/api/brushup/options')
  return response.data
 },

 getWebSocketConfig:async():Promise<WebSocketConfig>=>{
  const response=await api.get('/api/config/websocket')
  return response.data
 }
}

export interface AutoApprovalRuleApi{
 category:string
 enabled:boolean
}

export interface PricingUnit{
 input?:string
 output?:string
}

export interface ModelPricingInfo{
 provider:string
 pricing:Record<string,number>
}

export interface PricingConfigResponse{
 currency:string
 units:Record<string,PricingUnit>
 models:Record<string,ModelPricingInfo>
}

export const costApi={
 getPricing:async():Promise<PricingConfigResponse>=>{
  const response=await api.get('/api/config/pricing')
  return response.data
 }
}

export const autoApprovalApi={
 getRules:async(projectId:string):Promise<{rules:AutoApprovalRuleApi[]}>=>{
  const response=await api.get(`/api/projects/${projectId}/auto-approval-rules`)
  return response.data
 },

 updateRules:async(projectId:string,rules:AutoApprovalRuleApi[]):Promise<{rules:AutoApprovalRuleApi[]}>=>{
  const response=await api.put(`/api/projects/${projectId}/auto-approval-rules`,{rules})
  return response.data
 }
}

export interface LanguageOption{
 value:string
 label:string
 nativeName:string
}

export interface LanguagesConfigResponse{
 defaultPrimary:string
 defaultLanguages:string[]
 languages:LanguageOption[]
}

export const languagesApi={
 getConfig:async():Promise<LanguagesConfigResponse>=>{
  const response=await api.get('/api/languages')
  return response.data
 }
}

export interface OutputSettings{
 default_dir:string
}

export interface CostServiceSettings{
 enabled:boolean
 monthly_limit:number
}

export interface CostSettings{
 global_enabled:boolean
 global_monthly_limit:number
 alert_threshold:number
 stop_on_budget_exceeded:boolean
 services:Record<string,CostServiceSettings>
}

export const projectSettingsApi={
 getAgentServiceMap:async():Promise<Record<string,string>>=>{
  const response=await api.get('/api/config/agent-service-map')
  return response.data
 },

 getOutputSettings:async(projectId:string):Promise<OutputSettings>=>{
  const response=await api.get(`/api/projects/${projectId}/settings/output`)
  return response.data
 },

 updateOutputSettings:async(projectId:string,settings:Partial<OutputSettings>):Promise<OutputSettings>=>{
  const response=await api.put(`/api/projects/${projectId}/settings/output`,settings)
  return response.data
 },

 getCostSettings:async(projectId:string):Promise<CostSettings>=>{
  const response=await api.get(`/api/projects/${projectId}/settings/cost`)
  return response.data
 },

 updateCostSettings:async(projectId:string,settings:Partial<CostSettings>):Promise<CostSettings>=>{
  const response=await api.put(`/api/projects/${projectId}/settings/cost`,settings)
  return response.data
 },

 getAIProviders:async(projectId:string):Promise<unknown[]>=>{
  const response=await api.get(`/api/projects/${projectId}/settings/ai-providers`)
  return response.data
 },

 updateAIProviders:async(projectId:string,providers:unknown[]):Promise<unknown[]>=>{
  const response=await api.put(`/api/projects/${projectId}/settings/ai-providers`,providers)
  return response.data
 }
}

export interface ApiAgentTrace{
 id:string
 projectId:string
 agentId:string
 agentType:string
 status:'running'|'completed'|'error'
 inputContext:Record<string,unknown>|null
 promptSent:string|null
 llmResponse:string|null
 outputData:Record<string,unknown>|null
 tokensInput:number
 tokensOutput:number
 durationMs:number
 errorMessage:string|null
 modelUsed:string|null
 startedAt:string|null
 completedAt:string|null
}

export const traceApi={
 listByProject:async(projectId:string,limit:number=100):Promise<ApiAgentTrace[]>=>{
  const response=await api.get(`/api/projects/${projectId}/traces`,{params:{limit}})
  return response.data
 },

 listByAgent:async(agentId:string):Promise<ApiAgentTrace[]>=>{
  const response=await api.get(`/api/agents/${agentId}/traces`)
  return response.data
 },

 get:async(traceId:string):Promise<ApiAgentTrace>=>{
  const response=await api.get(`/api/traces/${traceId}`)
  return response.data
 },

 deleteByProject:async(projectId:string):Promise<{deleted:number}>=>{
  const response=await api.delete(`/api/projects/${projectId}/traces`)
  return response.data
 }
}

export{api}
