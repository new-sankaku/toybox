import{useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{cn}from'@/lib/utils'
import{ToggleLeft,ToggleRight,DollarSign,Info}from'lucide-react'
import{useCostSettingsStore}from'@/stores/costSettingsStore'
import{useAIServiceStore}from'@/stores/aiServiceStore'

interface CostSettingsProps{
 projectId:string
}

const SERVICE_LABELS:Record<string,string>={
 llm:'LLM（テキスト生成）',
 image:'画像生成',
 audio:'音声合成',
 music:'音楽生成'
}

interface ModelPricing{
 input?:number
 output?:number
 per_image?:number
 per_track?:number
 per_1k_chars?:number
}

function formatPricing(pricing:ModelPricing|undefined):string{
 if(!pricing)return'-'
 if(pricing.input!==undefined&&pricing.output!==undefined){
  return`In ${pricing.input} / Out ${pricing.output}`
 }
 if(pricing.per_image!==undefined)return`${pricing.per_image}/画像`
 if(pricing.per_track!==undefined)return`${pricing.per_track}/曲`
 if(pricing.per_1k_chars!==undefined)return`${pricing.per_1k_chars}/1000文字`
 return'-'
}

interface ServiceCostCardProps{
 serviceType:string
 label:string
}

function ServiceCostCard({serviceType,label}:ServiceCostCardProps):JSX.Element{
 const{settings,pricing,updateServiceLimit}=useCostSettingsStore()
 const service=settings.services[serviceType]
 const{master}=useAIServiceStore()

 const getProviderPricing=()=>{
  if(!pricing||!master)return[]
  const serviceProviders=master.services[serviceType as keyof typeof master.services]?.providers||[]
  return serviceProviders.flatMap(p=>
   p.models.map(m=>{
    const modelPricing=pricing.models[m.id]
    return{
     provider:p.label,
     model:m.label,
     pricing:modelPricing?.pricing
    }
   })
)
 }

 const providerPricings=getProviderPricing()

 return(
  <Card>
   <div className="flex items-center justify-between px-4 py-3">
    <div className="flex items-center gap-3">
     <DollarSign size={16} className="text-nier-text-light"/>
     <span className="text-nier-small text-nier-text-main">{label}</span>
    </div>
    <button
     onClick={()=>updateServiceLimit(serviceType,{enabled:!service?.enabled})}
     className="p-1 rounded transition-colors focus:outline-none"
    >
     {service?.enabled?(
      <div className="flex items-center gap-1 text-nier-accent-green">
       <ToggleRight size={20}/>
       <span className="text-nier-caption">有効</span>
      </div>
):(
      <div className="flex items-center gap-1 text-nier-text-light">
       <ToggleLeft size={20}/>
       <span className="text-nier-caption">無効</span>
      </div>
)}
    </button>
   </div>
   <CardContent className="border-t border-nier-border-light space-y-3">
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">月額上限 ($)</label>
     <input
      type="number"
      min="0"
      step="1"
      className={cn(
       'w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small',
       'focus:outline-none focus:border-nier-border-dark',
       !service?.enabled&&'opacity-50'
)}
      value={service?.monthlyLimit||0}
      onChange={e=>updateServiceLimit(serviceType,{monthlyLimit:parseFloat(e.target.value)||0})}
      disabled={!service?.enabled}
     />
    </div>
    {providerPricings.length>0&&(
     <div className="pt-2 border-t border-nier-border-light">
      <div className="flex items-center gap-1 text-nier-caption text-nier-text-light mb-2">
       <Info size={12}/>
       <span>参考単価 ($/1Mトークン)</span>
      </div>
      <table className="text-nier-caption">
       <thead>
        <tr className="text-nier-text-light">
         <th className="text-left font-normal pb-1 pr-4">モデル</th>
         <th className="text-left font-normal pb-1 pr-4">In</th>
         <th className="text-left font-normal pb-1">Out</th>
        </tr>
       </thead>
       <tbody>
        {providerPricings.map((pp,i)=>(
         <tr key={i}>
          <td className="text-nier-text-light py-0.5 pr-4">{pp.model}</td>
          <td className="text-nier-text-main py-0.5 pr-4">{pp.pricing?.input!==undefined?`${pp.pricing.input}`:'-'}</td>
          <td className="text-nier-text-main py-0.5">{pp.pricing?.output!==undefined?`${pp.pricing.output}`:'-'}</td>
         </tr>
))}
       </tbody>
      </table>
     </div>
)}
   </CardContent>
  </Card>
)
}

export function CostSettings({projectId}:CostSettingsProps):JSX.Element{
 const{
  settings,
  pricing,
  loading,
  updateGlobalEnabled,
  updateGlobalLimit,
  fetchPricing,
  resetToDefaults,
  loadFromServer
 }=useCostSettingsStore()
 const{fetchMaster}=useAIServiceStore()

 useEffect(()=>{
  fetchPricing()
  fetchMaster()
  loadFromServer(projectId)
 },[projectId])

 if(loading){
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
      <DollarSign size={16} className="text-nier-text-light"/>
      <span className="text-nier-small text-nier-text-main font-medium">全体コスト上限</span>
     </div>
     <button
      onClick={()=>updateGlobalEnabled(!settings.globalEnabled)}
      className="p-1 rounded transition-colors focus:outline-none"
     >
      {settings.globalEnabled?(
       <div className="flex items-center gap-1 text-nier-accent-green">
        <ToggleRight size={20}/>
        <span className="text-nier-caption">有効</span>
       </div>
):(
       <div className="flex items-center gap-1 text-nier-text-light">
        <ToggleLeft size={20}/>
        <span className="text-nier-caption">無効</span>
       </div>
)}
     </button>
    </div>
    <CardContent className="border-t border-nier-border-light">
     <div>
      <label className="block text-nier-caption text-nier-text-light mb-1">月額上限 ($)</label>
      <input
       type="number"
       min="0"
       step="1"
       className={cn(
        'w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small',
        'focus:outline-none focus:border-nier-border-dark',
        !settings.globalEnabled&&'opacity-50'
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
