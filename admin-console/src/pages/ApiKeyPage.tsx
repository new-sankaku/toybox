import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Eye,EyeOff,RefreshCw,Trash2,CheckCircle,XCircle,AlertTriangle,Key}from'lucide-react'
import{apiKeyApi,providerApi,type ApiKeyInfo,type ProviderInfo}from'@/services/adminApi'

export function ApiKeyPage(){
 const[keys,setKeys]=useState<ApiKeyInfo[]>([])
 const[providers,setProviders]=useState<ProviderInfo[]>([])
 const[loading,setLoading]=useState(true)
 const[editingKey,setEditingKey]=useState<Record<string,string>>({})
 const[showKey,setShowKey]=useState<Record<string,boolean>>({})
 const[validating,setValidating]=useState<Record<string,boolean>>({})
 const[saving,setSaving]=useState<Record<string,boolean>>({})
 const[confirmDelete,setConfirmDelete]=useState<string|null>(null)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 const fetchData=useCallback(async()=>{
  setLoading(true)
  try{
   const[keyData,providerData]=await Promise.all([
    apiKeyApi.list(),
    providerApi.list()
   ])
   setKeys(keyData)
   setProviders(providerData)
  }catch(e){
   console.error('Failed to fetch:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{fetchData()},[fetchData])

 const showMessage=(text:string,type:'success'|'error')=>{
  setMessage({text,type})
  setTimeout(()=>setMessage(null),3000)
 }

 const getKeyInfo=(pid:string)=>keys.find(k=>k.providerId===pid)

 const handleSave=async(pid:string)=>{
  const val=editingKey[pid]
  if(!val)return
  setSaving(p=>({...p,[pid]:true}))
  try{
   await apiKeyApi.save(pid,val)
   setEditingKey(p=>{const n={...p};delete n[pid];return n})
   showMessage('APIキーを保存しました','success')
   await fetchData()
  }catch{
   showMessage('保存に失敗しました','error')
  }finally{
   setSaving(p=>({...p,[pid]:false}))
  }
 }

 const handleValidate=async(pid:string)=>{
  setValidating(p=>({...p,[pid]:true}))
  try{
   const r=await apiKeyApi.validate(pid)
   showMessage(r.success?`検証成功 (${r.latency}ms)`:`検証失敗: ${r.message}`,r.success?'success':'error')
   await fetchData()
  }catch{
   showMessage('検証に失敗しました','error')
  }finally{
   setValidating(p=>({...p,[pid]:false}))
  }
 }

 const handleDelete=async(pid:string)=>{
  try{
   await apiKeyApi.delete(pid)
   showMessage('APIキーを削除しました','success')
   setConfirmDelete(null)
   await fetchData()
  }catch{
   showMessage('削除に失敗しました','error')
  }
 }

 if(loading){
  return <div className="text-center py-12 text-nier-text-light">読み込み中...</div>
 }

 return(
  <div className="space-y-4 animate-fade-in">
   <Card>
    <CardHeader>
     <Key size={16} className="text-nier-text-light"/>
     <span className="text-nier-h2">APIキー管理</span>
     <span className="text-nier-caption text-nier-text-light ml-2">全プロジェクト共通</span>
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

   {providers.map(provider=>{
    const keyInfo=getKeyInfo(provider.id)
    return(
     <Card key={provider.id}>
      <CardHeader>
       <div className="flex items-center gap-2">
        <span className="text-nier-small text-nier-text-main">{provider.name}</span>
        {keyInfo&&(
         keyInfo.validated
          ?<CheckCircle size={14} className="text-nier-accent-green"/>
          :<XCircle size={14} className="text-nier-text-light"/>
        )}
       </div>
       <div className="ml-auto flex items-center gap-1">
        {keyInfo&&(
         <>
          <Button variant="ghost" size="sm" onClick={()=>handleValidate(provider.id)} disabled={!!validating[provider.id]}>
           <RefreshCw size={12} className={validating[provider.id]?'animate-spin':''}/>
           <span className="ml-1">{validating[provider.id]?'検証中':'検証'}</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={()=>setConfirmDelete(provider.id)}>
           <Trash2 size={12}/>
          </Button>
         </>
        )}
       </div>
      </CardHeader>
      <CardContent className="border-t border-nier-border-light">
       <div className="space-y-2">
        {keyInfo&&editingKey[provider.id]===undefined&&(
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
           className="flex-1 bg-nier-bg-main border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
           placeholder={keyInfo?'新しいキーを入力...':'APIキーを入力...'}
           value={editingKey[provider.id]||''}
           onChange={e=>setEditingKey(p=>({...p,[provider.id]:e.target.value}))}
          />
          <button
           className="p-2 bg-nier-bg-main border border-nier-border-light hover:bg-nier-bg-selected transition-colors"
           onClick={()=>setShowKey(p=>({...p,[provider.id]:!p[provider.id]}))}
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
