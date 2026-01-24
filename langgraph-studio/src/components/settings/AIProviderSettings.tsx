import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{
 ToggleLeft,ToggleRight,RefreshCw,Save,
 Eye,EyeOff,ChevronDown,ChevronRight,FolderOpen
}from'lucide-react'
import{useAIProviderStore}from'@/stores/aiProviderStore'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{
 type AIProviderConfig,
 type LLMProviderConfig,
 type ComfyUIConfig,
 type VoicevoxConfig,
 type MusicGeneratorConfig,
 type AIServiceCategory,
 PROVIDER_TYPE_LABELS,
 SERVICE_CATEGORIES,
 getServiceCategory
}from'@/types/aiProvider'

interface AIProviderSettingsProps{
 projectId:string
}

interface ProviderCardProps{
 provider:AIProviderConfig
 onUpdate:(updates:Partial<AIProviderConfig>)=>void
 onToggle:()=>void
}

function LLMProviderForm({provider,onUpdate}:{provider:LLMProviderConfig,onUpdate:(u:Partial<LLMProviderConfig>)=>void}){
 const[showKey,setShowKey]=useState(false)
 const{master}=useAIServiceStore()
 const providerId=provider.type==='claude'?'anthropic':'openai'
 const providerMaster=master?.providers[providerId]
 const models=providerMaster?.models||[]

 return(
  <div className="space-y-3">
   <div>
    <label className="block text-nier-caption text-nier-text-light mb-1">API Key</label>
    <div className="flex gap-2">
     <input
      type={showKey?'text':'password'}
      className="flex-1 bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
    <label className="block text-nier-caption text-nier-text-light mb-1">Model</label>
    <select
     className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
     value={provider.model}
     onChange={e=>onUpdate({model:e.target.value})}
    >
     {models.map(m=><option key={m.id} value={m.id}>{m.label}</option>)}
    </select>
   </div>
   <div>
    <label className="block text-nier-caption text-nier-text-light mb-1">Endpoint</label>
    <input
     type="text"
     className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Max Tokens</label>
     <input
      type="number"
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.maxTokens}
      onChange={e=>onUpdate({maxTokens:parseInt(e.target.value)||4096})}
     />
    </div>
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Temperature: {provider.temperature}</label>
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

function ComfyUIForm({provider,onUpdate}:{provider:ComfyUIConfig,onUpdate:(u:Partial<ComfyUIConfig>)=>void}){
 const{master}=useAIServiceStore()
 const comfyuiMaster=master?.providers['comfyui']as{samplers?:string[],schedulers?:string[]}|undefined
 const samplers=comfyuiMaster?.samplers||[]
 const schedulers=comfyuiMaster?.schedulers||[]

 return(
  <div className="space-y-3">
   <div>
    <label className="block text-nier-caption text-nier-text-light mb-1">Endpoint</label>
    <input
     type="text"
     className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Workflow File</label>
     <div className="flex gap-2">
      <input
       type="text"
       className="flex-1 bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
       value={provider.workflowFile}
       onChange={e=>onUpdate({workflowFile:e.target.value})}
      />
      <button className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors">
       <FolderOpen size={16}/>
      </button>
     </div>
    </div>
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Output Dir</label>
     <input
      type="text"
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.outputDir}
      onChange={e=>onUpdate({outputDir:e.target.value})}
     />
    </div>
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Steps</label>
     <input
      type="number"
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.steps}
      onChange={e=>onUpdate({steps:parseInt(e.target.value)||20})}
     />
    </div>
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">CFG Scale</label>
     <input
      type="number"
      step="0.5"
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.cfgScale}
      onChange={e=>onUpdate({cfgScale:parseFloat(e.target.value)||7.0})}
     />
    </div>
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Sampler</label>
     <select
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.sampler}
      onChange={e=>onUpdate({sampler:e.target.value})}
     >
      {samplers.map(s=><option key={s} value={s}>{s}</option>)}
     </select>
    </div>
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Scheduler</label>
     <select
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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

function VoicevoxForm({provider,onUpdate}:{provider:VoicevoxConfig,onUpdate:(u:Partial<VoicevoxConfig>)=>void}){
 return(
  <div className="space-y-3">
   <div>
    <label className="block text-nier-caption text-nier-text-light mb-1">Endpoint</label>
    <input
     type="text"
     className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
   <div className="grid grid-cols-2 gap-3">
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Speaker ID</label>
     <input
      type="number"
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.speakerId}
      onChange={e=>onUpdate({speakerId:parseInt(e.target.value)||1})}
     />
    </div>
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Speed: {provider.speed}</label>
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

function MusicForm({provider,onUpdate}:{provider:MusicGeneratorConfig,onUpdate:(u:Partial<MusicGeneratorConfig>)=>void}){
 const[showKey,setShowKey]=useState(false)
 return(
  <div className="space-y-3">
   <div>
    <label className="block text-nier-caption text-nier-text-light mb-1">API Key</label>
    <div className="flex gap-2">
     <input
      type={showKey?'text':'password'}
      className="flex-1 bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
    <label className="block text-nier-caption text-nier-text-light mb-1">Endpoint</label>
    <input
     type="text"
     className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
     value={provider.endpoint}
     onChange={e=>onUpdate({endpoint:e.target.value})}
    />
   </div>
  </div>
)
}

function ProviderCard({provider,onUpdate,onToggle}:ProviderCardProps){
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
    return<LLMProviderForm provider={provider as LLMProviderConfig} onUpdate={onUpdate}/>
   case'comfyui':
    return<ComfyUIForm provider={provider as ComfyUIConfig} onUpdate={onUpdate}/>
   case'voicevox':
    return<VoicevoxForm provider={provider as VoicevoxConfig} onUpdate={onUpdate}/>
   case'suno':
    return<MusicForm provider={provider as MusicGeneratorConfig} onUpdate={onUpdate}/>
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
     <span className="text-nier-caption text-nier-text-light">({PROVIDER_TYPE_LABELS[provider.type]})</span>
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
 const{providers,updateProvider,toggleProvider,resetToDefaults,loadFromServer,saveToServer,loading}=useAIProviderStore()
 const{fetchMaster}=useAIServiceStore()
 const[saving,setSaving]=useState(false)

 useEffect(()=>{
  fetchMaster()
  loadFromServer(projectId)
 },[projectId])

 const handleSave=useCallback(async()=>{
  setSaving(true)
  await saveToServer(projectId)
  setSaving(false)
 },[projectId,saveToServer])

 const getProvidersByCategory=(category:AIServiceCategory)=>{
  return providers.filter(p=>getServiceCategory(p.type)===category)
 }

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
     <DiamondMarker>AIサービス設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     <div className="flex items-center justify-between">
      <div className="text-nier-small text-nier-text-light">
       {providers.filter(p=>p.enabled).length}/{providers.length} サービスが有効
      </div>
      <div className="flex gap-2">
       <Button variant="ghost" size="sm" onClick={resetToDefaults}>
        <RefreshCw size={14}/>
        <span className="ml-1">リセット</span>
       </Button>
       <Button variant="primary" size="sm" onClick={handleSave} disabled={saving}>
        <Save size={14}/>
        <span className="ml-1">{saving?'保存中...':'保存'}</span>
       </Button>
      </div>
     </div>
    </CardContent>
   </Card>

   {(Object.entries(SERVICE_CATEGORIES)as[AIServiceCategory,typeof SERVICE_CATEGORIES[AIServiceCategory]][]).map(([category,info])=>{
    const categoryProviders=getProvidersByCategory(category)
    if(categoryProviders.length===0)return null
    return(
     <div key={category} className="space-y-2">
      <div className="text-nier-small text-nier-text-light font-medium px-1">{info.label}</div>
      {categoryProviders.map(provider=>(
       <ProviderCard
        key={provider.id}
        provider={provider}
        onUpdate={updates=>updateProvider(provider.id,updates)}
        onToggle={()=>toggleProvider(provider.id)}
       />
))}
     </div>
)
   })}
  </div>
)
}
