import{create}from'zustand'
import{persist}from'zustand/middleware'
import{
 type CostSettings,
 type ServiceCostLimit,
 type PricingConfig
}from'@/types/costSettings'

interface CostSettingsState{
 settings:CostSettings|null
 originalSettings:CostSettings|null
 pricing:PricingConfig|null
 pricingLoaded:boolean
 currentProjectId:string|null
 loading:boolean
 error:string|null
 updateGlobalEnabled:(enabled:boolean)=>void
 updateGlobalLimit:(limit:number)=>void
 updateServiceLimit:(serviceType:string,updates:Partial<ServiceCostLimit>)=>void
 setPricing:(pricing:PricingConfig)=>void
 fetchPricing:()=>Promise<void>
 resetToDefaults:()=>Promise<void>
 loadFromServer:(projectId:string)=>Promise<void>
 saveToServer:(projectId:string)=>Promise<void>
 hasChanges:()=>boolean
 isFieldChanged:(field:string)=>boolean
 isServiceFieldChanged:(serviceType:string,field:string)=>boolean
}

export const useCostSettingsStore=create<CostSettingsState>()(
 persist(
  (set,get)=>({
   settings:null,
   originalSettings:null,
   pricing:null,
   pricingLoaded:false,
   currentProjectId:null,
   loading:false,
   error:null,

   updateGlobalEnabled:(enabled)=>{
    set(state=>{
     if(!state.settings)return state
     return{settings:{...state.settings,globalEnabled:enabled}}
    })
   },

   updateGlobalLimit:(limit)=>{
    set(state=>{
     if(!state.settings)return state
     return{settings:{...state.settings,globalMonthlyLimit:limit}}
    })
   },

   updateServiceLimit:(serviceType,updates)=>{
    set(state=>{
     if(!state.settings)return state
     return{
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
     }
    })
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

   resetToDefaults:async()=>{
    set({loading:true,error:null})
    try{
     const{configApi}=await import('@/services/apiService')
     const defaults=await configApi.getCostSettingsDefaults()
     if(defaults){
      const newSettings:CostSettings={
       globalEnabled:defaults.global_enabled,
       globalMonthlyLimit:defaults.global_monthly_limit,
       services:Object.fromEntries(
        Object.entries(defaults.services||{}).map(([k,v])=>[k,{
         enabled:v.enabled,
         monthlyLimit:v.monthly_limit
        }])
)
      }
      set({
       settings:newSettings,
       originalSettings:JSON.parse(JSON.stringify(newSettings)),
       currentProjectId:null
      })
     }
    }catch(error){
     console.error('Failed to fetch cost settings defaults:',error)
     set({error:error instanceof Error?error.message:'デフォルト値の取得に失敗しました'})
    }finally{
     set({loading:false})
    }
   },

   loadFromServer:async(projectId)=>{
    if(get().currentProjectId===projectId)return
    set({loading:true,error:null})
    try{
     const{projectSettingsApi}=await import('@/services/apiService')
     const serverSettings=await projectSettingsApi.getCostSettings(projectId)
     if(serverSettings){
      if(serverSettings.global_enabled==null||serverSettings.global_monthly_limit==null){
       set({
        error:'コスト設定のデータが不完全です',
        currentProjectId:projectId,
        loading:false
       })
       return
      }
      const newSettings:CostSettings={
       globalEnabled:serverSettings.global_enabled,
       globalMonthlyLimit:serverSettings.global_monthly_limit,
       services:Object.fromEntries(
        Object.entries(serverSettings.services||{}).map(([k,v])=>[k,{
         enabled:v.enabled,
         monthlyLimit:v.monthly_limit
        }])
)
      }
      set({
       settings:newSettings,
       originalSettings:JSON.parse(JSON.stringify(newSettings)),
       currentProjectId:projectId
      })
     }else{
      set({
       error:'コスト設定の取得結果が空です',
       currentProjectId:projectId
      })
     }
    }catch(error){
     console.error('Failed to load cost settings from server:',error)
     set({
      error:error instanceof Error?error.message:'コスト設定の取得に失敗しました',
      currentProjectId:projectId
     })
    }finally{
     set({loading:false})
    }
   },

   saveToServer:async(projectId)=>{
    try{
     const{projectSettingsApi}=await import('@/services/apiService')
     const settings=get().settings
     if(!settings)return
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
    if(!settings||!originalSettings)return false
    return(settings as unknown as Record<string,unknown>)[field]!==(originalSettings as unknown as Record<string,unknown>)[field]
   },

   isServiceFieldChanged:(serviceType,field)=>{
    const{settings,originalSettings}=get()
    if(!settings||!originalSettings)return false
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
