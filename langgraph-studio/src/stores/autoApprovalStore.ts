import{create}from'zustand'
import{persist}from'zustand/middleware'
import{
 type AutoApprovalRule,
 type ContentCategory,
 type ActionType,
 DEFAULT_AUTO_APPROVAL_RULES
}from'@/types/autoApproval'
import{autoApprovalApi}from'@/services/apiService'

interface AutoApprovalState{
 rules:AutoApprovalRule[]
 currentProjectId:string|null
 isSyncing:boolean
 lastSyncError:string|null
 setRuleEnabled:(category:ContentCategory,action:ActionType,enabled:boolean)=>void
 setAllEnabled:(enabled:boolean)=>void
 resetToDefaults:()=>void
 isAutoApproved:(category:ContentCategory,action:ActionType)=>boolean
 getEnabledCount:()=>number
 getRulesByCategory:(category:ContentCategory)=>AutoApprovalRule[]
 syncFromServer:(projectId:string)=>Promise<void>
 saveToServer:(projectId:string)=>Promise<void>
 setProjectId:(projectId:string|null)=>void
}

export const useAutoApprovalStore=create<AutoApprovalState>()(
 persist(
  (set,get)=>({
   rules:[...DEFAULT_AUTO_APPROVAL_RULES],
   currentProjectId:null,
   isSyncing:false,
   lastSyncError:null,

   setRuleEnabled:(category,action,enabled)=>{
    set(state=>({
     rules:state.rules.map(rule=>
      rule.category===category&&rule.action===action
       ?{...rule,enabled}
       :rule
)
    }))
   },

   setAllEnabled:(enabled)=>{
    set(state=>({
     rules:state.rules.map(rule=>({...rule,enabled}))
    }))
   },

   resetToDefaults:()=>{
    set({rules:[...DEFAULT_AUTO_APPROVAL_RULES]})
   },

   isAutoApproved:(category,action)=>{
    const rule=get().rules.find(r=>r.category===category&&r.action===action)
    return rule?.enabled??false
   },

   getEnabledCount:()=>{
    return get().rules.filter(r=>r.enabled).length
   },

   getRulesByCategory:(category)=>{
    return get().rules.filter(r=>r.category===category)
   },

   syncFromServer:async(projectId:string)=>{
    set({isSyncing:true,lastSyncError:null})
    try{
     const response=await autoApprovalApi.getRules(projectId)
     const serverRules=response.rules
     const mergedRules=get().rules.map(localRule=>{
      const serverRule=serverRules.find(
       sr=>sr.category===localRule.category&&sr.action===localRule.action
)
      if(serverRule){
       return{...localRule,enabled:serverRule.enabled}
      }
      return localRule
     })
     set({rules:mergedRules,currentProjectId:projectId,isSyncing:false})
    }catch(error){
     set({isSyncing:false,lastSyncError:'サーバーからの同期に失敗しました'})
     console.error('Failed to sync auto-approval rules:',error)
    }
   },

   saveToServer:async(projectId:string)=>{
    set({isSyncing:true,lastSyncError:null})
    try{
     const rules=get().rules.map(r=>({
      category:r.category,
      action:r.action,
      enabled:r.enabled
     }))
     await autoApprovalApi.updateRules(projectId,rules)
     set({isSyncing:false,currentProjectId:projectId})
    }catch(error){
     set({isSyncing:false,lastSyncError:'サーバーへの保存に失敗しました'})
     console.error('Failed to save auto-approval rules:',error)
    }
   },

   setProjectId:(projectId:string|null)=>{
    set({currentProjectId:projectId})
   }
  }),
  {
   name:'auto-approval-settings'
  }
)
)
