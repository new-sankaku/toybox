import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{formatSize}from'@/lib/utils'
import{Server,RefreshCw,CheckCircle,XCircle,Activity}from'lucide-react'
import{systemApi,providerApi}from'@/services/adminApi'

interface SystemStatus{
 database:{size:number;path:string}
 backup_info:Record<string,unknown>
 archive_stats:Record<string,unknown>
 rate_limiter:Record<string,unknown>
}

interface HealthEntry{
 provider_id:string
 display_name:string
 is_healthy:boolean
 last_latency_ms:number|null
 last_checked:string|null
 error_message:string|null
}

export function SystemStatusPage(){
 const[status,setStatus]=useState<SystemStatus|null>(null)
 const[health,setHealth]=useState<HealthEntry[]>([])
 const[loading,setLoading]=useState(true)

 const fetchAll=useCallback(async()=>{
  setLoading(true)
  try{
   const[s,h]=await Promise.all([
    systemApi.status(),
    providerApi.health()
   ])
   setStatus(s)
   setHealth(Array.isArray(h)?h:Object.values(h))
  }catch(e){
   console.error('Failed to fetch system status:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{fetchAll()},[fetchAll])

 if(loading){
  return <div className="text-center py-12 text-nier-text-light">読み込み中...</div>
 }

 return(
  <div className="space-y-4 animate-fade-in">
   <Card>
    <CardHeader>
     <Server size={16} className="text-nier-text-light"/>
     <span className="text-nier-h2">システム情報</span>
     <Button variant="ghost" size="sm" className="ml-auto" onClick={fetchAll}>
      <RefreshCw size={14}/>
      <span className="ml-1">更新</span>
     </Button>
    </CardHeader>
   </Card>

   {status&&(
    <Card>
     <CardHeader><span className="text-nier-small">データベース</span></CardHeader>
     <CardContent className="border-t border-nier-border-light">
      <div className="space-y-2 text-nier-small">
       <div className="flex justify-between">
        <span className="text-nier-text-light">サイズ</span>
        <span className="text-nier-text-main">{formatSize(status.database.size)}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">パス</span>
        <span className="text-nier-text-main font-mono text-nier-caption">{status.database.path}</span>
       </div>
      </div>
     </CardContent>
    </Card>
   )}

   {status&&(
    <Card>
     <CardHeader><span className="text-nier-small">バックアップ / アーカイブ</span></CardHeader>
     <CardContent className="border-t border-nier-border-light">
      <div className="grid grid-cols-2 gap-4 text-nier-small">
       <div>
        <div className="text-nier-text-light mb-1">バックアップ</div>
        <div className="pl-2 space-y-1">
         <div className="flex justify-between">
          <span className="text-nier-text-light">件数</span>
          <span className="text-nier-text-main">{(status.backup_info as Record<string,number>).count??'-'}</span>
         </div>
         <div className="flex justify-between">
          <span className="text-nier-text-light">合計</span>
          <span className="text-nier-text-main">{formatSize((status.backup_info as Record<string,number>).totalSize??0)}</span>
         </div>
        </div>
       </div>
       <div>
        <div className="text-nier-text-light mb-1">アーカイブ</div>
        <div className="pl-2 space-y-1">
         <div className="flex justify-between">
          <span className="text-nier-text-light">件数</span>
          <span className="text-nier-text-main">{(status.archive_stats as Record<string,number>).totalArchives??'-'}</span>
         </div>
         <div className="flex justify-between">
          <span className="text-nier-text-light">合計</span>
          <span className="text-nier-text-main">{formatSize((status.archive_stats as Record<string,number>).totalSize??0)}</span>
         </div>
        </div>
       </div>
      </div>
     </CardContent>
    </Card>
   )}

   <Card>
    <CardHeader>
     <Activity size={16} className="text-nier-text-light"/>
     <span className="text-nier-small">プロバイダーヘルス</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {health.length===0?(
      <div className="text-center py-4 text-nier-text-light text-nier-small">データなし</div>
     ):(
      <div className="divide-y divide-nier-border-light">
       {health.map((h:HealthEntry)=>(
        <div key={h.provider_id} className="flex items-center justify-between py-2">
         <div className="flex items-center gap-2">
          {h.is_healthy
           ?<CheckCircle size={14} className="text-nier-accent-green"/>
           :<XCircle size={14} className="text-nier-accent-red"/>}
          <span className="text-nier-small text-nier-text-main">{h.display_name||h.provider_id}</span>
         </div>
         <div className="text-nier-caption text-nier-text-light">
          {h.last_latency_ms!=null?`${h.last_latency_ms}ms`:'-'}
         </div>
        </div>
       ))}
      </div>
     )}
    </CardContent>
   </Card>
  </div>
 )
}
