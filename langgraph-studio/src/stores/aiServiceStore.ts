import{create}from'zustand'
import{
 aiServiceApi,
 type AIServiceConfig,
 type AIServiceType,
 type ProjectAIServiceConfig,
 type AIServiceMasterData
}from'@/services/apiService'

interface AIServiceState{
 services:Record<AIServiceType,AIServiceConfig>
 master:AIServiceMasterData|null
 projectServices:Record<string,Record<AIServiceType,ProjectAIServiceConfig>>
 loaded:boolean
 masterLoaded:boolean
 loading:boolean
 error:string|null
 fetchServices:()=>Promise<void>
 fetchMaster:()=>Promise<void>
 fetchProjectServices:(projectId:string)=>Promise<void>
 updateProjectService:(projectId:string,serviceType:AIServiceType,config:Partial<ProjectAIServiceConfig>)=>Promise<void>
 getService:(type:AIServiceType)=>AIServiceConfig|undefined
 getProjectService:(projectId:string,type:AIServiceType)=>ProjectAIServiceConfig|undefined
 getLabel:(type:AIServiceType)=>string
 getDescription:(type:AIServiceType)=>string
 getProviderLabel:(providerId:string)=>string
 getModelLabel:(providerId:string,modelId:string)=>string
}

const DEFAULT_SERVICES:Record<AIServiceType,AIServiceConfig>={
 llm:{label:'LLM',description:'-',provider:'',model:''},
 image:{label:'画像生成',description:'-',provider:'',model:''},
 music:{label:'音楽生成',description:'-',provider:'',model:''},
 audio:{label:'音声生成',description:'-',provider:'',model:''}
}

export const useAIServiceStore=create<AIServiceState>((set,get)=>({
 services:{...DEFAULT_SERVICES},
 master:null,
 projectServices:{},
 loaded:false,
 masterLoaded:false,
 loading:false,
 error:null,
 fetchServices:async()=>{
  if(get().loaded||get().loading)return
  set({loading:true,error:null})
  try{
   const services=await aiServiceApi.list()
   set({services,loaded:true,loading:false})
  }catch(error){
   console.error('Failed to fetch AI services:',error)
   set({
    error:error instanceof Error?error.message:'Failed to fetch AI services',
    loading:false
   })
  }
 },
 fetchMaster:async()=>{
  if(get().masterLoaded)return
  try{
   const master=await aiServiceApi.getMaster()
   set({master,masterLoaded:true})
  }catch(error){
   console.error('Failed to fetch AI service master:',error)
  }
 },
 fetchProjectServices:async(projectId:string)=>{
  try{
   const services=await aiServiceApi.getByProject(projectId)
   set(state=>({
    projectServices:{...state.projectServices,[projectId]:services}
   }))
  }catch(error){
   console.error('Failed to fetch project AI services:',error)
  }
 },
 updateProjectService:async(projectId:string,serviceType:AIServiceType,config:Partial<ProjectAIServiceConfig>)=>{
  try{
   const updated=await aiServiceApi.updateServiceByProject(projectId,serviceType,config)
   set(state=>{
    const current=state.projectServices[projectId]||{}
    return{
     projectServices:{
      ...state.projectServices,
      [projectId]:{...current,[serviceType]:updated}
     }
    }
   })
  }catch(error){
   console.error('Failed to update project AI service:',error)
   throw error
  }
 },
 getService:(type:AIServiceType)=>{
  return get().services[type]
 },
 getProjectService:(projectId:string,type:AIServiceType)=>{
  return get().projectServices[projectId]?.[type]
 },
 getLabel:(type:AIServiceType)=>{
  return get().services[type]?.label||type
 },
 getDescription:(type:AIServiceType)=>{
  return get().services[type]?.description||''
 },
 getProviderLabel:(providerId:string)=>{
  const master=get().master
  if(!master)return providerId
  return master.providers[providerId]?.label||providerId
 },
 getModelLabel:(providerId:string,modelId:string)=>{
  const master=get().master
  if(!master)return modelId
  const provider=master.providers[providerId]
  if(!provider)return modelId
  const model=provider.models.find(m=>m.id===modelId)
  return model?.label||modelId
 }
}))
