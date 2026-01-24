import{create}from'zustand'
import{persist}from'zustand/middleware'
import{
 type AIProviderConfig,
 type AIProviderType,
 DEFAULT_LLM_CONFIG,
 DEFAULT_COMFYUI_CONFIG,
 DEFAULT_VOICEVOX_CONFIG,
 DEFAULT_SUNO_CONFIG
}from'@/types/aiProvider'

interface AIProviderState{
 providers:AIProviderConfig[]
 currentProjectId:string|null
 loading:boolean
 updateProvider:(id:string,updates:Partial<AIProviderConfig>)=>void
 toggleProvider:(id:string)=>void
 getProvider:(id:string)=>AIProviderConfig|undefined
 getProvidersByType:(type:AIProviderType)=>AIProviderConfig[]
 getEnabledProviders:()=>AIProviderConfig[]
 resetToDefaults:()=>void
 loadFromServer:(projectId:string)=>Promise<void>
 saveToServer:(projectId:string)=>Promise<void>
}

const DEFAULT_PROVIDERS:AIProviderConfig[]=[
 {
  id:'claude-default',
  name:'Claude',
  ...DEFAULT_LLM_CONFIG,
  type:'claude'
 },
 {
  id:'openai-default',
  name:'OpenAI',
  ...DEFAULT_LLM_CONFIG,
  type:'openai',
  model:'gpt-4o',
  endpoint:'https://api.openai.com/v1'
 },
 {
  id:'comfyui-default',
  name:'ComfyUI',
  ...DEFAULT_COMFYUI_CONFIG
 },
 {
  id:'voicevox-default',
  name:'VOICEVOX',
  ...DEFAULT_VOICEVOX_CONFIG
 },
 {
  id:'suno-default',
  name:'Suno AI',
  ...DEFAULT_SUNO_CONFIG
 }
]

export const useAIProviderStore=create<AIProviderState>()(
 persist(
  (set,get)=>({
   providers:[...DEFAULT_PROVIDERS],
   currentProjectId:null,
   loading:false,

   updateProvider:(id,updates)=>{
    set(state=>({
     providers:state.providers.map(p=>
      p.id===id?{...p,...updates}as AIProviderConfig:p
)
    }))
   },

   toggleProvider:(id)=>{
    set(state=>({
     providers:state.providers.map(p=>
      p.id===id?{...p,enabled:!p.enabled}:p
)
    }))
   },

   getProvider:(id)=>{
    return get().providers.find(p=>p.id===id)
   },

   getProvidersByType:(type)=>{
    return get().providers.filter(p=>p.type===type)
   },

   getEnabledProviders:()=>{
    return get().providers.filter(p=>p.enabled)
   },

   resetToDefaults:()=>{
    set({providers:[...DEFAULT_PROVIDERS]})
   },

   loadFromServer:async(projectId)=>{
    if(get().currentProjectId===projectId&&get().providers.length>0)return
    set({loading:true})
    try{
     const{projectSettingsApi}=await import('@/services/apiService')
     const serverProviders=await projectSettingsApi.getAIProviders(projectId)
     if(serverProviders&&Array.isArray(serverProviders)&&serverProviders.length>0){
      set({providers:serverProviders as AIProviderConfig[],currentProjectId:projectId})
     }else{
      set({currentProjectId:projectId})
     }
    }catch(error){
     console.error('Failed to load AI providers from server:',error)
    }finally{
     set({loading:false})
    }
   },

   saveToServer:async(projectId)=>{
    try{
     const{projectSettingsApi}=await import('@/services/apiService')
     await projectSettingsApi.updateAIProviders(projectId,get().providers)
    }catch(error){
     console.error('Failed to save AI providers to server:',error)
    }
   }
  }),
  {
   name:'ai-provider-settings',
   partialize:(state)=>({providers:state.providers})
  }
)
)
