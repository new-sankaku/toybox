import axios,{type AxiosInstance}from'axios'
import{useAuthStore}from'@/stores/authStore'

const api:AxiosInstance=axios.create({baseURL:'/admin-api'})

api.interceptors.request.use(config=>{
 const token=useAuthStore.getState().token
 if(token){
  config.headers.Authorization=`Bearer ${token}`
 }
 return config
})

api.interceptors.response.use(
 res=>res,
 error=>{
  if(error.response?.status===401){
   useAuthStore.getState().logout()
  }
  return Promise.reject(error)
 }
)

export interface ApiKeyInfo{
 providerId:string
 hint:string
 validated:boolean
 latencyMs:number|null
 lastValidatedAt:string|null
}

export interface ProviderInfo{
 id:string
 name:string
 type:string
}

export interface BackupInfo{
 name:string
 size:number
 createdAt:string
}

export interface ArchiveInfo{
 name:string
 size:number
 createdAt:string
}

export const authApi={
 verify:async(token:string)=>{
  const{data}=await api.post('/auth/verify',{token})
  return data
 }
}

export const apiKeyApi={
 list:async():Promise<ApiKeyInfo[]>=>{
  const{data}=await api.get('/api-keys')
  return data
 },
 save:async(providerId:string,apiKey:string)=>{
  const{data}=await api.put(`/api-keys/${providerId}`,{apiKey})
  return data
 },
 delete:async(providerId:string)=>{
  const{data}=await api.delete(`/api-keys/${providerId}`)
  return data
 },
 validate:async(providerId:string)=>{
  const{data}=await api.post(`/api-keys/${providerId}/validate`)
  return data as{success:boolean;message:string;latency:number}
 }
}

export const providerApi={
 list:async():Promise<ProviderInfo[]>=>{
  const{data}=await api.get('/providers')
  return data
 },
 health:async()=>{
  const{data}=await api.get('/providers/health')
  return data
 }
}

export const backupApi={
 list:async()=>{
  const{data}=await api.get('/backups')
  return data as{backups:BackupInfo[];info:Record<string,unknown>}
 },
 create:async(tag?:string)=>{
  const{data}=await api.post('/backups',tag?{tag}:{})
  return data
 },
 restore:async(name:string)=>{
  const{data}=await api.post(`/backups/${name}/restore`)
  return data
 },
 delete:async(name:string)=>{
  const{data}=await api.delete(`/backups/${name}`)
  return data
 }
}

export const archiveApi={
 stats:async(projectId?:string)=>{
  const params=projectId?{projectId}:{}
  const{data}=await api.get('/archive/stats',{params})
  return data
 },
 estimate:async(projectId?:string)=>{
  const params=projectId?{projectId}:{}
  const{data}=await api.get('/archive/estimate',{params})
  return data
 },
 cleanup:async(projectId?:string)=>{
  const{data}=await api.post('/archive/cleanup',projectId?{projectId}:{})
  return data as{success:boolean;deleted:number}
 },
 setRetention:async(days:number)=>{
  const{data}=await api.put('/archive/retention',{retentionDays:days})
  return data
 },
 export:async(projectId:string,agentId?:string)=>{
  const{data}=await api.post('/archive/export',{projectId,agentId})
  return data
 },
 exportAndCleanup:async(projectId:string,agentId?:string)=>{
  const{data}=await api.post('/archive/export-and-cleanup',{projectId,agentId})
  return data
 },
 list:async()=>{
  const{data}=await api.get('/archives')
  return data as{archives:ArchiveInfo[];info:Record<string,unknown>}
 },
 delete:async(name:string)=>{
  const{data}=await api.delete(`/archives/${name}`)
  return data
 },
 getDownloadUrl:(name:string)=>`/admin-api/archives/${name}/download`
}

export const systemApi={
 status:async()=>{
  const{data}=await api.get('/system/status')
  return data
 }
}
