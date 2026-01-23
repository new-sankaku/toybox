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
 addProvider:(config:AIProviderConfig)=>void
 updateProvider:(id:string,updates:Partial<AIProviderConfig>)=>void
 removeProvider:(id:string)=>void
 toggleProvider:(id:string)=>void
 getProvider:(id:string)=>AIProviderConfig|undefined
 getProvidersByType:(type:AIProviderType)=>AIProviderConfig[]
 getEnabledProviders:()=>AIProviderConfig[]
 exportSettings:()=>string
 importSettings:(json:string)=>boolean
 resetToDefaults:()=>void
}

const generateId=()=>`provider-${Date.now()}-${Math.random().toString(36).slice(2,9)}`

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

   addProvider:(config)=>{
    set(state=>({
     providers:[...state.providers,{...config,id:config.id||generateId()}]
    }))
   },

   updateProvider:(id,updates)=>{
    set(state=>({
     providers:state.providers.map(p=>
      p.id===id?{...p,...updates}as AIProviderConfig:p
)
    }))
   },

   removeProvider:(id)=>{
    set(state=>({
     providers:state.providers.filter(p=>p.id!==id)
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

   exportSettings:()=>{
    const providers=get().providers.map(p=>{
     if('apiKey'in p){
      return{...p,apiKey:''}
     }
     return p
    })
    return JSON.stringify({providers,version:1},null,2)
   },

   importSettings:(json)=>{
    try{
     const data=JSON.parse(json)
     if(data.providers&&Array.isArray(data.providers)){
      set({providers:data.providers})
      return true
     }
     return false
    }catch{
     return false
    }
   },

   resetToDefaults:()=>{
    set({providers:[...DEFAULT_PROVIDERS]})
   }
  }),
  {
   name:'ai-provider-settings'
  }
)
)
