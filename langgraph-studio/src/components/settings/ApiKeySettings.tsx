import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Eye,EyeOff,RefreshCw,Trash2,CheckCircle,XCircle,AlertTriangle}from'lucide-react'
import{apiKeyApi,aiProviderApi,type ApiKeyInfo,type AIProviderInfo}from'@/services/apiService'
import{useToastStore}from'@/stores/toastStore'

interface ApiKeySettingsProps{
 projectId:string
}

export function ApiKeySettings({projectId}:ApiKeySettingsProps):JSX.Element{
 const addToast=useToastStore(s=>s.addToast)
 const[keys,setKeys]=useState<ApiKeyInfo[]>([])
 const[providers,setProviders]=useState<AIProviderInfo[]>([])
 const[loading,setLoading]=useState(true)
 const[editingKey,setEditingKey]=useState<Record<string,string>>({})
 const[showKey,setShowKey]=useState<Record<string,boolean>>({})
 const[validating,setValidating]=useState<Record<string,boolean>>({})
 const[saving,setSaving]=useState<Record<string,boolean>>({})
 const[confirmDelete,setConfirmDelete]=useState<string|null>(null)

 const fetchData=useCallback(async()=>{
  setLoading(true)
  try{
   const[keyData,providerData]=await Promise.all([
    apiKeyApi.list(),
    aiProviderApi.list()
])
   setKeys(keyData)
   setProviders(providerData)
  }catch(e){
   console.error('Failed to fetch API key data:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{
  fetchData()
 },[fetchData])

 const getKeyInfo=(providerId:string):ApiKeyInfo|undefined=>{
  return keys.find(k=>k.providerId===providerId)
 }

 const handleSave=async(providerId:string)=>{
  const value=editingKey[providerId]
  if(!value)return
  setSaving(prev=>({...prev,[providerId]:true}))
  try{
   await apiKeyApi.save(providerId,value)
   setEditingKey(prev=>{const n={...prev};delete n[providerId];return n})
   addToast('APIキーを保存しました','success')
   await fetchData()
  }catch{
   addToast('APIキーの保存に失敗しました','error')
  }finally{
   setSaving(prev=>({...prev,[providerId]:false}))
  }
 }

 const handleValidate=async(providerId:string)=>{
  setValidating(prev=>({...prev,[providerId]:true}))
  try{
   const result=await apiKeyApi.validate(providerId)
   if(result.success){
    addToast(`検証成功 (${result.latencyMs}ms)`,'success')
   }else{
    addToast(`検証失敗: ${result.message}`,'error')
   }
   await fetchData()
  }catch{
   addToast('検証に失敗しました','error')
  }finally{
   setValidating(prev=>({...prev,[providerId]:false}))
  }
 }

 const handleDelete=async(providerId:string)=>{
  try{
   await apiKeyApi.delete(providerId)
   addToast('APIキーを削除しました','success')
   setConfirmDelete(null)
   await fetchData()
  }catch{
   addToast('APIキーの削除に失敗しました','error')
  }
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
     <DiamondMarker>APIキー管理</DiamondMarker>
    </CardHeader>
    <CardContent>
     <div className="text-nier-small text-nier-text-light">
      {keys.filter(k=>k.validated).length}/{providers.length} プロバイダーのキーが検証済み
     </div>
    </CardContent>
   </Card>

   {providers.map(provider=>{
    const keyInfo=getKeyInfo(provider.id)
    const isEditing=editingKey[provider.id]!==undefined
    return(
     <Card key={provider.id}>
      <CardHeader>
       <div className="flex items-center gap-2">
        <span className="text-nier-small text-nier-text-main">{provider.name}</span>
        {keyInfo&&(
         keyInfo.validated?(
          <CheckCircle size={14} className="text-nier-accent-green"/>
):(
          <XCircle size={14} className="text-nier-text-light"/>
)
)}
       </div>
       <div className="ml-auto flex items-center gap-1">
        {keyInfo&&(
         <>
          <Button
           variant="ghost" size="sm"
           onClick={()=>handleValidate(provider.id)}
           disabled={!!validating[provider.id]}
          >
           <RefreshCw size={12} className={validating[provider.id]?'animate-spin':''}/>
           <span className="ml-1">{validating[provider.id]?'検証中':'検証'}</span>
          </Button>
          <Button
           variant="ghost" size="sm"
           onClick={()=>setConfirmDelete(provider.id)}
          >
           <Trash2 size={12}/>
          </Button>
         </>
)}
       </div>
      </CardHeader>
      <CardContent className="border-t border-nier-border-light">
       <div className="space-y-2">
        {keyInfo&&!isEditing&&(
         <div className="flex items-center gap-2 text-nier-small">
          <span className="text-nier-text-light">キー:</span>
          <span className="text-nier-text-main font-mono">{keyInfo.hint}</span>
          {keyInfo.latencyMs!=null&&(
           <span className="text-nier-caption text-nier-text-light ml-auto">{keyInfo.latencyMs}ms</span>
)}
         </div>
)}
        <div className="flex gap-2">
         <div className="flex-1 flex gap-2">
          <input
           type={showKey[provider.id]?'text':'password'}
           className="flex-1 bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
           placeholder={keyInfo?'新しいキーを入力...':'APIキーを入力...'}
           value={editingKey[provider.id]||''}
           onChange={e=>setEditingKey(prev=>({...prev,[provider.id]:e.target.value}))}
          />
          <button
           className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors"
           onClick={()=>setShowKey(prev=>({...prev,[provider.id]:!prev[provider.id]}))}
          >
           {showKey[provider.id]?<EyeOff size={16}/>:<Eye size={16}/>}
          </button>
         </div>
         <Button
          variant="primary" size="sm"
          onClick={()=>handleSave(provider.id)}
          disabled={!editingKey[provider.id]||!!saving[provider.id]}
         >
          {saving[provider.id]?'保存中...':'保存'}
         </Button>
        </div>
       </div>
      </CardContent>
     </Card>
)
   })}

   {confirmDelete&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-[90vw] md:max-w-sm lg:max-w-md">
      <CardHeader>
       <div className="flex items-center gap-2 text-nier-text-main">
        <AlertTriangle size={18}/>
        <span>APIキー削除の確認</span>
       </div>
      </CardHeader>
      <CardContent>
       <p className="text-nier-body mb-6">
        このプロバイダーのAPIキーを削除しますか？
       </p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setConfirmDelete(null)}>
         キャンセル
        </Button>
        <Button variant="danger" onClick={()=>handleDelete(confirmDelete)}>
         削除する
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>
)}
  </div>
)
}
