import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{formatSize,formatDate}from'@/lib/utils'
import{HardDrive,RotateCcw,Trash2,AlertTriangle}from'lucide-react'
import{backupApi,type BackupInfo}from'@/services/adminApi'

export function BackupPage(){
 const[backups,setBackups]=useState<BackupInfo[]>([])
 const[loading,setLoading]=useState(true)
 const[creating,setCreating]=useState(false)
 const[confirmDialog,setConfirmDialog]=useState<{type:'restore'|'delete';name:string}|null>(null)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 const fetchBackups=useCallback(async()=>{
  setLoading(true)
  try{
   const result=await backupApi.list()
   setBackups(result.backups)
  }catch(e){
   console.error('Failed to fetch backups:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{fetchBackups()},[fetchBackups])

 const showMsg=(text:string,type:'success'|'error')=>{
  setMessage({text,type})
  setTimeout(()=>setMessage(null),3000)
 }

 const handleCreate=async()=>{
  setCreating(true)
  try{
   await backupApi.create()
   showMsg('バックアップを作成しました','success')
   await fetchBackups()
  }catch{
   showMsg('バックアップの作成に失敗しました','error')
  }finally{
   setCreating(false)
  }
 }

 const handleRestore=async(name:string)=>{
  try{
   await backupApi.restore(name)
   showMsg('バックアップを復元しました','success')
   setConfirmDialog(null)
  }catch{
   showMsg('復元に失敗しました','error')
  }
 }

 const handleDelete=async(name:string)=>{
  try{
   await backupApi.delete(name)
   showMsg('バックアップを削除しました','success')
   setConfirmDialog(null)
   await fetchBackups()
  }catch{
   showMsg('削除に失敗しました','error')
  }
 }

 return(
  <div className="space-y-4 animate-fade-in">
   <Card>
    <CardHeader>
     <HardDrive size={16} className="text-nier-text-light"/>
     <span className="text-nier-h2">バックアップ管理</span>
     <Button variant="primary" size="sm" className="ml-auto" onClick={handleCreate} disabled={creating}>
      {creating?'作成中...':'新規作成'}
     </Button>
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

   <Card>
    <CardContent>
     {loading?(
      <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
     ):backups.length===0?(
      <div className="text-center py-8 text-nier-text-light">バックアップがありません</div>
     ):(
      <div className="divide-y divide-nier-border-light">
       {backups.map(b=>(
        <div key={b.name} className="flex items-center justify-between py-3 px-1">
         <div className="flex-1 min-w-0">
          <div className="text-nier-small text-nier-text-main truncate">{b.name}</div>
          <div className="text-nier-caption text-nier-text-light">
           {formatSize(b.size)} / {formatDate(b.createdAt)}
          </div>
         </div>
         <div className="flex items-center gap-1 ml-2">
          <Button variant="ghost" size="sm" onClick={()=>setConfirmDialog({type:'restore',name:b.name})}>
           <RotateCcw size={12}/>
           <span className="ml-1">復元</span>
          </Button>
          <Button variant="ghost" size="sm" onClick={()=>setConfirmDialog({type:'delete',name:b.name})}>
           <Trash2 size={12}/>
          </Button>
         </div>
        </div>
       ))}
      </div>
     )}
    </CardContent>
   </Card>

   {confirmDialog&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-sm">
      <CardHeader>
       <AlertTriangle size={18}/>
       <span>{confirmDialog.type==='restore'?'復元の確認':'削除の確認'}</span>
      </CardHeader>
      <CardContent className="border-t border-nier-border-light">
       <p className="text-nier-body mb-6">
        {confirmDialog.type==='restore'
         ?`バックアップ「${confirmDialog.name}」を復元しますか？現在のデータは上書きされます。`
         :`バックアップ「${confirmDialog.name}」を削除しますか？`}
       </p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setConfirmDialog(null)}>キャンセル</Button>
        <Button
         variant="danger"
         onClick={()=>confirmDialog.type==='restore'?handleRestore(confirmDialog.name):handleDelete(confirmDialog.name)}
        >
         {confirmDialog.type==='restore'?'復元する':'削除する'}
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>
   )}
  </div>
 )
}
