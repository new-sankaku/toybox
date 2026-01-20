import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{ToggleLeft,ToggleRight,RefreshCw,CheckCircle2,XCircle}from'lucide-react'
import{useAutoApprovalStore}from'@/stores/autoApprovalStore'
import{type ContentCategory,CATEGORY_LABELS}from'@/types/autoApproval'

const CATEGORY_ORDER:ContentCategory[]=['code','image','audio','music','document','system']

export function AutoApprovalSettings():JSX.Element{
 const{rules,setRuleEnabled,setAllEnabled,resetToDefaults,getEnabledCount,getRulesByCategory}=useAutoApprovalStore()

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <DiamondMarker>自動承認設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     <div className="flex items-center justify-between">
      <div className="text-nier-small">
       <span className="text-nier-accent-green">{getEnabledCount()}</span>
       <span className="text-nier-text-light">/{rules.length} カテゴリで自動承認ON</span>
      </div>
      <div className="flex gap-2">
       <Button variant="ghost" size="sm" onClick={()=>setAllEnabled(true)}>
        <CheckCircle2 size={14}/>
        <span className="ml-1">全てON</span>
       </Button>
       <Button variant="ghost" size="sm" onClick={()=>setAllEnabled(false)}>
        <XCircle size={14}/>
        <span className="ml-1">全てOFF</span>
       </Button>
       <Button variant="ghost" size="sm" onClick={resetToDefaults}>
        <RefreshCw size={14}/>
        <span className="ml-1">デフォルトに戻す</span>
       </Button>
      </div>
     </div>
     <div className="p-3 bg-nier-bg-panel border border-nier-border-light text-nier-caption text-nier-text-light">
      ONにすると、該当カテゴリのCHECKPOINTは人間の確認なしで自動的に承認されます。削除操作はデフォルトでOFFです。
     </div>
    </CardContent>
   </Card>

   {CATEGORY_ORDER.map(category=>{
    const categoryRules=getRulesByCategory(category)
    if(categoryRules.length===0)return null

    return(
     <Card key={category}>
      <CardHeader>
       <DiamondMarker variant="secondary">{CATEGORY_LABELS[category]}</DiamondMarker>
      </CardHeader>
      <CardContent className="p-0">
       <div className="divide-y divide-nier-border-light">
        {categoryRules.map(rule=>(
         <div
          key={`${rule.category}-${rule.action}`}
          className={cn(
           'flex items-center justify-between px-4 py-2 transition-colors',
           'hover:bg-nier-bg-panel'
          )}
         >
          <span className="text-nier-small text-nier-text-main">{rule.label}</span>
          <button
           onClick={()=>setRuleEnabled(rule.category,rule.action,!rule.enabled)}
           className={cn(
            'p-1 rounded transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-nier-accent-blue'
           )}
          >
           {rule.enabled?(
            <div className="flex items-center gap-1 text-nier-accent-green">
             <ToggleRight size={20}/>
             <span className="text-nier-caption">ON</span>
            </div>
           ):(
            <div className="flex items-center gap-1 text-nier-text-light">
             <ToggleLeft size={20}/>
             <span className="text-nier-caption">OFF</span>
            </div>
           )}
          </button>
         </div>
        ))}
       </div>
      </CardContent>
     </Card>
    )
   })}
  </div>
 )
}
