import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn,formatSize,formatDate}from'@/lib/utils'
import{Archive,Trash2,Download,AlertTriangle}from'lucide-react'
import{archiveApi,type ArchiveInfo}from'@/services/adminApi'

export function ArchivePage(){
 const[archives,setArchives]=useState<ArchiveInfo[]>([])
 const[stats,setStats]=useState<Record<string,unknown>|null>(null)
 const[estimate,setEstimate]=useState<{tracesCount:number;estimatedSize:number}|null>(null)
 const[loading,setLoading]=useState(true)
 const[retentionDays,setRetentionDays]=useState(30)
 const[operating,setOperating]=useState<string|null>(null)
 const[confirmDelete,setConfirmDelete]=useState<string|null>(null)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 const fetchAll=useCallback(async()=>{
  setLoading(true)
  try{
   const[archiveData,statsData,estData]=await Promise.all([
    archiveApi.list(),
    archiveApi.stats(),
    archiveApi.estimate()
   ])
   setArchives(archiveData.archives)
   setStats(statsData)
   setEstimate(estData)
  }catch(e){
   console.error('Failed to fetch archive data:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{fetchAll()},[fetchAll])

 const showMsg=(text:string,type:'success'|'error')=>{
  setMessage({text,type})
  setTimeout(()=>setMessage(null),3000)
 }

 const handleCleanup=async()=>{
  setOperating('cleanup')
  try{
   const r=await archiveApi.cleanup()
   showMsg(`${r.deleted}件のトレースをクリーンアップしました`,'success')
   await fetchAll()
  }catch{
   showMsg('クリーンアップに失敗しました','error')
  }finally{
   setOperating(null)
  }
 }

 const handleSetRetention=async()=>{
  setOperating('retention')
  try{
   await archiveApi.setRetention(retentionDays)
   showMsg(`保持期間を${retentionDays}日に設定しました`,'success')
  }catch{
   showMsg('設定に失敗しました','error')
  }finally{
   setOperating(null)
  }
 }

 const handleDeleteArchive=async(name:string)=>{
  try{
   await archiveApi.delete(name)
   showMsg('アーカイブを削除しました','success')
   setConfirmDelete(null)
   await fetchAll()
  }catch{
   showMsg('削除に失敗しました','error')
  }
 }

 const handleDownload=async(name:string)=>{
  try{
   const token=sessionStorage.getItem('admin_token')||''
   const res=await fetch(archiveApi.getDownloadUrl(name),{
    headers:{'Authorization':`Bearer ${token}`}
   })
   if(!res.ok){
    showMsg('ダウンロードに失敗しました','error')
    return
   }
   const blob=await res.blob()
   const url=URL.createObjectURL(blob)
   const a=document.createElement('a')
   a.href=url
   a.download=name
   a.click()
   URL.revokeObjectURL(url)
  }catch{
   showMsg('ダウンロードに失敗しました','error')
  }
 }

 if(loading){
  return <div className="text-center py-12 text-nier-text-light">読み込み中...</div>
 }

 return(
  <div className="space-y-4 animate-fade-in">
   <Card>
    <CardHeader>
     <Archive size={16} className="text-nier-text-light"/>
     <span className="text-nier-h2">アーカイブ管理</span>
    </CardHeader>
   </Card>

   {message&&(
    <div className={cn(
     'px-4 py-2 text-nier-small border',
     message.type==='success'?'border-nier-accent-green text-nier-accent-green':'border-nier-accent-red text-nier-accent-red'
    )}>
     {message.text}
    </div>
   )}

   {stats&&(
    <Card>
     <CardHeader><span className="text-nier-small">アーカイブ統計</span></CardHeader>
     <CardContent className="border-t border-nier-border-light">
      <div className="grid grid-cols-2 gap-3 text-nier-small">
       <div>
        <span className="text-nier-text-light">アーカイブ数</span>
        <div className="text-nier-text-main">{(stats as Record<string,number>).totalArchives??'-'}</div>
       </div>
       <div>
        <span className="text-nier-text-light">合計サイズ</span>
        <div className="text-nier-text-main">{formatSize((stats as Record<string,number>).totalSize??0)}</div>
       </div>
      </div>
     </CardContent>
    </Card>
   )}

   <Card>
    <CardHeader><span className="text-nier-small">クリーンアップ</span></CardHeader>
    <CardContent className="border-t border-nier-border-light space-y-3">
     {estimate&&(
      <div className="text-nier-small text-nier-text-light">
       対象: {estimate.tracesCount}件 ({formatSize(estimate.estimatedSize)})
      </div>
     )}
     <div className="flex items-center gap-2">
      <Button variant="default" size="sm" onClick={handleCleanup} disabled={operating==='cleanup'}>
       {operating==='cleanup'?'実行中...':'クリーンアップ実行'}
      </Button>
     </div>
     <div className="flex items-center gap-2 pt-2 border-t border-nier-border-light">
      <label className="text-nier-small text-nier-text-light">保持期間(日)</label>
      <input
       type="number" min={1} max={365}
       className="w-20 bg-nier-bg-main border border-nier-border-light px-2 py-1 text-nier-small focus:outline-none focus:border-nier-border-dark"
       value={retentionDays}
       onChange={e=>setRetentionDays(Number(e.target.value))}
      />
      <Button variant="ghost" size="sm" onClick={handleSetRetention} disabled={operating==='retention'}>
       設定
      </Button>
     </div>
    </CardContent>
   </Card>

   <Card>
    <CardHeader><span className="text-nier-small">アーカイブ一覧</span></CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {archives.length===0?(
      <div className="text-center py-8 text-nier-text-light">アーカイブがありません</div>
     ):(
      <div className="divide-y divide-nier-border-light">
       {archives.map(a=>(
        <div key={a.name} className="flex items-center justify-between py-3 px-1">
         <div className="flex-1 min-w-0">
          <div className="text-nier-small text-nier-text-main truncate">{a.name}</div>
          <div className="text-nier-caption text-nier-text-light">
           {formatSize(a.size)} / {formatDate(a.createdAt)}
          </div>
         </div>
         <div className="flex items-center gap-1 ml-2">
          <Button variant="ghost" size="sm" onClick={()=>handleDownload(a.name)}>
           <Download size={12}/>
          </Button>
          <Button variant="ghost" size="sm" onClick={()=>setConfirmDelete(a.name)}>
           <Trash2 size={12}/>
          </Button>
         </div>
        </div>
       ))}
      </div>
     )}
    </CardContent>
   </Card>

   {confirmDelete&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-sm">
      <CardHeader>
       <AlertTriangle size={18}/>
       <span>削除の確認</span>
      </CardHeader>
      <CardContent className="border-t border-nier-border-light">
       <p className="text-nier-body mb-6">アーカイブ「{confirmDelete}」を削除しますか？</p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setConfirmDelete(null)}>キャンセル</Button>
        <Button variant="danger" onClick={()=>handleDeleteArchive(confirmDelete)}>削除する</Button>
       </div>
      </CardContent>
     </Card>
    </div>
   )}
  </div>
 )
}
