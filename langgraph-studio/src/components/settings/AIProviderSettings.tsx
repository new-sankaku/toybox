import{useState,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{
 ToggleLeft,ToggleRight,RefreshCw,
 Eye,EyeOff,ChevronDown,ChevronRight,FolderOpen
}from'lucide-react'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{
 type AIProviderConfig,
 type LLMProviderConfig,
 type ComfyUIConfig,
 type VoicevoxConfig,
 type MusicGeneratorConfig
}from'@/types/aiProvider'

interface AIProviderSettingsProps{
 projectId:string
}

interface ProviderCardProps{
 provider:AIProviderConfig
 onUpdate:(updates:Partial<AIProviderConfig>)=>void
 onToggle:()=>void
 isFieldChanged:(field:string)=>boolean
}

function LLMProviderForm({provider,onUpdate,isFieldChanged}:{provider:LLMProviderConfig,onUpdate:(u:Partial<LLMProviderConfig>)=>void,isFieldChanged:(field:string)=>boolean}){
 const[showKey,setShowKey]=useState(false)
 const{master}=useAIServiceStore()
 const providerId=provider.type==='claude'?'anthropic':'openai'
 const providerMaster=master?.providers[providerId]
 const models=providerMaster?.models||[]
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
    <label className={cn('block text-nier-caption mb-1',isFieldChanged('model')?'text-nier-accent-red':'text-nier-text-light')}>Model</label>
    <select
     className={cn('w-full',baseInputClass,isFieldChanged('model')?changedInputClass:'border-nier-border-light')}
     value={provider.model}
     onChange={e=>onUpdate({model:e.target.value})}
    >
     {models.map(m=><option key={m.id} value={m.id}>{m.label}</option>)}
    </select>
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
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('maxTokens')?'text-nier-accent-red':'text-nier-text-light')}>Max Tokens</label>
     <input
      type="number"
      className={cn('w-full',baseInputClass,isFieldChanged('maxTokens')?changedInputClass:'border-nier-border-light')}
      value={provider.maxTokens}
      onChange={e=>onUpdate({maxTokens:parseInt(e.target.value)||4096})}
     />
    </div>
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('temperature')?'text-nier-accent-red':'text-nier-text-light')}>Temperature: {provider.temperature}</label>
     <input
      type="range"
      min="0"
      max="1"
      step="0.1"
      className="w-full"
      value={provider.temperature}
      onChange={e=>onUpdate({temperature:parseFloat(e.target.value)})}
     />
    </div>
   </div>
  </div>
)
}

function ComfyUIForm({provider,onUpdate,isFieldChanged}:{provider:ComfyUIConfig,onUpdate:(u:Partial<ComfyUIConfig>)=>void,isFieldChanged:(field:string)=>boolean}){
 const{master}=useAIServiceStore()
 const comfyuiMaster=master?.providers['comfyui']as{samplers?:string[],schedulers?:string[]}|undefined
 const samplers=comfyuiMaster?.samplers||[]
 const schedulers=comfyuiMaster?.schedulers||[]
 const changedInputClass='border-nier-accent-red text-nier-accent-red'
 const baseInputClass='bg-nier-bg-panel border px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark'

 return(
  <div className="space-y-3">
   <div>
    <label className={cn('block text-nier-caption mb-1',isFieldChanged('endpoint')?'text-nier-accent-red':'text-nier-text-light')}>Endpoint</label>
    <input
     type="text"
     className={cn('w-full',baseInputClass,isFieldChanged('endpoint')?changedInputClass:'border-nier-border-light')}
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('workflowFile')?'text-nier-accent-red':'text-nier-text-light')}>Workflow File</label>
     <div className="flex gap-2">
      <input
       type="text"
       className={cn('flex-1',baseInputClass,isFieldChanged('workflowFile')?changedInputClass:'border-nier-border-light')}
       value={provider.workflowFile}
       onChange={e=>onUpdate({workflowFile:e.target.value})}
      />
      <button className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors">
       <FolderOpen size={16}/>
      </button>
     </div>
    </div>
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('outputDir')?'text-nier-accent-red':'text-nier-text-light')}>Output Dir</label>
     <input
      type="text"
      className={cn('w-full',baseInputClass,isFieldChanged('outputDir')?changedInputClass:'border-nier-border-light')}
      value={provider.outputDir}
      onChange={e=>onUpdate({outputDir:e.target.value})}
     />
    </div>
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('steps')?'text-nier-accent-red':'text-nier-text-light')}>Steps</label>
     <input
      type="number"
      className={cn('w-full',baseInputClass,isFieldChanged('steps')?changedInputClass:'border-nier-border-light')}
      value={provider.steps}
      onChange={e=>onUpdate({steps:parseInt(e.target.value)||20})}
     />
    </div>
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('cfgScale')?'text-nier-accent-red':'text-nier-text-light')}>CFG Scale</label>
     <input
      type="number"
      step="0.5"
      className={cn('w-full',baseInputClass,isFieldChanged('cfgScale')?changedInputClass:'border-nier-border-light')}
      value={provider.cfgScale}
      onChange={e=>onUpdate({cfgScale:parseFloat(e.target.value)||7.0})}
     />
    </div>
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('sampler')?'text-nier-accent-red':'text-nier-text-light')}>Sampler</label>
     <select
      className={cn('w-full',baseInputClass,isFieldChanged('sampler')?changedInputClass:'border-nier-border-light')}
      value={provider.sampler}
      onChange={e=>onUpdate({sampler:e.target.value})}
     >
      {samplers.map(s=><option key={s} value={s}>{s}</option>)}
     </select>
    </div>
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('scheduler')?'text-nier-accent-red':'text-nier-text-light')}>Scheduler</label>
     <select
      className={cn('w-full',baseInputClass,isFieldChanged('scheduler')?changedInputClass:'border-nier-border-light')}
      value={provider.scheduler}
      onChange={e=>onUpdate({scheduler:e.target.value})}
     >
      {schedulers.map(s=><option key={s} value={s}>{s}</option>)}
     </select>
    </div>
   </div>
  </div>
)
}

function VoicevoxForm({provider,onUpdate,isFieldChanged}:{provider:VoicevoxConfig,onUpdate:(u:Partial<VoicevoxConfig>)=>void,isFieldChanged:(field:string)=>boolean}){
 const changedInputClass='border-nier-accent-red text-nier-accent-red'
 const baseInputClass='bg-nier-bg-panel border px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark'

 return(
  <div className="space-y-3">
   <div>
    <label className={cn('block text-nier-caption mb-1',isFieldChanged('endpoint')?'text-nier-accent-red':'text-nier-text-light')}>Endpoint</label>
    <input
     type="text"
     className={cn('w-full',baseInputClass,isFieldChanged('endpoint')?changedInputClass:'border-nier-border-light')}
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('speakerId')?'text-nier-accent-red':'text-nier-text-light')}>Speaker ID</label>
     <input
      type="number"
      className={cn('w-full',baseInputClass,isFieldChanged('speakerId')?changedInputClass:'border-nier-border-light')}
      value={provider.speakerId}
      onChange={e=>onUpdate({speakerId:parseInt(e.target.value)||1})}
     />
    </div>
    <div>
     <label className={cn('block text-nier-caption mb-1',isFieldChanged('speed')?'text-nier-accent-red':'text-nier-text-light')}>Speed: {provider.speed}</label>
     <input
      type="range"
      min="0.5"
      max="2.0"
      step="0.1"
      className="w-full"
      value={provider.speed}
      onChange={e=>onUpdate({speed:parseFloat(e.target.value)})}
     />
    </div>
   </div>
  </div>
)
}

function MusicForm({provider,onUpdate,isFieldChanged}:{provider:MusicGeneratorConfig,onUpdate:(u:Partial<MusicGeneratorConfig>)=>void,isFieldChanged:(field:string)=>boolean}){
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

function ProviderCard({provider,onUpdate,onToggle,isFieldChanged}:ProviderCardProps){
 const[expanded,setExpanded]=useState(false)
 const[testing,setTesting]=useState(false)
 const[testResult,setTestResult]=useState<{success:boolean,message:string}|null>(null)

 const handleTest=async()=>{
  setTesting(true)
  setTestResult(null)
  try{
   const{aiProviderApi}=await import('@/services/apiService')
   const providerType=provider.type==='claude'?'anthropic':provider.type
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
   case'openai':
    return<LLMProviderForm provider={provider as LLMProviderConfig} onUpdate={onUpdate} isFieldChanged={isFieldChanged}/>
   case'comfyui':
    return<ComfyUIForm provider={provider as ComfyUIConfig} onUpdate={onUpdate} isFieldChanged={isFieldChanged}/>
   case'voicevox':
    return<VoicevoxForm provider={provider as VoicevoxConfig} onUpdate={onUpdate} isFieldChanged={isFieldChanged}/>
   case'suno':
    return<MusicForm provider={provider as MusicGeneratorConfig} onUpdate={onUpdate} isFieldChanged={isFieldChanged}/>
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
     <div className="flex items-center gap-2 pt-2 border-t border-nier-border-light">
      <Button variant="ghost" size="sm" onClick={handleTest} disabled={testing}>
       <RefreshCw size={14} className={testing?'animate-spin':''}/>
       <span className="ml-1">{testing?'テスト中...':'テスト接続'}</span>
      </Button>
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

 useEffect(()=>{
  fetchMaster()
  loadProviderConfigs(projectId)
 },[projectId])

 const getProvidersByServiceType=(serviceType:string)=>{
  return providerConfigs.filter(p=>p.serviceType===serviceType)
 }

 const getServiceLabel=(serviceType:string)=>{
  if(!master)return serviceType
  return master.services[serviceType]?.label||serviceType
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
       />
))}
     </div>
)
   })}
  </div>
)
}
