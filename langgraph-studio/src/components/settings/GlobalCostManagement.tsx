import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{DollarSign,AlertTriangle,Save,TrendingUp}from'lucide-react'
import{useGlobalCostSettingsStore}from'@/stores/globalCostSettingsStore'

export function GlobalCostManagement():JSX.Element{
 const{settings,budgetStatus,loading,error,fetchSettings,updateSettings,fetchBudgetStatus}=useGlobalCostSettingsStore()
 const[localSettings,setLocalSettings]=useState({
  global_enabled:true,
  global_monthly_limit:100,
  alert_threshold:80,
  stop_on_budget_exceeded:false
 })
 const[saving,setSaving]=useState(false)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 useEffect(()=>{
  fetchSettings()
  fetchBudgetStatus()
 },[fetchSettings,fetchBudgetStatus])

 useEffect(()=>{
  if(settings){
   setLocalSettings({
    global_enabled:settings.global_enabled,
    global_monthly_limit:settings.global_monthly_limit,
    alert_threshold:settings.alert_threshold,
    stop_on_budget_exceeded:settings.stop_on_budget_exceeded
   })
  }
 },[settings])

 const showMsg=useCallback((text:string,type:'success'|'error')=>{
  setMessage({text,type})
  setTimeout(()=>setMessage(null),3000)
 },[])

 const handleSave=async()=>{
  setSaving(true)
  try{
   await updateSettings(localSettings)
   showMsg('設定を保存しました','success')
   fetchBudgetStatus()
  }catch{
   showMsg('保存に失敗しました','error')
  }finally{
   setSaving(false)
  }
 }

 if(loading&&!settings){
  return<div className="text-center py-8 text-nier-text-light">読み込み中...</div>
 }

 return(
  <div className="space-y-4">
   {message&&(
    <div className={cn(
     'px-4 py-2 text-nier-small border',
     message.type==='success'?'border-nier-accent-green text-nier-accent-green':'border-nier-accent-red text-nier-accent-red'
)}>
     {message.text}
    </div>
)}

   {error&&(
    <div className="px-4 py-2 text-nier-small border border-nier-accent-red text-nier-accent-red">
     {error}
    </div>
)}

   <Card>
    <CardHeader>
     <TrendingUp size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">予算ステータス</span>
     <span className="text-nier-caption opacity-60 ml-2">今月の使用状況</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {budgetStatus?(
      <div className="space-y-4">
       <div className="grid grid-cols-3 gap-4">
        <div>
         <div className="text-nier-caption text-nier-text-light">使用額</div>
         <div className="text-nier-body font-mono">${budgetStatus.current_usage.toFixed(2)}</div>
        </div>
        <div>
         <div className="text-nier-caption text-nier-text-light">月額上限</div>
         <div className="text-nier-body font-mono">${budgetStatus.monthly_limit.toFixed(2)}</div>
        </div>
        <div>
         <div className="text-nier-caption text-nier-text-light">残り</div>
         <div className="text-nier-body font-mono">${budgetStatus.remaining.toFixed(2)}</div>
        </div>
       </div>
       <div>
        <div className="flex justify-between text-nier-caption mb-1">
         <span className="text-nier-text-light">使用率</span>
         <span className={cn(
          budgetStatus.is_over_budget?'text-nier-accent-red':
          budgetStatus.is_warning?'text-nier-accent-orange':
          'text-nier-text-main'
)}>{budgetStatus.usage_percent.toFixed(1)}%</span>
        </div>
        <div className="h-2 bg-nier-bg-main border border-nier-border-light">
         <div
          className={cn(
           'h-full transition-all',
           budgetStatus.is_over_budget?'bg-nier-accent-red':
           budgetStatus.is_warning?'bg-nier-accent-orange':
           'bg-nier-accent-green'
)}
          style={{width:`${Math.min(100,budgetStatus.usage_percent)}%`}}
         />
        </div>
       </div>
       {budgetStatus.is_over_budget&&(
        <div className="flex items-center gap-2 px-3 py-2 bg-nier-bg-main border border-nier-accent-red">
         <AlertTriangle size={14} className="text-nier-accent-red"/>
         <span className="text-nier-small text-nier-accent-red">予算を超過しています</span>
        </div>
)}
       {budgetStatus.is_warning&&!budgetStatus.is_over_budget&&(
        <div className="flex items-center gap-2 px-3 py-2 bg-nier-bg-main border border-nier-accent-orange">
         <AlertTriangle size={14} className="text-nier-accent-orange"/>
         <span className="text-nier-small text-nier-accent-orange">警告しきい値({budgetStatus.alert_threshold}%)を超えています</span>
        </div>
)}
      </div>
):(
      <div className="text-center py-4 text-nier-text-light">データなし</div>
)}
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <DollarSign size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">全体予算設定</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light space-y-4">
     <div className="flex items-center gap-3">
      <label className="flex items-center gap-2 cursor-pointer">
       <input
        type="checkbox"
        checked={localSettings.global_enabled}
        onChange={e=>setLocalSettings(s=>({...s,global_enabled:e.target.checked}))}
        className="w-4 h-4"
       />
       <span className="text-nier-small">予算管理を有効化</span>
      </label>
     </div>

     <div className="grid grid-cols-2 gap-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">月額上限 (USD)</label>
       <input
        type="number"
        min={0}
        step={10}
        value={localSettings.global_monthly_limit}
        onChange={e=>setLocalSettings(s=>({...s,global_monthly_limit:Number(e.target.value)}))}
        className="w-full bg-nier-bg-main border border-nier-border-light px-3 py-2 text-nier-small text-nier-text-main focus:outline-none focus:border-nier-border-dark"
        disabled={!localSettings.global_enabled}
       />
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">警告しきい値 (%)</label>
       <input
        type="number"
        min={0}
        max={100}
        value={localSettings.alert_threshold}
        onChange={e=>setLocalSettings(s=>({...s,alert_threshold:Number(e.target.value)}))}
        className="w-full bg-nier-bg-main border border-nier-border-light px-3 py-2 text-nier-small text-nier-text-main focus:outline-none focus:border-nier-border-dark"
        disabled={!localSettings.global_enabled}
       />
      </div>
     </div>

     <div className="flex items-center gap-3">
      <label className="flex items-center gap-2 cursor-pointer">
       <input
        type="checkbox"
        checked={localSettings.stop_on_budget_exceeded}
        onChange={e=>setLocalSettings(s=>({...s,stop_on_budget_exceeded:e.target.checked}))}
        className="w-4 h-4"
        disabled={!localSettings.global_enabled}
       />
       <span className="text-nier-small">予算超過時にAI処理を停止</span>
      </label>
     </div>

     <div className="pt-2">
      <Button variant="primary" onClick={handleSave} disabled={saving}>
       <Save size={14}/>
       <span className="ml-1">{saving?'保存中...':'設定を保存'}</span>
      </Button>
     </div>
    </CardContent>
   </Card>
  </div>
)
}
