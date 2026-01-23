import{useState,useRef}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{
 ToggleLeft,ToggleRight,RefreshCw,Plus,Trash2,
 Eye,EyeOff,Download,Upload,ChevronDown,ChevronRight,FolderOpen
}from'lucide-react'
import{useAIProviderStore}from'@/stores/aiProviderStore'
import{
 type AIProviderConfig,
 type AIProviderType,
 type LLMProviderConfig,
 type ComfyUIConfig,
 type VoicevoxConfig,
 type MusicGeneratorConfig,
 type VideoGeneratorConfig,
 PROVIDER_TYPE_LABELS,
 CLAUDE_MODELS,
 OPENAI_MODELS,
 COMFYUI_SAMPLERS,
 COMFYUI_SCHEDULERS,
 VIDEO_MODELS,
 VIDEO_RESOLUTIONS,
 DEFAULT_LLM_CONFIG,
 DEFAULT_COMFYUI_CONFIG,
 DEFAULT_VOICEVOX_CONFIG,
 DEFAULT_SUNO_CONFIG,
 DEFAULT_VIDEO_CONFIG
}from'@/types/aiProvider'

interface ProviderCardProps{
 provider:AIProviderConfig
 onUpdate:(updates:Partial<AIProviderConfig>)=>void
 onToggle:()=>void
 onRemove:()=>void
}

function LLMProviderForm({provider,onUpdate}:{provider:LLMProviderConfig,onUpdate:(u:Partial<LLMProviderConfig>)=>void}){
 const[showKey,setShowKey]=useState(false)
 const models=provider.type==='claude'?CLAUDE_MODELS:OPENAI_MODELS

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
      {COMFYUI_SAMPLERS.map(s=><option key={s} value={s}>{s}</option>)}
     </select>
    </div>
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">Scheduler</label>
     <select
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.scheduler}
      onChange={e=>onUpdate({scheduler:e.target.value})}
     >
      {COMFYUI_SCHEDULERS.map(s=><option key={s} value={s}>{s}</option>)}
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

function VideoForm({provider,onUpdate}:{provider:VideoGeneratorConfig,onUpdate:(u:Partial<VideoGeneratorConfig>)=>void}){
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
    <label className="block text-nier-caption text-nier-text-light mb-1">Model</label>
    <select
     className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
     value={provider.model}
     onChange={e=>onUpdate({model:e.target.value as 'runway'|'pika'|'stablevideo'})}
    >
     {VIDEO_MODELS.map(m=><option key={m.id} value={m.id}>{m.label}</option>)}
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
     <label className="block text-nier-caption text-nier-text-light mb-1">Resolution</label>
     <select
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.resolution}
      onChange={e=>onUpdate({resolution:e.target.value as '720p'|'1080p'})}
     >
      {VIDEO_RESOLUTIONS.map(r=><option key={r.id} value={r.id}>{r.label}</option>)}
     </select>
    </div>
    <div>
     <label className="block text-nier-caption text-nier-text-light mb-1">FPS</label>
     <input
      type="number"
      min="12"
      max="60"
      className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
      value={provider.fps}
      onChange={e=>onUpdate({fps:parseInt(e.target.value)||24})}
     />
    </div>
   </div>
  </div>
)
}

function ProviderCard({provider,onUpdate,onToggle,onRemove}:ProviderCardProps){
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
   case'video':
    return<VideoForm provider={provider as VideoGeneratorConfig} onUpdate={onUpdate}/>
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
     <button
      onClick={onRemove}
      className="p-1 text-nier-text-light hover:text-nier-accent-red transition-colors"
     >
      <Trash2 size={16}/>
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

export function AIProviderSettings():JSX.Element{
 const{providers,addProvider,updateProvider,toggleProvider,removeProvider,exportSettings,importSettings,resetToDefaults}=useAIProviderStore()
 const fileInputRef=useRef<HTMLInputElement>(null)
 const[showAddMenu,setShowAddMenu]=useState(false)

 const handleExport=()=>{
  const json=exportSettings()
  const blob=new Blob([json],{type:'application/json'})
  const url=URL.createObjectURL(blob)
  const a=document.createElement('a')
  a.href=url
  a.download='ai-providers.json'
  a.click()
  URL.revokeObjectURL(url)
 }

 const handleImport=(e:React.ChangeEvent<HTMLInputElement>)=>{
  const file=e.target.files?.[0]
  if(!file)return
  const reader=new FileReader()
  reader.onload=ev=>{
   const json=ev.target?.result as string
   importSettings(json)
  }
  reader.readAsText(file)
 }

 const handleAddProvider=(type:AIProviderType)=>{
  const id=`${type}-${Date.now()}`
  let config:AIProviderConfig
  switch(type){
   case'claude':
    config={id,name:'Claude (新規)',...DEFAULT_LLM_CONFIG,type:'claude'}
    break
   case'openai':
    config={id,name:'OpenAI (新規)',...DEFAULT_LLM_CONFIG,type:'openai',model:'gpt-4o',endpoint:'https://api.openai.com/v1'}
    break
   case'comfyui':
    config={id,name:'ComfyUI (新規)',...DEFAULT_COMFYUI_CONFIG}
    break
   case'voicevox':
    config={id,name:'VOICEVOX (新規)',...DEFAULT_VOICEVOX_CONFIG}
    break
   case'suno':
    config={id,name:'Suno AI (新規)',...DEFAULT_SUNO_CONFIG}
    break
   case'video':
    config={id,name:'動画生成 (新規)',...DEFAULT_VIDEO_CONFIG}
    break
   default:
    config={id,name:'カスタム',type:'custom',enabled:false,endpoint:'',apiKey:'',settings:{}}
  }
  addProvider(config)
  setShowAddMenu(false)
 }

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <DiamondMarker>AI Provider設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     <div className="flex items-center justify-between">
      <div className="text-nier-small text-nier-text-light">
       {providers.filter(p=>p.enabled).length}/{providers.length} プロバイダーが有効
      </div>
      <div className="flex gap-2">
       <div className="relative">
        <Button variant="ghost" size="sm" onClick={()=>setShowAddMenu(!showAddMenu)}>
         <Plus size={14}/>
         <span className="ml-1">新規追加</span>
        </Button>
        {showAddMenu&&(
         <div className="absolute right-0 top-full mt-1 z-10 bg-nier-bg-main border border-nier-border-dark shadow-lg">
          {(['claude','openai','comfyui','voicevox','suno','video']as AIProviderType[]).map(type=>(
           <button
            key={type}
            className="block w-full px-4 py-2 text-left text-nier-small hover:bg-nier-bg-selected"
            onClick={()=>handleAddProvider(type)}
           >
            {PROVIDER_TYPE_LABELS[type]}
           </button>
))}
         </div>
)}
       </div>
       <Button variant="ghost" size="sm" onClick={handleExport}>
        <Download size={14}/>
        <span className="ml-1">エクスポート</span>
       </Button>
       <Button variant="ghost" size="sm" onClick={()=>fileInputRef.current?.click()}>
        <Upload size={14}/>
        <span className="ml-1">インポート</span>
       </Button>
       <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleImport}/>
       <Button variant="ghost" size="sm" onClick={resetToDefaults}>
        <RefreshCw size={14}/>
        <span className="ml-1">リセット</span>
       </Button>
      </div>
     </div>
     <div className="p-3 bg-nier-bg-panel border border-nier-border-light text-nier-caption text-nier-text-light">
      APIキーはエクスポート時に除外されます。インポート後に再設定してください。
     </div>
    </CardContent>
   </Card>

   {providers.map(provider=>(
    <ProviderCard
     key={provider.id}
     provider={provider}
     onUpdate={updates=>updateProvider(provider.id,updates)}
     onToggle={()=>toggleProvider(provider.id)}
     onRemove={()=>removeProvider(provider.id)}
    />
))}
  </div>
)
}
