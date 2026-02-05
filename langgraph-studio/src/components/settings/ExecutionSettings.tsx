import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Settings2,RefreshCw,Save}from'lucide-react'
import{
 projectSettingsApi,configApi,
 type ConcurrentLimitsSettings,type WebSocketConfig
}from'@/services/apiService'

export function ExecutionSettings():JSX.Element{
 const[concurrentLimits,setConcurrentLimits]=useState<ConcurrentLimitsSettings|null>(null)
 const[originalConcurrentLimits,setOriginalConcurrentLimits]=useState<ConcurrentLimitsSettings|null>(null)
 const[wsConfig,setWsConfig]=useState<WebSocketConfig|null>(null)
 const[originalWsConfig,setOriginalWsConfig]=useState<WebSocketConfig|null>(null)
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState(false)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 const fetchSettings=useCallback(async()=>{
  setLoading(true)
  try{
   const[limits,ws]=await Promise.all([
    projectSettingsApi.getConcurrentLimits(),
    configApi.getWebSocketConfig()
   ])
   setConcurrentLimits(limits)
   setOriginalConcurrentLimits(JSON.parse(JSON.stringify(limits)))
   setWsConfig(ws)
   setOriginalWsConfig(JSON.parse(JSON.stringify(ws)))
  }catch(e){
   console.error('Failed to fetch execution settings:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{fetchSettings()},[fetchSettings])

 const showMsg=(text:string,type:'success'|'error')=>{
  setMessage({text,type})
  setTimeout(()=>setMessage(null),3000)
 }

 const hasConcurrentChanges=concurrentLimits&&originalConcurrentLimits&&JSON.stringify(concurrentLimits)!==JSON.stringify(originalConcurrentLimits)
 const hasWsChanges=wsConfig&&originalWsConfig&&JSON.stringify(wsConfig)!==JSON.stringify(originalWsConfig)

 const handleSaveConcurrent=async()=>{
  if(!concurrentLimits)return
  setSaving(true)
  try{
   const updated=await projectSettingsApi.updateConcurrentLimits(concurrentLimits)
   setConcurrentLimits(updated)
   setOriginalConcurrentLimits(JSON.parse(JSON.stringify(updated)))
   showMsg('同時実行設定を保存しました','success')
  }catch{
   showMsg('保存に失敗しました','error')
  }finally{
   setSaving(false)
  }
 }

 const handleSaveWs=async()=>{
  if(!wsConfig)return
  setSaving(true)
  try{
   const updated=await projectSettingsApi.updateWebSocketConfig(wsConfig)
   setWsConfig(updated)
   setOriginalWsConfig(JSON.parse(JSON.stringify(updated)))
   showMsg('WebSocket設定を保存しました','success')
  }catch{
   showMsg('保存に失敗しました','error')
  }finally{
   setSaving(false)
  }
 }

 const handleProviderOverrideChange=(provider:string,value:number)=>{
  if(!concurrentLimits)return
  setConcurrentLimits({
   ...concurrentLimits,
   provider_overrides:{...concurrentLimits.provider_overrides,[provider]:value}
  })
 }

 if(loading){
  return<div className="nier-surface-panel text-center py-8">読み込み中...</div>
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
   <Card>
    <CardHeader>
     <Settings2 size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">同時実行制限</span>
     <span className="text-nier-caption opacity-60 ml-2">プロバイダー別の同時リクエスト数</span>
     {hasConcurrentChanges&&(
      <Button variant="primary" size="sm" className="ml-auto" onClick={handleSaveConcurrent} disabled={saving}>
       <Save size={12}/>
       <span className="ml-1">{saving?'保存中...':'保存'}</span>
      </Button>
     )}
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {concurrentLimits?(
      <div className="space-y-4">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">デフォルト最大同時実行数</label>
        <input
         type="number"
         min={1}
         max={20}
         className="nier-input w-32"
         value={concurrentLimits.default_max_concurrent}
         onChange={(e)=>setConcurrentLimits({...concurrentLimits,default_max_concurrent:parseInt(e.target.value)||1})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-2">プロバイダー別設定</label>
        <div className="grid grid-cols-2 gap-3">
         {Object.entries(concurrentLimits.provider_overrides).map(([provider,limit])=>(
          <div key={provider} className="flex items-center gap-2 nier-surface-main p-2 border border-nier-border-light">
           <span className="text-nier-small text-nier-text-main flex-1">{provider}</span>
           <input
            type="number"
            min={1}
            max={20}
            className="nier-input w-16"
            value={limit}
            onChange={(e)=>handleProviderOverrideChange(provider,parseInt(e.target.value)||1)}
           />
          </div>
         ))}
        </div>
       </div>
      </div>
     ):(
      <div className="text-nier-text-light">同時実行設定を取得できませんでした</div>
     )}
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <RefreshCw size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">WebSocket再接続設定</span>
     {hasWsChanges&&(
      <Button variant="primary" size="sm" className="ml-auto" onClick={handleSaveWs} disabled={saving}>
       <Save size={12}/>
       <span className="ml-1">{saving?'保存中...':'保存'}</span>
      </Button>
     )}
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {wsConfig?(
      <div className="grid grid-cols-2 gap-4">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">最大再接続試行回数</label>
        <input
         type="number"
         min={1}
         max={100}
         className="nier-input w-full"
         value={wsConfig.maxReconnectAttempts}
         onChange={(e)=>setWsConfig({...wsConfig,maxReconnectAttempts:parseInt(e.target.value)||10})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">再接続遅延 (ms)</label>
        <input
         type="number"
         min={100}
         step={100}
         className="nier-input w-full"
         value={wsConfig.reconnectDelay}
         onChange={(e)=>setWsConfig({...wsConfig,reconnectDelay:parseInt(e.target.value)||1000})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">最大再接続遅延 (ms)</label>
        <input
         type="number"
         min={1000}
         step={1000}
         className="nier-input w-full"
         value={wsConfig.reconnectDelayMax}
         onChange={(e)=>setWsConfig({...wsConfig,reconnectDelayMax:parseInt(e.target.value)||30000})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">タイムアウト (ms)</label>
        <input
         type="number"
         min={1000}
         step={1000}
         className="nier-input w-full"
         value={wsConfig.timeout}
         onChange={(e)=>setWsConfig({...wsConfig,timeout:parseInt(e.target.value)||20000})}
        />
       </div>
      </div>
     ):(
      <div className="text-nier-text-light">WebSocket設定を取得できませんでした</div>
     )}
    </CardContent>
   </Card>
  </div>
 )
}
