import{create}from'zustand'
import{
 type AutoApprovalRule,
 type ContentCategory
}from'@/types/autoApproval'
import{autoApprovalApi}from'@/services/apiService'

const CATEGORY_LABELS:Record<string,string>={
 code:'コード',
 image:'画像',
 audio:'音声',
 music:'音楽',
 document:'ドキュメント',
 video:'動画'
}

interface AutoApprovalState{
 rules:AutoApprovalRule[]
 originalRules:AutoApprovalRule[]
 projectId:string|null
 loading:boolean
 error:string|null
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
 rules:[],
 originalRules:[],
 projectId:null,
 loading:false,
 error:null,

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
  set({loading:true,projectId,error:null})
  try{
   const response=await autoApprovalApi.getRules(projectId)
   const serverRules:AutoApprovalRule[]=response.rules.map((r)=>({
    category:r.category as ContentCategory,
    enabled:r.enabled,
    label:CATEGORY_LABELS[r.category]||r.category
   }))
   set({rules:serverRules,originalRules:JSON.parse(JSON.stringify(serverRules)),loading:false})
  }catch(error){
   console.error('Failed to load auto-approval rules:',error)
   set({
    error:error instanceof Error?error.message:'自動承認ルールの取得に失敗しました',
    loading:false
   })
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
