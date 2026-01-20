import{create}from'zustand'
import{persist}from'zustand/middleware'
import{
 type AutoApprovalRule,
 type ContentCategory,
 type ActionType,
 DEFAULT_AUTO_APPROVAL_RULES,
 CATEGORY_LABELS
}from'@/types/autoApproval'

interface AutoApprovalState{
 rules:AutoApprovalRule[]
 setRuleEnabled:(category:ContentCategory,action:ActionType,enabled:boolean)=>void
 setAllEnabled:(enabled:boolean)=>void
 resetToDefaults:()=>void
 isAutoApproved:(category:ContentCategory,action:ActionType)=>boolean
 getEnabledCount:()=>number
 getRulesByCategory:(category:ContentCategory)=>AutoApprovalRule[]
}

export const useAutoApprovalStore=create<AutoApprovalState>()(
 persist(
  (set,get)=>({
   rules:[...DEFAULT_AUTO_APPROVAL_RULES],

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
   }
  }),
  {
   name:'auto-approval-settings'
  }
 )
)
