import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{CheckCircle2,XCircle,Loader2,Save}from'lucide-react'
import{useAutoApprovalStore}from'@/stores/autoApprovalStore'

interface AutoApprovalSettingsProps{
 projectId:string
}

export function AutoApprovalSettings({projectId}:AutoApprovalSettingsProps):JSX.Element{
 const{
  rules,
  loading,
  setRuleEnabled,
  setAllEnabled,
  getEnabledCount,
  loadFromServer,
  saveToServer
 }=useAutoApprovalStore()
 const[saving,setSaving]=useState(false)

 useEffect(()=>{
  loadFromServer(projectId)
 },[projectId,loadFromServer])

 const handleSave=useCallback(async()=>{
  setSaving(true)
  await saveToServer()
  setSaving(false)
 },[saveToServer])

 if(loading){
  return(
   <Card>
    <CardHeader>
     <DiamondMarker>自動承認設定</DiamondMarker>
    </CardHeader>
    <CardContent className="flex items-center justify-center py-8">
     <Loader2 size={20} className="animate-spin text-nier-text-light"/>
    </CardContent>
   </Card>
)
 }

 return(
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
      <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
       <Save size={14}/>
       <span className="ml-1">{saving?'保存中...':'保存'}</span>
      </Button>
     </div>
    </div>

    <div className="divide-y divide-nier-border-light border border-nier-border-light">
     {rules.map(rule=>(
      <div
       key={rule.category}
       className="flex items-center justify-between px-4 py-2 hover:bg-nier-bg-panel transition-colors"
      >
       <span className="text-nier-small text-nier-text-main">{rule.label}</span>
       <button
        onClick={()=>setRuleEnabled(rule.category,!rule.enabled)}
        className={cn(
         'px-3 py-1 text-nier-caption border transition-colors min-w-[52px]',
         rule.enabled
          ?'border-nier-border-dark bg-nier-bg-selected text-nier-text-main font-medium'
          :'border-nier-border-light text-nier-text-light hover:bg-nier-bg-panel'
)}
       >
        {rule.enabled?'ON':'OFF'}
       </button>
      </div>
))}
    </div>

    <div className="p-3 bg-nier-bg-panel border border-nier-border-light text-nier-caption text-nier-text-light">
     ONにすると、該当カテゴリのCHECKPOINTは人間の確認なしで自動的に承認されます。
    </div>
   </CardContent>
  </Card>
)
}
