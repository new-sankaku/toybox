import{useState,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{
 ToggleLeft,ToggleRight,RefreshCw,
 Eye,EyeOff,ChevronDown,ChevronRight
}from'lucide-react'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{
 type AIProviderConfig,
 type LLMProviderConfig,
 type AudioCraftConfig
}from'@/types/aiProvider'
import{providerHealthApi,type ApiProviderHealth}from'@/services/apiService'

interface AIProviderSettingsProps{
 projectId:string
}

interface ProviderCardProps{
 provider:AIProviderConfig
 onUpdate:(updates:Partial<AIProviderConfig>)=>void
 onToggle:()=>void
 isFieldChanged:(field:string)=>boolean
 health?:ApiProviderHealth|null
 onCheckHealth?:()=>void
 healthChecking?:boolean
}

function LLMProviderForm({provider,onUpdate,isFieldChanged}:{provider:LLMProviderConfig,onUpdate:(u:Partial<LLMProviderConfig>)=>void,isFieldChanged:(field:string)=>boolean}){
 const[showKey,setShowKey]=useState(false)
 const changedInputClass='border-nier-accent-red text-nier-accent-red'
 const baseInputClass='bg-nier-bg-panel border px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark'

 return(
  <div className="space-y-3">
   <div>
    <label className={cn('block text-nier-caption mb-1',isFieldChanged('apiKey')?'text-nier-accent-red':'text-nier-text-light')}>API Key</label>
    <div className="flex gap-2">
     <input
      type={showKey?'text':'password'}
      className={cn('flex-1',baseInputClass,isFieldChanged('apiKey')?changedInputClass:'border-nier-border-light')}
      placeholder="sk-..."
      value={provider.apiKey}
      onChange={e=>onUpdate({apiKey:e.target.value})}
     />
     <button
      className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors"
      onClick={()=>setShowKey(!showKey)}
     >
      {showKey?<EyeOff size={16}/>:<Eye size={16}/>}
     </button>
    </div>
   </div>
   <div>
    <label className={cn('block text-nier-caption mb-1',isFieldChanged('endpoint')?'text-nier-accent-red':'text-nier-text-light')}>Endpoint</label>
    <input
     type="text"
     className={cn('w-full',baseInputClass,isFieldChanged('endpoint')?changedInputClass:'border-nier-border-light')}
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
  </div>
)
}

function EndpointOnlyForm({provider,onUpdate,isFieldChanged}:{provider:{endpoint:string},onUpdate:(u:{endpoint:string})=>void,isFieldChanged:(field:string)=>boolean}){
 const changedInputClass='border-nier-accent-red text-nier-accent-red'
 const baseInputClass='bg-nier-bg-panel border px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark'

 return(
  <div>
   <label className={cn('block text-nier-caption mb-1',isFieldChanged('endpoint')?'text-nier-accent-red':'text-nier-text-light')}>Endpoint</label>
   <input
    type="text"
    className={cn('w-full',baseInputClass,isFieldChanged('endpoint')?changedInputClass:'border-nier-border-light')}
    value={provider.endpoint}
    onChange={e=>onUpdate({endpoint:e.target.value})}
   />
  </div>
)
}


function AudioCraftForm({provider,onUpdate,isFieldChanged}:{provider:AudioCraftConfig,onUpdate:(u:Partial<AudioCraftConfig>)=>void,isFieldChanged:(field:string)=>boolean}){
 const[showKey,setShowKey]=useState(false)
 const changedInputClass='border-nier-accent-red text-nier-accent-red'
 const baseInputClass='bg-nier-bg-panel border px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark'

 return(
  <div className="space-y-3">
   <div>
    <label className={cn('block text-nier-caption mb-1',isFieldChanged('apiKey')?'text-nier-accent-red':'text-nier-text-light')}>API Key</label>
    <div className="flex gap-2">
     <input
      type={showKey?'text':'password'}
      className={cn('flex-1',baseInputClass,isFieldChanged('apiKey')?changedInputClass:'border-nier-border-light')}
      value={provider.apiKey}
      onChange={e=>onUpdate({apiKey:e.target.value})}
     />
     <button
      className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors"
      onClick={()=>setShowKey(!showKey)}
     >
      {showKey?<EyeOff size={16}/>:<Eye size={16}/>}
     </button>
    </div>
   </div>
   <div>
    <label className={cn('block text-nier-caption mb-1',isFieldChanged('endpoint')?'text-nier-accent-red':'text-nier-text-light')}>Endpoint</label>
    <input
     type="text"
     className={cn('w-full',baseInputClass,isFieldChanged('endpoint')?changedInputClass:'border-nier-border-light')}
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
  </div>
)
}

function ProviderCard({provider,onUpdate,onToggle,isFieldChanged,health,onCheckHealth,healthChecking}:ProviderCardProps){
 const[expanded,setExpanded]=useState(false)
 const[testing,setTesting]=useState(false)
 const[testResult,setTestResult]=useState<{success:boolean,message:string}|null>(null)

 const{master}=useAIServiceStore()

 const handleTest=async()=>{
  setTesting(true)
  setTestResult(null)
  try{
   const{aiProviderApi}=await import('@/services/apiService')
   const providerType=master?.providerTypeMapping?.[provider.type]||provider.type
   const config:Record<string,unknown>={apiKey:(provider as LLMProviderConfig).apiKey}
   const result=await aiProviderApi.testConnection(providerType,config)
   setTestResult({success:result.success,message:result.message})
  }catch{
   setTestResult({success:false,message:'接続テストに失敗しました'})
  }
  setTesting(false)
 }

 const renderForm=()=>{
  switch(provider.type){
   case'claude':
    return<LLMProviderForm provider={provider as LLMProviderConfig} onUpdate={onUpdate} isFieldChanged={isFieldChanged}/>
   case'comfyui':
   case'tts':
    return<EndpointOnlyForm provider={provider as{endpoint:string}} onUpdate={onUpdate} isFieldChanged={isFieldChanged}/>
   case'audiocraft':
    return<AudioCraftForm provider={provider as AudioCraftConfig} onUpdate={onUpdate} isFieldChanged={isFieldChanged}/>
   default:
    return null
  }
 }

 return(
  <Card>
   <div
    className={cn(
     'flex items-center justify-between px-4 py-3 cursor-pointer',
     'hover:bg-nier-bg-panel transition-colors'
)}
    onClick={()=>setExpanded(!expanded)}
   >
    <div className="flex items-center gap-3">
     {expanded?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
     <span className="text-nier-small text-nier-text-main">{provider.name}</span>
     {health&&(
      <span className={cn('inline-block w-2 h-2 rounded-full',health.healthy?'bg-nier-accent-green':health.error?'bg-nier-accent-red':'bg-nier-text-light')}/>
)}
    </div>
    <div className="flex items-center gap-2" onClick={e=>e.stopPropagation()}>
     <button
      onClick={onToggle}
      className="p-1 rounded transition-colors focus:outline-none"
     >
      {provider.enabled?(
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
   </div>
   {expanded&&(
    <CardContent className="border-t border-nier-border-light space-y-4">
     {renderForm()}
     {health&&(
      <div className="flex items-center gap-3 text-nier-caption text-nier-text-light">
       <span>ヘルス: {health.healthy?'正常':'異常'}</span>
       {health.latencyMs!=null&&<span>{health.latencyMs}ms</span>}
       {health.lastChecked&&<span>最終チェック: {new Date(health.lastChecked).toLocaleTimeString('ja-JP')}</span>}
      </div>
)}
     <div className="flex items-center gap-2 pt-2 border-t border-nier-border-light">
      <Button variant="ghost" size="sm" onClick={handleTest} disabled={testing}>
       <RefreshCw size={14} className={testing?'animate-spin':''}/>
       <span className="ml-1">{testing?'テスト中...':'テスト接続'}</span>
      </Button>
      {onCheckHealth&&(
       <Button variant="ghost" size="sm" onClick={onCheckHealth} disabled={healthChecking}>
        <RefreshCw size={14} className={healthChecking?'animate-spin':''}/>
        <span className="ml-1">{healthChecking?'チェック中':'ヘルスチェック'}</span>
       </Button>
)}
      {testResult&&(
       <span className={cn(
        'text-nier-caption',
        testResult.success?'text-nier-accent-green':'text-nier-accent-red'
)}>
        {testResult.message}
       </span>
)}
     </div>
    </CardContent>
)}
  </Card>
)
}

export function AIProviderSettings({projectId}:AIProviderSettingsProps):JSX.Element{
 const{
  providerConfigs,
  updateProviderConfig,
  toggleProviderConfig,
  loadProviderConfigs,
  providerLoading,
  fetchMaster,
  master,
  isProviderFieldChanged
 }=useAIServiceStore()

 const[healthMap,setHealthMap]=useState<Record<string,ApiProviderHealth>>({})
 const[healthChecking,setHealthChecking]=useState<Record<string,boolean>>({})

 useEffect(()=>{
  fetchMaster()
  loadProviderConfigs(projectId)
  providerHealthApi.getAll().then(list=>{
   const map:Record<string,ApiProviderHealth>={}
   list.forEach(h=>{map[h.providerId]=h})
   setHealthMap(map)
  }).catch(()=>{})
 },[projectId])

 const handleCheckHealth=async(providerId:string)=>{
  setHealthChecking(prev=>({...prev,[providerId]:true}))
  try{
   const result=await providerHealthApi.check(providerId)
   setHealthMap(prev=>({...prev,[providerId]:result}))
  }catch{}
  setHealthChecking(prev=>({...prev,[providerId]:false}))
 }

 const getProvidersByServiceType=(serviceType:string)=>{
  return providerConfigs.filter(p=>p.serviceType===serviceType)
 }

 const getServiceLabel=(serviceType:string)=>{
  if(!master)return serviceType
  return master.services[serviceType as keyof typeof master.services]?.label||serviceType
 }

 if(providerLoading){
  return(
   <Card>
    <CardContent>
     <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
    </CardContent>
   </Card>
)
 }

 const serviceTypes=master?.serviceTypes||[]

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <DiamondMarker>AIサービス設定</DiamondMarker>
    </CardHeader>
    <CardContent>
     <div className="text-nier-small text-nier-text-light">
      {providerConfigs.filter(p=>p.enabled).length}/{providerConfigs.length} サービスが有効
     </div>
    </CardContent>
   </Card>

   {serviceTypes.map(serviceType=>{
    const categoryProviders=getProvidersByServiceType(serviceType)
    if(categoryProviders.length===0)return null
    return(
     <div key={serviceType} className="space-y-2">
      <div className="text-nier-small text-nier-text-light font-medium px-1">{getServiceLabel(serviceType)}</div>
      {categoryProviders.map(provider=>(
       <ProviderCard
        key={provider.id}
        provider={provider}
        onUpdate={updates=>updateProviderConfig(provider.id,updates)}
        onToggle={()=>toggleProviderConfig(provider.id)}
        isFieldChanged={field=>isProviderFieldChanged(provider.id,field)}
        health={healthMap[provider.type]||null}
        onCheckHealth={()=>handleCheckHealth(provider.type)}
        healthChecking={!!healthChecking[provider.type]}
       />
))}
     </div>
)
   })}
  </div>
)
}
