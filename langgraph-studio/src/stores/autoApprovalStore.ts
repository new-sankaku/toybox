import{create}from'zustand'
import{
 type AutoApprovalRule,
 type ContentCategory,
 DEFAULT_AUTO_APPROVAL_RULES
}from'@/types/autoApproval'
import{autoApprovalApi}from'@/services/apiService'

interface AutoApprovalState{
 rules:AutoApprovalRule[]
 originalRules:AutoApprovalRule[]
 projectId:string|null
 loading:boolean
 setRuleEnabled:(category:ContentCategory,enabled:boolean)=>void
 setAllEnabled:(enabled:boolean)=>void
 isAutoApproved:(category:ContentCategory)=>boolean
 getEnabledCount:()=>number
 loadFromServer:(projectId:string)=>Promise<void>
 saveToServer:()=>Promise<void>
 hasChanges:()=>boolean
 isRuleChanged:(category:ContentCategory)=>boolean
}

export const useAutoApprovalStore=create<AutoApprovalState>()((set,get)=>({
 rules:[...DEFAULT_AUTO_APPROVAL_RULES],
 originalRules:[...DEFAULT_AUTO_APPROVAL_RULES],
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
   set({rules:mergedRules,originalRules:JSON.parse(JSON.stringify(mergedRules)),loading:false})
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
   set({originalRules:JSON.parse(JSON.stringify(rules))})
  }catch(error){
   console.error('Failed to save auto-approval rules:',error)
  }
 },

 hasChanges:()=>{
  const{rules,originalRules}=get()
  return JSON.stringify(rules)!==JSON.stringify(originalRules)
 },

 isRuleChanged:(category)=>{
  const{rules,originalRules}=get()
  const current=rules.find(r=>r.category===category)
  const original=originalRules.find(r=>r.category===category)
  return current?.enabled!==original?.enabled
 }
}))
