import{useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{cn}from'@/lib/utils'
import{ToggleLeft,ToggleRight,DollarSign}from'lucide-react'
import{useCostSettingsStore}from'@/stores/costSettingsStore'

interface CostSettingsProps{
 projectId:string
}

const SERVICE_LABELS:Record<string,string>={
 llm:'LLM（テキスト生成）',
 image:'画像生成',
 audio:'音声合成',
 music:'音楽生成'
}

interface ServiceCostCardProps{
 serviceType:string
 label:string
}

function ServiceCostCard({serviceType,label}:ServiceCostCardProps):JSX.Element{
 const{settings,updateServiceLimit,isServiceFieldChanged}=useCostSettingsStore()
 const service=settings?.services[serviceType]
 const enabledChanged=isServiceFieldChanged(serviceType,'enabled')
 const limitChanged=isServiceFieldChanged(serviceType,'monthlyLimit')

 return(
  <Card>
   <div className="flex items-center justify-between px-4 py-3">
    <div className="flex items-center gap-3">
     <DollarSign size={16} className={enabledChanged?'text-nier-accent-red':'text-nier-text-light'}/>
     <span className={cn('text-nier-small',enabledChanged?'text-nier-accent-red':'text-nier-text-main')}>{label}</span>
    </div>
    <button
     onClick={()=>updateServiceLimit(serviceType,{enabled:!service?.enabled})}
     className="p-1 rounded transition-colors focus:outline-none"
    >
     {service?.enabled?(
      <div className={cn('flex items-center gap-1',enabledChanged?'text-nier-accent-red':'text-nier-accent-green')}>
       <ToggleRight size={20}/>
       <span className="text-nier-caption">有効</span>
      </div>
):(
      <div className={cn('flex items-center gap-1',enabledChanged?'text-nier-accent-red':'text-nier-text-light')}>
       <ToggleLeft size={20}/>
       <span className="text-nier-caption">無効</span>
      </div>
)}
    </button>
   </div>
   <CardContent className="border-t border-nier-border-light space-y-3">
    <div>
     <label className={cn('block text-nier-caption mb-1',limitChanged?'text-nier-accent-red':'text-nier-text-light')}>月額上限 ($)</label>
     <input
      type="number"
      min="0"
      step="1"
      className={cn(
       'w-full bg-nier-bg-panel border px-3 py-2 text-nier-small',
       'focus:outline-none focus:border-nier-border-dark',
       !service?.enabled&&'opacity-50',
       limitChanged?'border-nier-accent-red text-nier-accent-red':'border-nier-border-light'
)}
      value={service?.monthlyLimit||0}
      onChange={e=>updateServiceLimit(serviceType,{monthlyLimit:parseFloat(e.target.value)||0})}
      disabled={!service?.enabled}
     />
    </div>
   </CardContent>
  </Card>
)
}

export function CostSettings({projectId}:CostSettingsProps):JSX.Element{
 const{
  settings,
  loading,
  updateGlobalEnabled,
  updateGlobalLimit,
  loadFromServer,
  isFieldChanged
 }=useCostSettingsStore()
 const globalEnabledChanged=isFieldChanged('globalEnabled')
 const globalLimitChanged=isFieldChanged('globalMonthlyLimit')

 useEffect(()=>{
  loadFromServer(projectId)
 },[projectId])

 if(loading||!settings){
  return(
   <Card>
    <CardContent>
     <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
    </CardContent>
   </Card>
)
 }

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <DiamondMarker>コスト設定</DiamondMarker>
    </CardHeader>
    <CardContent>
     <div className="text-nier-small text-nier-text-light">
      ※コストは概算です
     </div>
    </CardContent>
   </Card>

   <Card>
    <div className="flex items-center justify-between px-4 py-3">
     <div className="flex items-center gap-3">
      <DollarSign size={16} className={globalEnabledChanged?'text-nier-accent-red':'text-nier-text-light'}/>
      <span className={cn('text-nier-small font-medium',globalEnabledChanged?'text-nier-accent-red':'text-nier-text-main')}>全体コスト上限</span>
     </div>
     <button
      onClick={()=>updateGlobalEnabled(!settings.globalEnabled)}
      className="p-1 rounded transition-colors focus:outline-none"
     >
      {settings.globalEnabled?(
       <div className={cn('flex items-center gap-1',globalEnabledChanged?'text-nier-accent-red':'text-nier-accent-green')}>
        <ToggleRight size={20}/>
        <span className="text-nier-caption">有効</span>
       </div>
):(
       <div className={cn('flex items-center gap-1',globalEnabledChanged?'text-nier-accent-red':'text-nier-text-light')}>
        <ToggleLeft size={20}/>
        <span className="text-nier-caption">無効</span>
       </div>
)}
     </button>
    </div>
    <CardContent className="border-t border-nier-border-light">
     <div>
      <label className={cn('block text-nier-caption mb-1',globalLimitChanged?'text-nier-accent-red':'text-nier-text-light')}>月額上限 ($)</label>
      <input
       type="number"
       min="0"
       step="1"
       className={cn(
        'w-full bg-nier-bg-panel border px-3 py-2 text-nier-small',
        'focus:outline-none focus:border-nier-border-dark',
        !settings.globalEnabled&&'opacity-50',
        globalLimitChanged?'border-nier-accent-red text-nier-accent-red':'border-nier-border-light'
)}
       value={settings.globalMonthlyLimit}
       onChange={e=>updateGlobalLimit(parseFloat(e.target.value)||0)}
       disabled={!settings.globalEnabled}
      />
     </div>
    </CardContent>
   </Card>

   <div className="space-y-2">
    <div className="text-nier-small text-nier-text-light font-medium px-1">サービス別コスト上限</div>
    {Object.entries(SERVICE_LABELS).map(([type,label])=>(
     <ServiceCostCard key={type} serviceType={type} label={label}/>
))}
   </div>
  </div>
)
}
