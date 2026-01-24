import{create}from'zustand'
import{
 type AutoApprovalRule,
 type ContentCategory,
 DEFAULT_AUTO_APPROVAL_RULES
}from'@/types/autoApproval'
import{autoApprovalApi}from'@/services/apiService'

interface AutoApprovalState{
 rules:AutoApprovalRule[]
 projectId:string|null
 loading:boolean
 setRuleEnabled:(category:ContentCategory,enabled:boolean)=>void
 setAllEnabled:(enabled:boolean)=>void
 isAutoApproved:(category:ContentCategory)=>boolean
 getEnabledCount:()=>number
 loadFromServer:(projectId:string)=>Promise<void>
 saveToServer:()=>Promise<void>
}

export const useAutoApprovalStore=create<AutoApprovalState>()((set,get)=>({
 rules:[...DEFAULT_AUTO_APPROVAL_RULES],
 projectId:null,
 loading:false,

 setRuleEnabled:(category,enabled)=>{
  set(state=>({
   rules:state.rules.map(rule=>
    rule.category===category?{...rule,enabled}:rule
)
  }))
 },

 setAllEnabled:(enabled)=>{
  set(state=>({
   rules:state.rules.map(rule=>({...rule,enabled}))
  }))
 },

 isAutoApproved:(category)=>{
  const rule=get().rules.find(r=>r.category===category)
  return rule?.enabled??false
 },

 getEnabledCount:()=>{
  return get().rules.filter(r=>r.enabled).length
 },

 loadFromServer:async(projectId:string)=>{
  set({loading:true,projectId})
  try{
   const response=await autoApprovalApi.getRules(projectId)
   const serverRules=response.rules
   const mergedRules=DEFAULT_AUTO_APPROVAL_RULES.map(defaultRule=>{
    const serverRule=serverRules.find(sr=>sr.category===defaultRule.category)
    return{
     ...defaultRule,
     enabled:serverRule?.enabled??defaultRule.enabled
    }
   })
   set({rules:mergedRules,loading:false})
  }catch(error){
   console.error('Failed to load auto-approval rules:',error)
   set({loading:false})
  }
 },

 saveToServer:async()=>{
  const{projectId,rules}=get()
  if(!projectId)return
  try{
   await autoApprovalApi.updateRules(projectId,rules.map(r=>({
    category:r.category,
    enabled:r.enabled
   })))
  }catch(error){
   console.error('Failed to save auto-approval rules:',error)
  }
 }
}))
