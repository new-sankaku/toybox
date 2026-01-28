import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{
 Eye,EyeOff,RefreshCw,Trash2,CheckCircle,XCircle,AlertTriangle,
 Key,HardDrive,Archive,RotateCcw,Download,Database,Clock,Save
}from'lucide-react'
import{
 apiKeyApi,aiProviderApi,backupApi,archiveApi,
 type ApiKeyInfo,type AIProviderInfo,type ApiBackupEntry,type ApiArchiveEntry
}from'@/services/apiService'

interface ConfigSection{
 id:string
 label:string
}

const configSections:ConfigSection[]=[
 {id:'api-keys',label:'APIキー管理'},
 {id:'data-management',label:'データ管理'}
]

function formatSize(bytes:number):string{
 if(bytes<1024)return`${bytes} B`
 if(bytes<1024*1024)return`${(bytes/1024).toFixed(1)} KB`
 if(bytes<1024*1024*1024)return`${(bytes/(1024*1024)).toFixed(1)} MB`
 return`${(bytes/(1024*1024*1024)).toFixed(1)} GB`
}

function formatDate(dateStr:string):string{
 return new Date(dateStr).toLocaleString('ja-JP')
}

function ApiKeyManagement():JSX.Element{
 const[keys,setKeys]=useState<ApiKeyInfo[]>([])
 const[providers,setProviders]=useState<AIProviderInfo[]>([])
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
    aiProviderApi.list()
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

 const showMsg=(text:string,type:'success'|'error')=>{
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
   showMsg('APIキーを保存しました','success')
   await fetchData()
  }catch{
   showMsg('保存に失敗しました','error')
  }finally{
   setSaving(p=>({...p,[pid]:false}))
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

 if(loading){
  return<div className="text-center py-8 text-nier-text-light">読み込み中...</div>
 }

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <Key size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">APIキー管理</span>
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
          <Save size={12}/>
          <span className="ml-1">{saving[provider.id]?'保存中...':'保存'}</span>
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

interface DataStats{
 total:{traces:number;agent_logs:number;system_logs:number}
 older_than_retention:{traces:number;agent_logs:number;system_logs:number}
 retention_days:number
 cutoff_date:string
}

function DataManagement():JSX.Element{
 const[backups,setBackups]=useState<ApiBackupEntry[]>([])
 const[archives,setArchives]=useState<ApiArchiveEntry[]>([])
 const[stats,setStats]=useState<DataStats|null>(null)
 const[loading,setLoading]=useState(true)
 const[creating,setCreating]=useState(false)
 const[retentionDays,setRetentionDays]=useState(30)
 const[operating,setOperating]=useState<string|null>(null)
 const[confirmDialog,setConfirmDialog]=useState<{type:'restore'|'delete-backup'|'delete-archive'|'cleanup';name?:string}|null>(null)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 const fetchAll=useCallback(async()=>{
  setLoading(true)
  try{
   const[backupData,archiveData,statsData]=await Promise.all([
    backupApi.list(),
    archiveApi.list(),
    archiveApi.getStats()
   ])
   setBackups(backupData)
   setArchives(archiveData)
   if(statsData){
    setStats(statsData as unknown as DataStats)
   }
  }catch(e){
   console.error('Failed to fetch data:',e)
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{fetchAll()},[fetchAll])

 const showMsg=(text:string,type:'success'|'error')=>{
  setMessage({text,type})
  setTimeout(()=>setMessage(null),3000)
 }

 const handleCreateBackup=async()=>{
  setCreating(true)
  try{
   await backupApi.create()
   showMsg('バックアップを作成しました','success')
   await fetchAll()
  }catch{
   showMsg('バックアップの作成に失敗しました','error')
  }finally{
   setCreating(false)
  }
 }

 const handleRestoreBackup=async(name:string)=>{
  try{
   await backupApi.restore(name)
   showMsg('バックアップを復元しました','success')
   setConfirmDialog(null)
  }catch{
   showMsg('復元に失敗しました','error')
  }
 }

 const handleDeleteBackup=async(name:string)=>{
  try{
   await backupApi.delete(name)
   showMsg('バックアップを削除しました','success')
   setConfirmDialog(null)
   await fetchAll()
  }catch{
   showMsg('削除に失敗しました','error')
  }
 }

 const handleDeleteArchive=async(name:string)=>{
  try{
   await archiveApi.delete(name)
   showMsg('アーカイブを削除しました','success')
   setConfirmDialog(null)
   await fetchAll()
  }catch{
   showMsg('削除に失敗しました','error')
  }
 }

 const handleCleanup=async()=>{
  setConfirmDialog(null)
  setOperating('cleanup')
  try{
   const r=await archiveApi.cleanup()
   showMsg(`${r.deleted}件のデータをクリーンアップしました`,'success')
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
   await fetchAll()
  }catch{
   showMsg('設定に失敗しました','error')
  }finally{
   setOperating(null)
  }
 }

 const handleDownloadArchive=(name:string)=>{
  const url=archiveApi.getDownloadUrl(name)
  const a=document.createElement('a')
  a.href=url
  a.download=name
  a.click()
 }

 if(loading){
  return<div className="text-center py-8 text-nier-text-light">読み込み中...</div>
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
     <HardDrive size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">バックアップ管理</span>
     <Button variant="primary" size="sm" className="ml-auto" onClick={handleCreateBackup} disabled={creating}>
      {creating?'作成中...':'新規作成'}
     </Button>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {backups.length===0?(
      <div className="text-center py-4 text-nier-text-light">バックアップがありません</div>
     ):(
      <div className="divide-y divide-nier-border-light">
       {backups.map(b=>(
        <div key={b.name} className="flex items-center justify-between py-3">
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
          <Button variant="ghost" size="sm" onClick={()=>setConfirmDialog({type:'delete-backup',name:b.name})}>
           <Trash2 size={12}/>
          </Button>
         </div>
        </div>
       ))}
      </div>
     )}
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <Clock size={14} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">クリーンアップ</span>
     <span className="text-nier-caption text-nier-text-light ml-2">保持期間より古いデータを削除</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light space-y-4">
     <div className="flex items-center gap-3">
      <label className="text-nier-small text-nier-text-light">保持期間</label>
      <input
       type="number" min={1} max={365}
       className="w-20 bg-nier-bg-main border border-nier-border-light px-2 py-1 text-nier-small focus:outline-none focus:border-nier-border-dark"
       value={retentionDays}
       onChange={e=>setRetentionDays(Number(e.target.value))}
      />
      <span className="text-nier-small text-nier-text-light">日</span>
      <Button variant="ghost" size="sm" onClick={handleSetRetention} disabled={operating==='retention'}>
       {operating==='retention'?'設定中...':'設定'}
      </Button>
     </div>
     {stats&&(
      <div className="bg-nier-bg-main p-3 border border-nier-border-light">
       <div className="text-nier-small text-nier-text-light mb-2">
        削除対象（{stats.retention_days||retentionDays}日より古いデータ）:
       </div>
       <div className="grid grid-cols-3 gap-3 text-nier-small">
        <div>
         <span className="text-nier-text-light">トレース</span>
         <div className={cn("font-mono",stats.older_than_retention?.traces>0?"text-nier-accent-orange":"text-nier-text-main")}>
          {stats.older_than_retention?.traces?.toLocaleString()||0}件
         </div>
        </div>
        <div>
         <span className="text-nier-text-light">エージェントログ</span>
         <div className={cn("font-mono",stats.older_than_retention?.agent_logs>0?"text-nier-accent-orange":"text-nier-text-main")}>
          {stats.older_than_retention?.agent_logs?.toLocaleString()||0}件
         </div>
        </div>
        <div>
         <span className="text-nier-text-light">システムログ</span>
         <div className={cn("font-mono",stats.older_than_retention?.system_logs>0?"text-nier-accent-orange":"text-nier-text-main")}>
          {stats.older_than_retention?.system_logs?.toLocaleString()||0}件
         </div>
        </div>
       </div>
      </div>
     )}
     <Button
      variant="default" size="sm"
      onClick={()=>setConfirmDialog({type:'cleanup'})}
      disabled={operating==='cleanup'}
     >
      {operating==='cleanup'?'実行中...':'クリーンアップ実行'}
     </Button>
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <Archive size={16} className="text-nier-text-light"/>
     <span className="text-nier-small font-medium">アーカイブ一覧</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     {archives.length===0?(
      <div className="text-center py-4 text-nier-text-light">アーカイブがありません</div>
     ):(
      <div className="divide-y divide-nier-border-light">
       {archives.map(a=>(
        <div key={a.name} className="flex items-center justify-between py-3">
         <div className="flex-1 min-w-0">
          <div className="text-nier-small text-nier-text-main truncate">{a.name}</div>
          <div className="text-nier-caption text-nier-text-light">
           {formatSize(a.size)} / {formatDate(a.createdAt)}
          </div>
         </div>
         <div className="flex items-center gap-1 ml-2">
          <Button variant="ghost" size="sm" onClick={()=>handleDownloadArchive(a.name)}>
           <Download size={12}/>
          </Button>
          <Button variant="ghost" size="sm" onClick={()=>setConfirmDialog({type:'delete-archive',name:a.name})}>
           <Trash2 size={12}/>
          </Button>
         </div>
        </div>
       ))}
      </div>
     )}
    </CardContent>
   </Card>

   {stats&&(
    <Card>
     <CardHeader>
      <Database size={14} className="text-nier-text-light"/>
      <span className="text-nier-small font-medium">データ統計</span>
     </CardHeader>
     <CardContent className="border-t border-nier-border-light">
      <div className="grid grid-cols-3 gap-4 text-nier-small">
       <div>
        <span className="text-nier-text-light">トレース</span>
        <div className="text-nier-text-main font-mono">{stats.total?.traces?.toLocaleString()||0}</div>
       </div>
       <div>
        <span className="text-nier-text-light">エージェントログ</span>
        <div className="text-nier-text-main font-mono">{stats.total?.agent_logs?.toLocaleString()||0}</div>
       </div>
       <div>
        <span className="text-nier-text-light">システムログ</span>
        <div className="text-nier-text-main font-mono">{stats.total?.system_logs?.toLocaleString()||0}</div>
       </div>
      </div>
     </CardContent>
    </Card>
   )}

   {confirmDialog&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-md">
      <CardHeader>
       <AlertTriangle size={18} className="text-nier-accent-orange"/>
       <span>
        {confirmDialog.type==='restore'&&'復元の確認'}
        {confirmDialog.type==='delete-backup'&&'バックアップ削除の確認'}
        {confirmDialog.type==='delete-archive'&&'アーカイブ削除の確認'}
        {confirmDialog.type==='cleanup'&&'クリーンアップの確認'}
       </span>
      </CardHeader>
      <CardContent className="border-t border-nier-border-light">
       <p className="text-nier-body mb-6">
        {confirmDialog.type==='restore'&&`バックアップ「${confirmDialog.name}」を復元しますか？現在のデータは上書きされます。`}
        {confirmDialog.type==='delete-backup'&&`バックアップ「${confirmDialog.name}」を削除しますか？`}
        {confirmDialog.type==='delete-archive'&&`アーカイブ「${confirmDialog.name}」を削除しますか？`}
        {confirmDialog.type==='cleanup'&&'保持期間より古いデータを完全に削除します。この操作は取り消せません。'}
       </p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setConfirmDialog(null)}>キャンセル</Button>
        <Button
         variant="danger"
         onClick={()=>{
          if(confirmDialog.type==='restore'&&confirmDialog.name)handleRestoreBackup(confirmDialog.name)
          else if(confirmDialog.type==='delete-backup'&&confirmDialog.name)handleDeleteBackup(confirmDialog.name)
          else if(confirmDialog.type==='delete-archive'&&confirmDialog.name)handleDeleteArchive(confirmDialog.name)
          else if(confirmDialog.type==='cleanup')handleCleanup()
         }}
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

export default function GlobalConfigView():JSX.Element{
 const[activeSection,setActiveSection]=useState('api-keys')

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   <div className="flex-1 flex gap-3 overflow-hidden">
    <div className="w-48 flex-shrink-0 flex flex-col overflow-hidden">
     <Card className="flex flex-col overflow-hidden">
      <CardHeader>
       <DiamondMarker>共通設定</DiamondMarker>
      </CardHeader>
      <CardContent className="p-0">
       <div className="divide-y divide-nier-border-light">
        {configSections.map(section=>(
         <button
          key={section.id}
          className={cn(
           'w-full px-4 py-3 text-left text-nier-small tracking-nier transition-colors',
           activeSection===section.id
            ?'bg-nier-bg-selected text-nier-text-main'
            :'text-nier-text-light hover:bg-nier-bg-panel'
          )}
          onClick={()=>setActiveSection(section.id)}
         >
          {section.label}
         </button>
        ))}
       </div>
      </CardContent>
     </Card>
    </div>

    <div className="flex-1 min-h-0 overflow-y-auto">
     {activeSection==='api-keys'&&<ApiKeyManagement/>}
     {activeSection==='data-management'&&<DataManagement/>}
    </div>
   </div>
  </div>
 )
}
