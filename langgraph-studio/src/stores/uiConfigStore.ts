import{create}from'zustand'
import{uiSettingsApi,type UIPhase,type UISettingsAgent}from'@/services/apiService'

interface UIConfigState{
 uiPhases:UIPhase[]
 agentServiceMap:Record<string,string>
 serviceLabels:Record<string,string>
 statusLabels:Record<string,string>
 agentStatusLabels:Record<string,string>
 approvalStatusLabels:Record<string,string>
 assetTypeLabels:Record<string,string>
 resolutionLabels:Record<string,string>
 roleLabels:Record<string,string>
 checkpointTypeLabels:Record<string,string>
 agentRoles:Record<string,string>
 agents:Record<string,UISettingsAgent>
 loaded:boolean
 loading:boolean
 error:string|null
 fetchSettings:()=>Promise<void>
 getServiceLabel:(serviceType:string)=>string
 getStatusLabel:(status:string)=>string
 getAgentStatusLabel:(status:string)=>string
 getApprovalStatusLabel:(status:string)=>string
 getAssetTypeLabel:(assetType:string)=>string
 getResolutionLabel:(resolution:string)=>string
 getRoleLabel:(role:string)=>string
 getCheckpointTypeLabel:(checkpointType:string)=>string
 getAgentRole:(agentType:string)=>string
 getAgentServiceType:(agentType:string)=>string
}

export const useUIConfigStore=create<UIConfigState>((set,get)=>({
 uiPhases:[],
 agentServiceMap:{},
 serviceLabels:{},
 statusLabels:{},
 agentStatusLabels:{},
 approvalStatusLabels:{},
 assetTypeLabels:{},
 resolutionLabels:{},
 roleLabels:{},
 checkpointTypeLabels:{},
 agentRoles:{},
 agents:{},
 loaded:false,
 loading:false,
 error:null,
 fetchSettings:async()=>{
  if(get().loaded||get().loading)return
  set({loading:true,error:null})
  try{
   const response=await uiSettingsApi.get()
   set({
    uiPhases:response.uiPhases||[],
    agentServiceMap:response.agentServiceMap||{},
    serviceLabels:response.serviceLabels||{},
    statusLabels:response.statusLabels||{},
    agentStatusLabels:response.agentStatusLabels||{},
    approvalStatusLabels:response.approvalStatusLabels||{},
    assetTypeLabels:response.assetTypeLabels||{},
    resolutionLabels:response.resolutionLabels||{},
    roleLabels:response.roleLabels||{},
    checkpointTypeLabels:response.checkpointTypeLabels||{},
    agentRoles:response.agentRoles||{},
    agents:response.agents||{},
    loaded:true,
    loading:false
   })
  }catch(error){
   console.error('Failed to fetch UI settings:',error)
   set({
    error:error instanceof Error?error.message:'UI設定の取得に失敗しました',
    loading:false,
   })
  }
 },
 getServiceLabel:(serviceType:string)=>{
  return get().serviceLabels[serviceType]||serviceType
 },
 getStatusLabel:(status:string)=>{
  return get().statusLabels[status]||status
 },
 getAgentStatusLabel:(status:string)=>{
  return get().agentStatusLabels[status]||status
 },
 getApprovalStatusLabel:(status:string)=>{
  return get().approvalStatusLabels[status]||status
 },
 getAssetTypeLabel:(assetType:string)=>{
  return get().assetTypeLabels[assetType]||assetType
 },
 getResolutionLabel:(resolution:string)=>{
  return get().resolutionLabels[resolution]||resolution
 },
 getRoleLabel:(role:string)=>{
  return get().roleLabels[role]||role
 },
 getCheckpointTypeLabel:(checkpointType:string)=>{
  return get().checkpointTypeLabels[checkpointType]||checkpointType
 },
 getAgentRole:(agentType:string)=>{
  return get().agentRoles[agentType]||agentType
 },
 getAgentServiceType:(agentType:string)=>{
  return get().agentServiceMap[agentType]||agentType
 },
}))
