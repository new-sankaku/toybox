import axios,{AxiosError}from'axios'
import type{Project}from'@/types/project'
import type{BrushupOptionsConfig,BrushupSuggestImage}from'@/types/brushup'
import type{SequenceData,AgentSystemPrompt}from'@/types/agent'
import{API_ENDPOINTS}from'@/constants/api'

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
  const response=await api.get(API_ENDPOINTS.projects.list)
  return response.data
 },

 create:async(data:Partial<Project>):Promise<Project>=>{
  const response=await api.post(API_ENDPOINTS.projects.create,data)
  return response.data
 },

 update:async(projectId:string,data:Partial<Project>):Promise<Project>=>{
  const response=await api.patch(API_ENDPOINTS.projects.update(projectId),data)
  return response.data
 },

 delete:async(projectId:string):Promise<void>=>{
  await api.delete(API_ENDPOINTS.projects.delete(projectId))
 },

 start:async(projectId:string):Promise<Project>=>{
  const response=await api.post(API_ENDPOINTS.projects.start(projectId))
  return response.data
 },

 pause:async(projectId:string):Promise<Project>=>{
  const response=await api.post(API_ENDPOINTS.projects.pause(projectId))
  return response.data
 },

 resume:async(projectId:string):Promise<Project>=>{
  const response=await api.post(API_ENDPOINTS.projects.resume(projectId))
  return response.data
 },

 initialize:async(projectId:string):Promise<Project>=>{
  const response=await api.post(API_ENDPOINTS.projects.initialize(projectId))
  return response.data
 },

 brushup:async(projectId:string,options?:{
  selectedAgents?:string[]
  agentOptions?:Record<string,string[]>
  agentInstructions?:Record<string,string>
  clearAssets?:boolean
  customInstruction?:string
  referenceImageIds?:string[]
 }):Promise<Project>=>{
  const response=await api.post(API_ENDPOINTS.projects.brushup(projectId),options||{})
  return response.data
 },

 getBrushupOptions:async():Promise<BrushupOptionsConfig>=>{
  const response=await api.get(API_ENDPOINTS.brushup.options)
  return response.data
 },

 suggestBrushupImages:async(projectId:string,options:{
  customInstruction?:string
  count?:number
 }):Promise<{images:BrushupSuggestImage[]}>=>{
  const response=await api.post(API_ENDPOINTS.projects.brushupSuggestImages(projectId),options)
  return response.data
 }
}





export interface ApiAgent{
 id:string
 projectId:string
 type:string
 phase?:number
 status:'pending'|'running'|'completed'|'failed'|'waiting_approval'|'waiting_response'|'waiting_provider'|'paused'|'interrupted'
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
  const response=await api.get(API_ENDPOINTS.projects.agents(projectId))
  return response.data
 },

 get:async(agentId:string):Promise<ApiAgent>=>{
  const response=await api.get(API_ENDPOINTS.agents.get(agentId))
  return response.data
 },

 listWorkers:async(agentId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(API_ENDPOINTS.agents.workers(agentId))
  return response.data
 },

 getLogs:async(agentId:string):Promise<ApiAgentLog[]>=>{
  const response=await api.get(API_ENDPOINTS.agents.logs(agentId))
  return response.data
 },

 retry:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(API_ENDPOINTS.agents.retry(agentId))
  return response.data
 },

 getRetryable:async(projectId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(API_ENDPOINTS.projects.agentsRetryable(projectId))
  return response.data
 },

 getInterrupted:async(projectId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(API_ENDPOINTS.projects.agentsInterrupted(projectId))
  return response.data
 },

 pause:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(API_ENDPOINTS.agents.pause(agentId))
  return response.data
 },

 resume:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(API_ENDPOINTS.agents.resume(agentId))
  return response.data
 },

 cancel:async(agentId:string):Promise<{success:boolean;message:string}>=>{
  const response=await api.post(API_ENDPOINTS.agents.cancel(agentId))
  return response.data
 },

 getSequence:async(agentId:string):Promise<SequenceData>=>{
  const response=await api.get(API_ENDPOINTS.agents.sequence(agentId))
  return response.data
 },

 listLeaders:async(projectId:string):Promise<ApiAgent[]>=>{
  const response=await api.get(API_ENDPOINTS.projects.agentsLeaders(projectId))
  return response.data
 },

 execute:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(API_ENDPOINTS.agents.execute(agentId))
  return response.data
 },

 executeWithWorkers:async(agentId:string):Promise<{success:boolean;agent:ApiAgent}>=>{
  const response=await api.post(API_ENDPOINTS.agents.executeWithWorkers(agentId))
  return response.data
 },

 getSystemPrompt:async(agentId:string):Promise<AgentSystemPrompt>=>{
  const response=await api.get(API_ENDPOINTS.agents.systemPrompt(agentId))
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
  const response=await api.get(API_ENDPOINTS.projects.checkpoints(projectId))
  return response.data
 },

 resolve:async(checkpointId:string,resolution:'approved'|'rejected'|'revision_requested',feedback?:string):Promise<ApiCheckpoint>=>{
  const response=await api.post(API_ENDPOINTS.checkpoints.resolve(checkpointId),{
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
  const response=await api.get(API_ENDPOINTS.projects.metrics(projectId))
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
  const response=await api.get(API_ENDPOINTS.projects.logs(projectId))
  return response.data
 }
}





export interface ApiAsset{
 id:string
 agentId:string|null
 name:string
 type:'image'|'audio'|'video'|'document'|'code'|'other'
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
  const response=await api.get(API_ENDPOINTS.projects.assets(projectId))
  return response.data.map((asset:ApiAsset)=>({
   ...asset,
   url:toFullUrl(asset.url),
   thumbnail:toFullUrl(asset.thumbnail),
  }))
 },

 updateStatus:async(projectId:string,assetId:string,status:'approved'|'rejected'):Promise<ApiAsset>=>{
  const response=await api.patch(API_ENDPOINTS.projects.asset(projectId,assetId),{
   approvalStatus:status
  })
  return{
   ...response.data,
   url:toFullUrl(response.data.url),
   thumbnail:toFullUrl(response.data.thumbnail),
  }
 },

 bulkUpdateStatus:async(projectId:string,assetIds:string[],status:'approved'|'rejected'):Promise<{updated:number;assets:ApiAsset[]}>=>{
  const response=await api.patch(API_ENDPOINTS.projects.assetsBulk(projectId),{
   assetIds,
   approvalStatus:status
  })
  return{
   updated:response.data.updated,
   assets:response.data.assets.map((a:ApiAsset)=>({
    ...a,
    url:toFullUrl(a.url),
    thumbnail:toFullUrl(a.thumbnail),
   }))
  }
 },

 requestRegeneration:async(projectId:string,assetId:string,feedback:string):Promise<{success:boolean;message:string}>=>{
  const response=await api.post(API_ENDPOINTS.projects.assetRegenerate(projectId,assetId),{
   feedback
  })
  return response.data
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
  const response=await api.get(API_ENDPOINTS.projects.settings.qualityCheck(projectId))
  return response.data
 },

 updateSingle:async(
  projectId:string,
  agentType:string,
  config:Partial<QualityCheckConfig>
):Promise<{agentType:string;config:QualityCheckConfig}>=>{
  const response=await api.patch(
   API_ENDPOINTS.projects.settings.qualityCheckAgent(projectId,agentType),
   config
)
  return response.data
 },

 bulkUpdate:async(
  projectId:string,
  settings:Record<string,Partial<QualityCheckConfig>>
):Promise<{updated:Record<string,QualityCheckConfig>;count:number}>=>{
  const response=await api.patch(
   API_ENDPOINTS.projects.settings.qualityCheckBulk(projectId),
   {settings}
)
  return response.data
 },

 getDefaults:async():Promise<QualitySettingsDefaultsResponse>=>{
  const response=await api.get(API_ENDPOINTS.settings.qualityCheckDefaults)
  return response.data
 },

 resetToDefaults:async(projectId:string):Promise<{message:string;settings:Record<string,QualityCheckConfig>}>=>{
  const response=await api.post(API_ENDPOINTS.projects.settings.qualityCheckReset(projectId))
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
  const response=await api.get(API_ENDPOINTS.projects.aiRequests(projectId))
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
  const response=await api.get(API_ENDPOINTS.agentDefinitions)
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
 checkpointTypeLabels:Record<string,string>
 agentRoles:Record<string,string>
 agents:Record<string,UISettingsAgent>
 assetTypeLabels?:Record<string,string>
}

export const uiSettingsApi={
 get:async():Promise<UISettingsResponse>=>{
  const response=await api.get(API_ENDPOINTS.config.uiSettings)
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
  const response=await api.get(API_ENDPOINTS.projects.interventions(projectId))
  return response.data
 },

 create:async(projectId:string,data:CreateInterventionInput):Promise<ApiIntervention>=>{
  const response=await api.post(API_ENDPOINTS.projects.interventions(projectId),data)
  return response.data
 },

 get:async(interventionId:string):Promise<ApiIntervention>=>{
  const response=await api.get(API_ENDPOINTS.interventions.get(interventionId))
  return response.data
 },

 acknowledge:async(interventionId:string):Promise<ApiIntervention>=>{
  const response=await api.post(API_ENDPOINTS.interventions.acknowledge(interventionId))
  return response.data
 },

 process:async(interventionId:string):Promise<ApiIntervention>=>{
  const response=await api.post(API_ENDPOINTS.interventions.process(interventionId))
  return response.data
 },

 delete:async(interventionId:string):Promise<void>=>{
  await api.delete(API_ENDPOINTS.interventions.delete(interventionId))
 },

 respond:async(interventionId:string,message:string):Promise<ApiIntervention>=>{
  const response=await api.post(API_ENDPOINTS.interventions.respond(interventionId),{message})
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
  const response=await api.get(API_ENDPOINTS.projects.files(projectId))
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
  const response=await api.post(API_ENDPOINTS.projects.files(projectId),formData,{
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
  const response=await api.post(API_ENDPOINTS.projects.filesBatch(projectId),formData,{
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
  const response=await api.get(API_ENDPOINTS.files.get(fileId))
  return{
   ...response.data,
   url:toFullUrl(response.data.url)
  }
 },

 delete:async(fileId:string):Promise<void>=>{
  await api.delete(API_ENDPOINTS.files.delete(fileId))
 },

 getDownloadUrl:(fileId:string):string=>{
  return`${API_BASE_URL}${API_ENDPOINTS.files.download(fileId)}`
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
  const response=await api.get(API_ENDPOINTS.projects.tree(projectId))
  return response.data
 },

 downloadFile:async(projectId:string,filePath:string):Promise<Blob>=>{
  const response=await api.get(API_ENDPOINTS.projects.treeDownload(projectId),{
   params:{path:filePath},
   responseType:'blob'
  })
  return response.data
 },

 replaceFile:async(projectId:string,filePath:string,file:File):Promise<void>=>{
  const formData=new FormData()
  formData.append('file',file)
  formData.append('path',filePath)
  await api.post(API_ENDPOINTS.projects.treeReplace(projectId),formData,{
   headers:{'Content-Type':'multipart/form-data'}
  })
 },

 downloadAll:async(projectId:string):Promise<Blob>=>{
  const response=await api.get(API_ENDPOINTS.projects.treeDownloadAll(projectId),{
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
 serviceTypes?:string[]
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

export interface AIServiceTypesInfo{
 types:string[]
 labels:Record<string,string>
}

export const aiProviderApi={
 list:async():Promise<AIProviderInfo[]>=>{
  const response=await api.get(API_ENDPOINTS.aiProviders.list)
  return response.data
 },

 get:async(providerId:string):Promise<AIProviderInfo>=>{
  const response=await api.get(API_ENDPOINTS.aiProviders.get(providerId))
  return response.data
 },

 getServiceTypes:async():Promise<AIServiceTypesInfo>=>{
  const response=await api.get(API_ENDPOINTS.aiProviders.serviceTypes)
  return response.data
 },

 getModels:async(providerId:string):Promise<AIProviderModel[]>=>{
  const response=await api.get(API_ENDPOINTS.aiProviders.models(providerId))
  return response.data
 },

 testConnection:async(providerType:string,config:Record<string,unknown>):Promise<AIProviderTestResult>=>{
  const response=await api.post(API_ENDPOINTS.aiProviders.test,{providerType,config})
  return response.data
 },

 chat:async(request:AIChatRequest):Promise<AIChatResponse>=>{
  const response=await api.post(API_ENDPOINTS.ai.chat,request)
  return response.data
 },

 chatStream:async function*(request:AIChatRequest):AsyncGenerator<{content?:string;done?:boolean;usage?:{inputTokens:number;outputTokens:number};error?:string}>{
  const response=await fetch(`${API_BASE_URL}${API_ENDPOINTS.ai.chatStream}`,{
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
  const response=await api.get(API_ENDPOINTS.aiServices.list)
  return response.data
 },
 get:async(serviceType:AIServiceType):Promise<AIServiceConfig>=>{
  const response=await api.get(API_ENDPOINTS.aiServices.get(serviceType))
  return response.data
 },
 getMaster:async():Promise<AIServiceMasterData>=>{
  const response=await api.get(API_ENDPOINTS.aiServices.master)
  return response.data
 },
 getByProject:async(projectId:string):Promise<Record<AIServiceType,ProjectAIServiceConfig>>=>{
  const response=await api.get(API_ENDPOINTS.projects.aiServices(projectId))
  return response.data
 },
 updateByProject:async(projectId:string,aiServices:Record<AIServiceType,Partial<ProjectAIServiceConfig>>):Promise<Record<AIServiceType,ProjectAIServiceConfig>>=>{
  const response=await api.put(API_ENDPOINTS.projects.aiServices(projectId),aiServices)
  return response.data
 },
 updateServiceByProject:async(projectId:string,serviceType:AIServiceType,config:Partial<ProjectAIServiceConfig>):Promise<ProjectAIServiceConfig>=>{
  const response=await api.patch(API_ENDPOINTS.projects.aiService(projectId,serviceType),config)
  return response.data
 }
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
 getProjectOptions:async():Promise<ProjectOptionsConfig>=>{
  const response=await api.get(API_ENDPOINTS.config.projectOptions)
  return response.data
 },

 getFileExtensions:async():Promise<FileExtensionsConfig>=>{
  const response=await api.get(API_ENDPOINTS.config.fileExtensions)
  return response.data
 },

 getAgentsConfig:async():Promise<Record<string,unknown>>=>{
  const response=await api.get(API_ENDPOINTS.config.agents)
  return response.data
 },

 getBrushupOptions:async():Promise<BrushupOptionsConfig>=>{
  const response=await api.get(API_ENDPOINTS.brushup.options)
  return response.data
 },

 getWebSocketConfig:async():Promise<WebSocketConfig>=>{
  const response=await api.get(API_ENDPOINTS.config.websocket)
  return response.data
 },

 getCostSettingsDefaults:async():Promise<CostSettings>=>{
  const response=await api.get(API_ENDPOINTS.config.costSettingsDefaults)
  return response.data
 },

 getOutputSettingsDefaults:async():Promise<OutputSettings>=>{
  const response=await api.get(API_ENDPOINTS.config.outputSettingsDefaults)
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
  const response=await api.get(API_ENDPOINTS.config.pricing)
  return response.data
 }
}

export const autoApprovalApi={
 getRules:async(projectId:string):Promise<{rules:AutoApprovalRuleApi[]}>=>{
  const response=await api.get(API_ENDPOINTS.projects.autoApprovalRules(projectId))
  return response.data
 },

 updateRules:async(projectId:string,rules:AutoApprovalRuleApi[]):Promise<{rules:AutoApprovalRuleApi[]}>=>{
  const response=await api.put(API_ENDPOINTS.projects.autoApprovalRules(projectId),{rules})
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
  const response=await api.get(API_ENDPOINTS.languages)
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

export interface AdvancedQualityCheckSettings{
 quality_threshold:number
 escalation:{
  enabled:boolean
  tier2_score_min:number
  tier2_score_max:number
 }
}

export interface ToolExecutionLimits{
 max_iterations:number
 timeout_seconds:number
 loop_detection_threshold:number
}

export interface DagExecutionSettings{
 enabled:boolean
}

export interface TokenBudgetSettings{
 default_limit:number
 warning_threshold_percent:number
 enforcement:'hard'|'soft'
}

export interface ContextPolicySettings{
 auto_downgrade_threshold:number
 summary_max_length:number
 leader_output_max_for_worker:number
 retry_previous_output_max:number
 llm_summary:{
  enabled:boolean
  usage_category:string
  max_tokens:number
  min_content_length:number
  input_max_length:number
 }
 summary_directive:string
}

export interface AdvancedSettingsResponse{
 qualityCheck:AdvancedQualityCheckSettings
 toolExecution:ToolExecutionLimits
 dagExecution:DagExecutionSettings
 temperatureDefaults:Record<string,number>
 tokenBudget:TokenBudgetSettings
 contextPolicy:ContextPolicySettings
}

export interface ConcurrentLimitsSettings{
 default_max_concurrent:number
 provider_overrides:Record<string,number>
}

export const projectSettingsApi={
 getAgentServiceMap:async():Promise<Record<string,string>>=>{
  const response=await api.get(API_ENDPOINTS.config.agentServiceMap)
  return response.data
 },

 getOutputSettings:async(projectId:string):Promise<OutputSettings>=>{
  const response=await api.get(API_ENDPOINTS.projects.settings.output(projectId))
  return response.data
 },

 updateOutputSettings:async(projectId:string,settings:Partial<OutputSettings>):Promise<OutputSettings>=>{
  const response=await api.put(API_ENDPOINTS.projects.settings.output(projectId),settings)
  return response.data
 },

 getCostSettings:async(projectId:string):Promise<CostSettings>=>{
  const response=await api.get(API_ENDPOINTS.projects.settings.cost(projectId))
  return response.data
 },

 updateCostSettings:async(projectId:string,settings:Partial<CostSettings>):Promise<CostSettings>=>{
  const response=await api.put(API_ENDPOINTS.projects.settings.cost(projectId),settings)
  return response.data
 },

 getAIProviders:async(projectId:string):Promise<unknown[]>=>{
  const response=await api.get(API_ENDPOINTS.projects.settings.aiProviders(projectId))
  return response.data
 },

 updateAIProviders:async(projectId:string,providers:unknown[]):Promise<unknown[]>=>{
  const response=await api.put(API_ENDPOINTS.projects.settings.aiProviders(projectId),providers)
  return response.data
 },

 getAdvancedSettingsDefaults:async():Promise<AdvancedSettingsResponse>=>{
  const response=await api.get(API_ENDPOINTS.config.advancedSettingsDefaults)
  return response.data
 },

 getAdvancedSettings:async(projectId:string):Promise<AdvancedSettingsResponse>=>{
  const response=await api.get(API_ENDPOINTS.projects.settings.advanced(projectId))
  return response.data
 },

 updateAdvancedSettings:async(projectId:string,settings:Partial<AdvancedSettingsResponse>):Promise<AdvancedSettingsResponse>=>{
  const response=await api.put(API_ENDPOINTS.projects.settings.advanced(projectId),settings)
  return response.data
 },

 getConcurrentLimitsDefaults:async():Promise<ConcurrentLimitsSettings>=>{
  const response=await api.get(API_ENDPOINTS.config.concurrentLimitsDefaults)
  return response.data
 },

 getConcurrentLimits:async():Promise<ConcurrentLimitsSettings>=>{
  const response=await api.get(API_ENDPOINTS.config.concurrentLimits)
  return response.data
 },

 updateConcurrentLimits:async(settings:Partial<ConcurrentLimitsSettings>):Promise<ConcurrentLimitsSettings>=>{
  const response=await api.put(API_ENDPOINTS.config.concurrentLimits,settings)
  return response.data
 },

 updateWebSocketConfig:async(settings:Partial<WebSocketConfig>):Promise<WebSocketConfig>=>{
  const response=await api.put(API_ENDPOINTS.config.websocket,settings)
  return response.data
 },

 getUsageCategories:async(projectId:string):Promise<UsageCategorySetting[]>=>{
  const response=await api.get(API_ENDPOINTS.projects.settings.usageCategories(projectId))
  return response.data
 },

 updateUsageCategory:async(projectId:string,categoryId:string,settings:{provider:string;model:string}):Promise<UsageCategorySetting>=>{
  const response=await api.put(API_ENDPOINTS.projects.settings.usageCategory(projectId,categoryId),settings)
  return response.data
 },

 resetUsageCategory:async(projectId:string,categoryId:string):Promise<UsageCategorySetting>=>{
  const response=await api.delete(API_ENDPOINTS.projects.settings.usageCategory(projectId,categoryId))
  return response.data
 },

 getPrinciplesList:async():Promise<PrinciplesListResponse>=>{
  const response=await api.get(API_ENDPOINTS.config.principles)
  return response.data
 },

 getProjectPrinciples:async(projectId:string):Promise<ProjectPrinciplesResponse>=>{
  const response=await api.get(API_ENDPOINTS.projects.settings.principles(projectId))
  return response.data
 },

 updateProjectPrinciples:async(projectId:string,settings:{overrides?:Record<string,string[]>;enabledPrinciples?:string[]}):Promise<ProjectPrinciplesResponse>=>{
  const response=await api.put(API_ENDPOINTS.projects.settings.principles(projectId),settings)
  return response.data
 }
}

export interface PrincipleInfo{
 id:string
 label:string
 description:string
}

export interface PrinciplesListResponse{
 principles:PrincipleInfo[]
 defaults:Record<string,string[]>
}

export interface ProjectPrinciplesResponse{
 defaults:Record<string,string[]>
 overrides:Record<string,string[]>
 enabledPrinciples:string[]|null
}

export interface UsageCategorySetting{
 id:string
 label:string
 service_type:string
 provider:string
 model:string
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
  const response=await api.get(API_ENDPOINTS.projects.traces(projectId),{params:{limit}})
  return response.data
 },

 listByAgent:async(agentId:string):Promise<ApiAgentTrace[]>=>{
  const response=await api.get(API_ENDPOINTS.agents.traces(agentId))
  return response.data
 },

 get:async(traceId:string):Promise<ApiAgentTrace>=>{
  const response=await api.get(API_ENDPOINTS.traces.get(traceId))
  return response.data
 },

 deleteByProject:async(projectId:string):Promise<{deleted:number}>=>{
  const response=await api.delete(API_ENDPOINTS.projects.traces(projectId))
  return response.data
 }
}

export interface ApiLlmJob{
 id:string
 projectId:string
 agentId:string
 providerId:string
 model:string
 status:string
 priority:number
 systemPrompt:string|null
 prompt:string|null
 maxTokens:number
 responseContent:string|null
 tokensInput:number
 tokensOutput:number
 errorMessage:string|null
 retryCount:number
 externalJobId:string|null
 createdAt:string|null
 startedAt:string|null
 completedAt:string|null
}

export const llmJobApi={
 get:async(jobId:string):Promise<ApiLlmJob>=>{
  const response=await api.get(API_ENDPOINTS.llmJobs.get(jobId))
  return response.data
 }
}





export interface ApiBackupEntry{
 name:string
 size:number
 createdAt:string
}

export const backupApi={
 list:async():Promise<ApiBackupEntry[]>=>{
  const response=await api.get(API_ENDPOINTS.backups.list)
  return response.data.backups||[]
 },
 create:async():Promise<ApiBackupEntry>=>{
  const response=await api.post(API_ENDPOINTS.backups.create)
  return response.data
 },
 restore:async(backupName:string):Promise<{success:boolean;message:string}>=>{
  const response=await api.post(API_ENDPOINTS.backups.restore(backupName))
  return response.data
 },
 delete:async(backupName:string):Promise<void>=>{
  await api.delete(API_ENDPOINTS.backups.delete(backupName))
 }
}

export interface ApiArchiveEntry{
 name:string
 size:number
 createdAt:string
}

export interface ApiArchiveStats{
 total:{traces:number;agent_logs:number;system_logs:number}
 older_than_retention:{traces:number;agent_logs:number;system_logs:number}
 retention_days:number
 cutoff_date:string
}

export interface ApiCleanupEstimate{
 traces:number
 agent_logs:number
 system_logs:number
}

export interface ApiCleanupResult{
 success:boolean
 deleted:{traces:number;agent_logs:number;system_logs:number}
}

export const archiveApi={
 getStats:async(projectId?:string):Promise<ApiArchiveStats>=>{
  const response=await api.get(API_ENDPOINTS.archives.stats,{params:projectId?{projectId}:undefined})
  return response.data
 },
 cleanup:async(projectId?:string):Promise<ApiCleanupResult>=>{
  const response=await api.post(API_ENDPOINTS.archives.cleanup,projectId?{projectId}:{})
  return response.data
 },
 estimate:async(projectId?:string):Promise<ApiCleanupEstimate>=>{
  const response=await api.get(API_ENDPOINTS.archives.estimate,{params:projectId?{projectId}:undefined})
  return response.data
 },
 setRetention:async(days:number):Promise<{retentionDays:number}>=>{
  const response=await api.put(API_ENDPOINTS.archives.retention,{retentionDays:days})
  return response.data
 },
 export:async(projectId:string):Promise<{filename:string}>=>{
  const response=await api.post(API_ENDPOINTS.archives.export,{projectId})
  return response.data
 },
 exportAndCleanup:async(projectId:string):Promise<{filename:string;deleted:number}>=>{
  const response=await api.post(API_ENDPOINTS.archives.exportAndCleanup,{projectId})
  return response.data
 },
 autoArchive:async():Promise<{archived:number}>=>{
  const response=await api.post(API_ENDPOINTS.archives.autoArchive)
  return response.data
 },
 list:async():Promise<ApiArchiveEntry[]>=>{
  const response=await api.get(API_ENDPOINTS.archives.list)
  return response.data.archives||[]
 },
 delete:async(archiveName:string):Promise<void>=>{
  await api.delete(API_ENDPOINTS.archives.delete(archiveName))
 },
 getDownloadUrl:(archiveName:string):string=>{
  return`${API_BASE_URL}${API_ENDPOINTS.archives.download(archiveName)}`
 }
}

export interface ApiRecoveryStatus{
 interruptedAgents:number
 interruptedProjects:number
}

export const recoveryApi={
 getStatus:async():Promise<ApiRecoveryStatus>=>{
  const response=await api.get(API_ENDPOINTS.recovery.status)
  return response.data
 },
 retryAll:async():Promise<{retriedCount:number}>=>{
  const response=await api.post(API_ENDPOINTS.recovery.retryAll)
  return response.data
 }
}





export interface ApiSystemStats{
 backups:{count:number;totalSize:number}
 archives:ApiArchiveStats
 rateLimiter:{activeKeys:number}
}

export const systemApi={
 getStats:async():Promise<ApiSystemStats>=>{
  const response=await api.get(API_ENDPOINTS.system.stats)
  return response.data
 }
}





export interface ApiKeyInfo{
 providerId:string
 hint:string
 validated:boolean
 validatedAt:string|null
 latencyMs:number|null
}

export interface ApiKeyValidationResult{
 success:boolean
 message:string
 latencyMs:number
}

export const apiKeyApi={
 list:async():Promise<ApiKeyInfo[]>=>{
  const response=await api.get(API_ENDPOINTS.apiKeys.list)
  const data=response.data as Record<string,{hint:string;isValid:boolean;lastValidatedAt:string|null}>
  return Object.entries(data).map(([providerId,info])=>({
   providerId,
   hint:info.hint,
   validated:info.isValid,
   validatedAt:info.lastValidatedAt,
   latencyMs:null
  }))
 },
 save:async(providerId:string,apiKey:string):Promise<{success:boolean}>=>{
  const response=await api.put(API_ENDPOINTS.apiKeys.save(providerId),{apiKey})
  return response.data
 },
 delete:async(providerId:string):Promise<void>=>{
  await api.delete(API_ENDPOINTS.apiKeys.delete(providerId))
 },
 validate:async(providerId:string):Promise<ApiKeyValidationResult>=>{
  const response=await api.post(API_ENDPOINTS.apiKeys.validate(providerId))
  return response.data
 }
}





export interface ApiProviderHealth{
 providerId:string
 healthy:boolean
 latencyMs:number|null
 lastChecked:string|null
 error:string|null
}

export const providerHealthApi={
 getAll:async():Promise<ApiProviderHealth[]>=>{
  const response=await api.get(API_ENDPOINTS.providers.health)
  return response.data
 },
 check:async(providerId:string):Promise<ApiProviderHealth>=>{
  const response=await api.get(API_ENDPOINTS.providers.healthCheck(providerId))
  return response.data
 }
}





export const navigatorApi={
 sendMessage:async(data:{projectId?:string;text:string;priority?:string}):Promise<{success:boolean}>=>{
  const response=await api.post(API_ENDPOINTS.navigator.message,data)
  return response.data
 },
 broadcast:async(data:{text:string;priority?:string}):Promise<{success:boolean}>=>{
  const response=await api.post(API_ENDPOINTS.navigator.broadcast,data)
  return response.data
 }
}





export interface GlobalCostSettings{
 global_enabled:boolean
 global_monthly_limit:number
 alert_threshold:number
 stop_on_budget_exceeded:boolean
 services:Record<string,{enabled:boolean;monthly_limit:number}>
 updated_at:string|null
}

export interface BudgetStatus{
 current_usage:number
 monthly_limit:number
 remaining:number
 usage_percent:number
 alert_threshold:number
 is_over_budget:boolean
 is_warning:boolean
 stop_on_budget_exceeded:boolean
 global_enabled:boolean
}

export const globalCostApi={
 getSettings:async():Promise<GlobalCostSettings>=>{
  const response=await api.get(API_ENDPOINTS.globalCost.settings)
  return response.data
 },
 updateSettings:async(data:Partial<GlobalCostSettings>):Promise<GlobalCostSettings>=>{
  const response=await api.put(API_ENDPOINTS.globalCost.settings,data)
  return response.data
 },
 getBudgetStatus:async():Promise<BudgetStatus>=>{
  const response=await api.get(API_ENDPOINTS.globalCost.budgetStatus)
  return response.data
 }
}





export interface CostHistoryItem{
 id:string
 project_id:string
 agent_id:string|null
 agent_type:string|null
 service_type:string
 provider_id:string|null
 model_id:string|null
 input_tokens:number
 output_tokens:number
 unit_count:number
 cost_usd:number
 recorded_at:string|null
 metadata:Record<string,unknown>|null
}

export interface CostHistoryResponse{
 items:CostHistoryItem[]
 total:number
 limit:number
 offset:number
}

export interface CostSummary{
 year:number
 month:number
 total_cost:number
 by_service:Record<string,{input_tokens:number;output_tokens:number;call_count:number}>
 by_project:Record<string,{call_count:number}>
}

export const costReportApi={
 getHistory:async(params?:{project_id?:string;year?:number;month?:number;limit?:number;offset?:number}):Promise<CostHistoryResponse>=>{
  const response=await api.get(API_ENDPOINTS.cost.history,{params})
  return response.data
 },
 getSummary:async(params?:{year?:number;month?:number}):Promise<CostSummary>=>{
  const response=await api.get(API_ENDPOINTS.cost.summary,{params})
  return response.data
 },
 getExportCsvUrl:(params?:{year?:number;month?:number;project_id?:string}):string=>{
  const query=new URLSearchParams()
  if(params?.year)query.set('year',String(params.year))
  if(params?.month)query.set('month',String(params.month))
  if(params?.project_id)query.set('project_id',params.project_id)
  const qs=query.toString()
  return`${API_BASE_URL}${API_ENDPOINTS.cost.exportCsv}${qs?'?'+qs:''}`
 },
 getExportJsonUrl:(params?:{year?:number;month?:number;project_id?:string}):string=>{
  const query=new URLSearchParams()
  if(params?.year)query.set('year',String(params.year))
  if(params?.month)query.set('month',String(params.month))
  if(params?.project_id)query.set('project_id',params.project_id)
  const qs=query.toString()
  return`${API_BASE_URL}${API_ENDPOINTS.cost.exportJson}${qs?'?'+qs:''}`
 }
}

export{api}
