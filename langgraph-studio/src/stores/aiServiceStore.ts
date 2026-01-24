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
 type VoicevoxConfig,
 type MusicGeneratorConfig
}from'@/types/aiProvider'

interface AIServiceState{
 services:Record<AIServiceType,AIServiceConfig>
 master:AIServiceMasterData|null
 projectServices:Record<string,Record<AIServiceType,ProjectAIServiceConfig>>
 loaded:boolean
 masterLoaded:boolean
 loading:boolean
 error:string|null
 providerConfigs:AIProviderConfig[]
 currentProjectId:string|null
 providerLoading:boolean
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
}

const DEFAULT_SERVICES:Record<AIServiceType,AIServiceConfig>={
 llm:{label:'LLM',description:'-',provider:'',model:''},
 image:{label:'画像生成',description:'-',provider:'',model:''},
 music:{label:'音楽生成',description:'-',provider:'',model:''},
 audio:{label:'音声生成',description:'-',provider:'',model:''}
}

export const useAIServiceStore=create<AIServiceState>()(
 persist(
  (set,get)=>({
   services:{...DEFAULT_SERVICES},
   master:null,
   projectServices:{},
   loaded:false,
   masterLoaded:false,
   loading:false,
   error:null,
   providerConfigs:[],
   currentProjectId:null,
   providerLoading:false,

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
   },

   buildDefaultProviderConfigs:()=>{
    const master=get().master
    if(!master)return[]
    const configs:AIProviderConfig[]=[]
    for(const[pid,pdata]of Object.entries(master.providers)){
     if(pdata.serviceTypes.includes('llm')){
      const isAnthropic=pid==='anthropic'
      configs.push({
       id:`${pid}-llm-default`,
       name:pdata.label,
       type:isAnthropic?'claude':'openai',
       serviceType:'llm',
       providerId:pid,
       enabled:false,
       apiKey:'',
       model:pdata.defaultModel,
       endpoint:isAnthropic?'https://api.anthropic.com':'',
       maxTokens:4096,
       temperature:0.7
      }as LLMProviderConfig)
     }
     if(pdata.serviceTypes.includes('image')){
      configs.push({
       id:`${pid}-image-default`,
       name:pdata.label,
       type:'comfyui',
       serviceType:'image',
       providerId:pid,
       enabled:false,
       endpoint:'http://localhost:8188',
       workflowFile:'default.json',
       outputDir:'./outputs',
       steps:20,
       cfgScale:7.0,
       sampler:(pdata as{samplers?:string[]}).samplers?.[0]||'euler_ancestral',
       scheduler:(pdata as{schedulers?:string[]}).schedulers?.[0]||'normal'
      }as ComfyUIConfig)
     }
     if(pdata.serviceTypes.includes('audio')){
      configs.push({
       id:`${pid}-audio-default`,
       name:pdata.label,
       type:'voicevox',
       serviceType:'audio',
       providerId:pid,
       enabled:false,
       endpoint:'http://localhost:50021',
       speakerId:1,
       speed:1.0
      }as VoicevoxConfig)
     }
     if(pdata.serviceTypes.includes('music')){
      configs.push({
       id:`${pid}-music-default`,
       name:pdata.label,
       type:'suno',
       serviceType:'music',
       providerId:pid,
       enabled:false,
       apiKey:'',
       endpoint:''
      }as MusicGeneratorConfig)
     }
    }
    return configs
   },

   loadProviderConfigs:async(projectId:string)=>{
    const state=get()
    if(state.currentProjectId===projectId&&state.providerConfigs.length>0)return
    set({providerLoading:true})
    try{
     const serverConfigs=await projectSettingsApi.getAIProviders(projectId)
     if(serverConfigs&&Array.isArray(serverConfigs)&&serverConfigs.length>0){
      set({providerConfigs:serverConfigs as AIProviderConfig[],currentProjectId:projectId})
     }else{
      const defaults=get().buildDefaultProviderConfigs()
      set({providerConfigs:defaults,currentProjectId:projectId})
     }
    }catch(error){
     console.error('Failed to load provider configs:',error)
     const defaults=get().buildDefaultProviderConfigs()
     set({providerConfigs:defaults,currentProjectId:projectId})
    }finally{
     set({providerLoading:false})
    }
   },

   saveProviderConfigs:async(projectId:string)=>{
    try{
     await projectSettingsApi.updateAIProviders(projectId,get().providerConfigs)
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
   }
  }),
  {
   name:'ai-service-settings',
   partialize:(state)=>({providerConfigs:state.providerConfigs})
  }
)
)
