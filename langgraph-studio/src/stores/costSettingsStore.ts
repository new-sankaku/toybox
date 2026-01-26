import{create}from'zustand'
import{persist}from'zustand/middleware'
import{
 type CostSettings,
 type ServiceCostLimit,
 type PricingConfig,
 DEFAULT_COST_SETTINGS
}from'@/types/costSettings'

interface CostSettingsState{
 settings:CostSettings
 originalSettings:CostSettings
 pricing:PricingConfig|null
 pricingLoaded:boolean
 currentProjectId:string|null
 loading:boolean
 updateGlobalEnabled:(enabled:boolean)=>void
 updateGlobalLimit:(limit:number)=>void
 updateServiceLimit:(serviceType:string,updates:Partial<ServiceCostLimit>)=>void
 setPricing:(pricing:PricingConfig)=>void
 fetchPricing:()=>Promise<void>
 resetToDefaults:()=>void
 loadFromServer:(projectId:string)=>Promise<void>
 saveToServer:(projectId:string)=>Promise<void>
 hasChanges:()=>boolean
 isFieldChanged:(field:string)=>boolean
 isServiceFieldChanged:(serviceType:string,field:string)=>boolean
}

export const useCostSettingsStore=create<CostSettingsState>()(
 persist(
  (set,get)=>({
   settings:{...DEFAULT_COST_SETTINGS},
   originalSettings:{...DEFAULT_COST_SETTINGS},
   pricing:null,
   pricingLoaded:false,
   currentProjectId:null,
   loading:false,

   updateGlobalEnabled:(enabled)=>{
    set(state=>({
     settings:{...state.settings,globalEnabled:enabled}
    }))
   },

   updateGlobalLimit:(limit)=>{
    set(state=>({
     settings:{...state.settings,globalMonthlyLimit:limit}
    }))
   },

   updateServiceLimit:(serviceType,updates)=>{
    set(state=>({
     settings:{
      ...state.settings,
      services:{
       ...state.settings.services,
       [serviceType]:{
        ...state.settings.services[serviceType],
        ...updates
       }
      }
     }
    }))
   },

   setPricing:(pricing)=>{
    set({pricing,pricingLoaded:true})
   },

   fetchPricing:async()=>{
    if(get().pricingLoaded)return
    try{
     const{costApi}=await import('@/services/apiService')
     const pricing=await costApi.getPricing()
     set({pricing,pricingLoaded:true})
    }catch(error){
     console.error('Failed to fetch pricing:',error)
    }
   },

   resetToDefaults:()=>{
    set({settings:{...DEFAULT_COST_SETTINGS}})
   },

   loadFromServer:async(projectId)=>{
    if(get().currentProjectId===projectId)return
    set({loading:true})
    try{
     const{projectSettingsApi}=await import('@/services/apiService')
     const serverSettings=await projectSettingsApi.getCostSettings(projectId)
     if(serverSettings){
      const newSettings={
       globalEnabled:serverSettings.global_enabled??DEFAULT_COST_SETTINGS.globalEnabled,
       globalMonthlyLimit:serverSettings.global_monthly_limit??DEFAULT_COST_SETTINGS.globalMonthlyLimit,
       services:Object.fromEntries(
        Object.entries(serverSettings.services||{}).map(([k,v])=>[k,{
         enabled:v.enabled,
         monthlyLimit:v.monthly_limit
        }])
)||DEFAULT_COST_SETTINGS.services
      }
      set({
       settings:newSettings,
       originalSettings:JSON.parse(JSON.stringify(newSettings)),
       currentProjectId:projectId
      })
     }else{
      set({currentProjectId:projectId,originalSettings:JSON.parse(JSON.stringify(get().settings))})
     }
    }catch(error){
     console.error('Failed to load cost settings from server:',error)
     set({currentProjectId:projectId})
    }finally{
     set({loading:false})
    }
   },

   saveToServer:async(projectId)=>{
    try{
     const{projectSettingsApi}=await import('@/services/apiService')
     const settings=get().settings
     await projectSettingsApi.updateCostSettings(projectId,{
      global_enabled:settings.globalEnabled,
      global_monthly_limit:settings.globalMonthlyLimit,
      alert_threshold:80,
      stop_on_budget_exceeded:false,
      services:Object.fromEntries(
       Object.entries(settings.services).map(([k,v])=>[k,{
        enabled:v.enabled,
        monthly_limit:v.monthlyLimit
       }])
)
     })
     set({originalSettings:JSON.parse(JSON.stringify(settings))})
    }catch(error){
     console.error('Failed to save cost settings to server:',error)
    }
   },

   hasChanges:()=>{
    const{settings,originalSettings}=get()
    return JSON.stringify(settings)!==JSON.stringify(originalSettings)
   },

   isFieldChanged:(field)=>{
    const{settings,originalSettings}=get()
    return(settings as unknown as Record<string,unknown>)[field]!==(originalSettings as unknown as Record<string,unknown>)[field]
   },

   isServiceFieldChanged:(serviceType,field)=>{
    const{settings,originalSettings}=get()
    const current=settings.services[serviceType]
    const original=originalSettings.services[serviceType]
    if(!current||!original)return false
    return(current as unknown as Record<string,unknown>)[field]!==(original as unknown as Record<string,unknown>)[field]
   }
  }),
  {
   name:'cost-settings',
   partialize:(state)=>({settings:state.settings})
  }
)
)
