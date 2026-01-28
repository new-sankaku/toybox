import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{CheckCircle,XCircle,ExternalLink}from'lucide-react'
import{apiKeyApi,aiProviderApi,type ApiKeyInfo,type AIProviderInfo}from'@/services/apiService'

interface ApiKeySettingsProps{
 projectId:string
}

export function ApiKeySettings({projectId:_projectId}:ApiKeySettingsProps):JSX.Element{
 const[keys,setKeys]=useState<ApiKeyInfo[]>([])
 const[providers,setProviders]=useState<AIProviderInfo[]>([])
 const[loading,setLoading]=useState(true)

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
     <DiamondMarker>APIキー状態</DiamondMarker>
    </CardHeader>
    <CardContent>
     <div className="space-y-3">
      <div className="text-nier-small text-nier-text-light">
       {keys.filter(k=>k.validated).length}/{providers.length} プロバイダーのキーが検証済み
      </div>
      <div className="flex items-center gap-2 px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-small">
       <ExternalLink size={14} className="text-nier-accent-blue flex-shrink-0"/>
       <span className="text-nier-text-main">
        APIキーの登録・削除・検証はAdmin Consoleで管理してください
       </span>
      </div>
     </div>
    </CardContent>
   </Card>

   {providers.map(provider=>{
    const keyInfo=getKeyInfo(provider.id)
    return(
     <Card key={provider.id}>
      <CardHeader>
       <div className="flex items-center gap-2">
        <span className="text-nier-small text-nier-text-main">{provider.name}</span>
        {keyInfo?(
         keyInfo.validated
          ?<CheckCircle size={14} className="text-nier-accent-green"/>
          :<XCircle size={14} className="text-nier-text-light"/>
        ):(
         <span className="text-nier-caption text-nier-text-light">未設定</span>
        )}
       </div>
       {keyInfo&&(
        <div className="ml-auto flex items-center gap-2 text-nier-caption text-nier-text-light">
         <span className="font-mono">{keyInfo.hint}</span>
         {keyInfo.latencyMs!=null&&<span>{keyInfo.latencyMs}ms</span>}
        </div>
       )}
      </CardHeader>
     </Card>
    )
   })}
  </div>
 )
}
