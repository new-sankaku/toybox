import{create}from'zustand'
import{persist}from'zustand/middleware'
import{
 aiServiceApi,
 projectSettingsApi,
 type AIServiceConfig,
 type AIServiceType,
 type ProjectAIServiceConfig,
 type AIServiceMasterData
}from'@/services/apiService'
import{
 type AIProviderConfig,
 type LLMProviderConfig,
 type ComfyUIConfig,
 type AudioCraftConfig
}from'@/types/aiProvider'

interface AIServiceState{
 services:Partial<Record<AIServiceType,AIServiceConfig>>
 master:AIServiceMasterData|null
 projectServices:Record<string,Partial<Record<AIServiceType,ProjectAIServiceConfig>>>
 loaded:boolean
 masterLoaded:boolean
 loading:boolean
 error:string|null
 providerConfigs:AIProviderConfig[]
 originalProviderConfigs:AIProviderConfig[]
 currentProjectId:string|null
 providerLoading:boolean
 providerError:string|null
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
 loadProviderConfigs:(projectId:string)=>Promise<void>
 saveProviderConfigs:(projectId:string)=>Promise<void>
 updateProviderConfig:(id:string,updates:Partial<AIProviderConfig>)=>void
 toggleProviderConfig:(id:string)=>void
 getProviderConfig:(id:string)=>AIProviderConfig|undefined
 getProviderConfigsByType:(type:AIProviderConfig['type'])=>AIProviderConfig[]
 getEnabledProviderConfigs:()=>AIProviderConfig[]
 resetProviderConfigs:()=>void
 buildDefaultProviderConfigs:()=>AIProviderConfig[]
 hasProviderChanges:()=>boolean
 isProviderFieldChanged:(id:string,field:string)=>boolean
}

export const useAIServiceStore=create<AIServiceState>()(
 persist(
  (set,get)=>({
   services:{},
   master:null,
   projectServices:{},
   loaded:false,
   masterLoaded:false,
   loading:false,
   error:null,
   providerConfigs:[],
   originalProviderConfigs:[],
   currentProjectId:null,
   providerLoading:false,
   providerError:null,

   fetchServices:async()=>{
    if(get().loaded||get().loading)return
    set({loading:true,error:null})
    try{
     const services=await aiServiceApi.list()
     set({services,loaded:true,loading:false})
    }catch(error){
     console.error('Failed to fetch AI services:',error)
     set({
      error:error instanceof Error?error.message:'AIサービスの取得に失敗しました',
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
   },

   buildDefaultProviderConfigs:()=>{
    const master=get().master
    if(!master)return[]
    const reverseMapping=master.reverseProviderTypeMapping||{}
    const configs:AIProviderConfig[]=[]
    for(const[pid,pdata]of Object.entries(master.providers)){
     if(pdata.serviceTypes.includes('llm')){
      const providerType=reverseMapping[pid]
      if(!providerType)continue
      configs.push({
       id:`${pid}-llm-default`,
       name:pdata.label,
       type:providerType as LLMProviderConfig['type'],
       serviceType:'llm',
       providerId:pid,
       enabled:false,
       apiKey:'',
       endpoint:''
      }as LLMProviderConfig)
     }
     if(pdata.serviceTypes.includes('image')){
      const providerType=reverseMapping[pid]
      if(!providerType)continue
      configs.push({
       id:`${pid}-image-default`,
       name:pdata.label,
       type:providerType as ComfyUIConfig['type'],
       serviceType:'image',
       providerId:pid,
       enabled:false,
       endpoint:''
      }as ComfyUIConfig)
     }
     if(pdata.serviceTypes.includes('audio')){
      const providerType=reverseMapping[pid]
      if(!providerType)continue
      configs.push({
       id:`${pid}-audio-default`,
       name:pdata.label,
       type:providerType as ComfyUIConfig['type'],
       serviceType:'audio',
       providerId:pid,
       enabled:false,
       endpoint:''
      }as ComfyUIConfig)
     }
     if(pdata.serviceTypes.includes('music')){
      const providerType=reverseMapping[pid]
      if(!providerType)continue
      configs.push({
       id:`${pid}-music-default`,
       name:pdata.label,
       type:providerType as AudioCraftConfig['type'],
       serviceType:'music',
       providerId:pid,
       enabled:false,
       apiKey:'',
       endpoint:''
      }as AudioCraftConfig)
     }
    }
    return configs
   },

   loadProviderConfigs:async(projectId:string)=>{
    const state=get()
    if(state.currentProjectId===projectId&&state.providerConfigs.length>0)return
    set({providerLoading:true,providerError:null})
    try{
     const serverConfigs=await projectSettingsApi.getAIProviders(projectId)
     if(serverConfigs&&Array.isArray(serverConfigs)&&serverConfigs.length>0){
      const configs=serverConfigs as AIProviderConfig[]
      set({providerConfigs:configs,originalProviderConfigs:JSON.parse(JSON.stringify(configs)),currentProjectId:projectId})
     }else{
      const defaults=get().buildDefaultProviderConfigs()
      set({providerConfigs:defaults,originalProviderConfigs:JSON.parse(JSON.stringify(defaults)),currentProjectId:projectId})
     }
    }catch(error){
     console.error('Failed to load provider configs:',error)
     set({
      providerError:error instanceof Error?error.message:'プロバイダー設定の取得に失敗しました',
      currentProjectId:projectId
     })
    }finally{
     set({providerLoading:false})
    }
   },

   saveProviderConfigs:async(projectId:string)=>{
    try{
     await projectSettingsApi.updateAIProviders(projectId,get().providerConfigs)
     const configs=get().providerConfigs
     set({originalProviderConfigs:JSON.parse(JSON.stringify(configs))})
    }catch(error){
     console.error('Failed to save provider configs:',error)
    }
   },

   updateProviderConfig:(id,updates)=>{
    set(state=>({
     providerConfigs:state.providerConfigs.map(p=>
      p.id===id?{...p,...updates}as AIProviderConfig:p
)
    }))
   },

   toggleProviderConfig:(id)=>{
    set(state=>({
     providerConfigs:state.providerConfigs.map(p=>
      p.id===id?{...p,enabled:!p.enabled}:p
)
    }))
   },

   getProviderConfig:(id)=>{
    return get().providerConfigs.find(p=>p.id===id)
   },

   getProviderConfigsByType:(type)=>{
    return get().providerConfigs.filter(p=>p.type===type)
   },

   getEnabledProviderConfigs:()=>{
    return get().providerConfigs.filter(p=>p.enabled)
   },

   resetProviderConfigs:()=>{
    const defaults=get().buildDefaultProviderConfigs()
    set({providerConfigs:defaults})
   },

   hasProviderChanges:()=>{
    const{providerConfigs,originalProviderConfigs}=get()
    return JSON.stringify(providerConfigs)!==JSON.stringify(originalProviderConfigs)
   },

   isProviderFieldChanged:(id,field)=>{
    const{providerConfigs,originalProviderConfigs}=get()
    const current=providerConfigs.find(p=>p.id===id)
    const original=originalProviderConfigs.find(p=>p.id===id)
    if(!current||!original)return false
    return(current as unknown as Record<string,unknown>)[field]!==(original as unknown as Record<string,unknown>)[field]
   }
  }),
  {
   name:'ai-service-settings',
   partialize:(state)=>({providerConfigs:state.providerConfigs})
  }
)
)
