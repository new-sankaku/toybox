import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Eye,EyeOff,RefreshCw,AlertTriangle,Key,CheckCircle,XCircle,Save}from'lucide-react'
import{
 apiKeyApi,aiProviderApi,
 type ApiKeyInfo,type AIProviderInfo,type AIServiceTypesInfo
}from'@/services/apiService'

export function ApiKeyManagement():JSX.Element{
 const[keys,setKeys]=useState<ApiKeyInfo[]>([])
 const[providers,setProviders]=useState<AIProviderInfo[]>([])
 const[serviceTypesInfo,setServiceTypesInfo]=useState<AIServiceTypesInfo|null>(null)
 const[loading,setLoading]=useState(true)
 const[editingKey,setEditingKey]=useState<Record<string,string>>({})
 const[showKey,setShowKey]=useState<Record<string,boolean>>({})
 const[validating,setValidating]=useState<Record<string,boolean>>({})
 const[saving,setSaving]=useState(false)
 const[confirmDelete,setConfirmDelete]=useState<string|null>(null)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 const fetchData=useCallback(async()=>{
  setLoading(true)
  try{
   const[keyData,providerData,typesData]=await Promise.all([
    apiKeyApi.list(),
    aiProviderApi.list(),
    aiProviderApi.getServiceTypes()
])
   setKeys(keyData)
   setProviders(providerData)
   setServiceTypesInfo(typesData)
  }catch(e){
   console.error('Failed to fetch:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{fetchData()},[fetchData])

 const showMsg=(text:string,type:'success'|'error')=>{
  setMessage({text,type})
  setTimeout(()=>setMessage(null),3000)
 }

 const getKeyInfo=(pid:string)=>keys.find(k=>k.providerId===pid)

 const handleSaveAll=async()=>{
  const keysToSave=Object.entries(editingKey).filter(([,val])=>val.trim()!=='')
  if(keysToSave.length===0)return
  setSaving(true)
  try{
   for(const[pid,val]of keysToSave){
    await apiKeyApi.save(pid,val)
   }
   setEditingKey({})
   showMsg(`${keysToSave.length}件のAPIキーを保存しました`,'success')
   await fetchData()
  }catch{
   showMsg('保存に失敗しました','error')
  }finally{
   setSaving(false)
  }
 }

 const handleValidate=async(pid:string)=>{
  setValidating(p=>({...p,[pid]:true}))
  try{
   const r=await apiKeyApi.validate(pid)
   showMsg(r.success?`検証成功 (${r.latencyMs}ms)`:`検証失敗: ${r.message}`,r.success?'success':'error')
   await fetchData()
  }catch{
   showMsg('検証に失敗しました','error')
  }finally{
   setValidating(p=>({...p,[pid]:false}))
  }
 }

 const handleDelete=async(pid:string)=>{
  try{
   await apiKeyApi.delete(pid)
   showMsg('APIキーを削除しました','success')
   setConfirmDelete(null)
   await fetchData()
  }catch{
   showMsg('削除に失敗しました','error')
  }
 }

 const groupedProviders=useCallback(()=>{
  if(!serviceTypesInfo)return{}
  const groups:Record<string,AIProviderInfo[]>={}
  for(const t of serviceTypesInfo.types){
   groups[t]=[]
  }
  for(const p of providers){
   const types=p.serviceTypes||[]
   if(types.length>0){
    const primary=types[0]
    if(!groups[primary])groups[primary]=[]
    groups[primary].push(p)
   }
  }
  return groups
 },[providers,serviceTypesInfo])

 const hasChanges=Object.values(editingKey).some(v=>v.trim()!=='')

 if(loading){
  return<div className="nier-surface-panel text-center py-8">読み込み中...</div>
 }

 const groups=groupedProviders()

 const renderProviderRow=(provider:AIProviderInfo)=>{
  const keyInfo=getKeyInfo(provider.id)
  return(
   <div key={provider.id} className="grid grid-cols-[minmax(100px,140px)_1fr_auto] gap-2 items-center py-2 border-b border-nier-border-light last:border-b-0">
    <div className="flex items-center gap-1 min-w-0">
     <span className="text-nier-small truncate">{provider.name}</span>
     {keyInfo&&(
      keyInfo.validated
       ?<CheckCircle size={12} className="text-nier-accent-green flex-shrink-0"/>
       :<XCircle size={12} className="text-nier-text-light flex-shrink-0"/>
)}
    </div>
    <div className="flex items-center gap-1 min-w-0">
     <input
      type={showKey[provider.id]?'text':'password'}
      className="nier-input flex-1 min-w-0"
      placeholder={keyInfo?keyInfo.hint:'APIキーを入力...'}
      value={editingKey[provider.id]||''}
      onChange={e=>setEditingKey(p=>({...p,[provider.id]:e.target.value}))}
     />
     <button
      className="p-1 nier-surface-main border border-nier-border-light hover:bg-nier-bg-selected transition-colors flex-shrink-0"
      onClick={()=>setShowKey(p=>({...p,[provider.id]:!p[provider.id]}))}
     >
      {showKey[provider.id]?<EyeOff size={14}/>:<Eye size={14}/>}
     </button>
    </div>
    <Button
     variant="ghost" size="sm"
     onClick={()=>handleValidate(provider.id)}
     disabled={!keyInfo||!!validating[provider.id]}
     className="flex-shrink-0"
    >
     <RefreshCw size={12} className={validating[provider.id]?'animate-spin':''}/>
     <span className="ml-1 hidden sm:inline">{validating[provider.id]?'検証中':'検証'}</span>
    </Button>
   </div>
)
 }

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <Key size={16}/>
     <span className="text-nier-small font-medium">AI APIキー管理</span>
     <span className="text-nier-caption opacity-60 ml-2">全プロジェクト共通</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     <div className="text-nier-small text-nier-text-light">
      {keys.filter(k=>k.validated).length}/{providers.length} プロバイダーのキーが検証済み
     </div>
    </CardContent>
   </Card>

   {message&&(
    <div className={cn(
     'px-4 py-2 text-nier-small border',
     message.type==='success'?'border-nier-accent-green text-nier-accent-green':'border-nier-accent-red text-nier-accent-red'
)}>
     {message.text}
    </div>
)}

   {serviceTypesInfo?.types.map(serviceType=>{
    const providersInGroup=groups[serviceType]||[]
    if(providersInGroup.length===0)return null
    const label=serviceTypesInfo.labels[serviceType]||serviceType
    const half=Math.ceil(providersInGroup.length/2)
    const leftColumn=providersInGroup.slice(0,half)
    const rightColumn=providersInGroup.slice(half)
    const maxRows=Math.max(leftColumn.length,rightColumn.length)
    return(
     <Card key={serviceType}>
      <CardHeader>
       <span className="text-nier-small font-medium">{label}</span>
      </CardHeader>
      <CardContent className="border-t border-nier-border-light">
       <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-6">
        <div>
         {Array.from({length:maxRows}).map((_,i)=>{
          const p=leftColumn[i]
          if(!p)return<div key={`left-empty-${i}`} className="py-2 border-b border-transparent last:border-b-0">&nbsp;</div>
          return renderProviderRow(p)
         })}
        </div>
        <div className="border-l border-nier-border-light pl-6 hidden lg:block">
         {Array.from({length:maxRows}).map((_,i)=>{
          const p=rightColumn[i]
          if(!p)return<div key={`right-empty-${i}`} className="py-2 border-b border-transparent last:border-b-0">&nbsp;</div>
          return renderProviderRow(p)
         })}
        </div>
        <div className="lg:hidden">
         {rightColumn.map(p=>renderProviderRow(p))}
        </div>
       </div>
      </CardContent>
     </Card>
)
   })}

   {hasChanges&&(
    <div className="flex justify-end">
     <Button variant="primary" onClick={handleSaveAll} disabled={saving}>
      <Save size={14}/>
      <span className="ml-1">{saving?'保存中...':'APIキーを保存'}</span>
     </Button>
    </div>
)}

   {confirmDelete&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-sm">
      <CardHeader>
       <AlertTriangle size={18}/>
       <span>APIキー削除の確認</span>
      </CardHeader>
      <CardContent className="border-t border-nier-border-light">
       <p className="text-nier-body mb-6">このプロバイダーのAPIキーを削除しますか？</p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setConfirmDelete(null)}>キャンセル</Button>
        <Button variant="danger" onClick={()=>handleDelete(confirmDelete)}>削除する</Button>
       </div>
      </CardContent>
     </Card>
    </div>
)}
  </div>
)
}
