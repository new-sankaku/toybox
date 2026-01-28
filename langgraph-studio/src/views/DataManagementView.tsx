import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{RefreshCw,Trash2,Download,AlertTriangle,RotateCcw,HardDrive,Archive,Activity,Server}from'lucide-react'
import{useDataManagementStore}from'@/stores/dataManagementStore'
import{useProjectStore}from'@/stores/projectStore'
import{useToastStore}from'@/stores/toastStore'
import{archiveApi}from'@/services/apiService'

interface SectionConfig{
 id:string
 label:string
}

const sections:SectionConfig[]=[
 {id:'backup',label:'バックアップ'},
 {id:'archive',label:'アーカイブ'},
 {id:'recovery',label:'リカバリー'},
 {id:'system',label:'システム情報'}
]

function formatSize(bytes:number):string{
 if(bytes>=1024*1024*1024)return`${(bytes/(1024*1024*1024)).toFixed(1)}GB`
 if(bytes>=1024*1024)return`${(bytes/(1024*1024)).toFixed(1)}MB`
 if(bytes>=1024)return`${(bytes/1024).toFixed(1)}KB`
 return`${bytes}B`
}

function formatDate(dateStr:string):string{
 const d=new Date(dateStr)
 return d.toLocaleString('ja-JP',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
}

export default function DataManagementView():JSX.Element{
 const{currentProject}=useProjectStore()
 const addToast=useToastStore(s=>s.addToast)
 const store=useDataManagementStore()
 const[activeSection,setActiveSection]=useState('backup')
 const[confirmDialog,setConfirmDialog]=useState<{type:string;name:string;message:string}|null>(null)
 const[retentionDays,setRetentionDays]=useState(30)

 const loadSectionData=useCallback(()=>{
  switch(activeSection){
   case'backup':
    store.fetchBackups()
    break
   case'archive':
    store.fetchArchives()
    store.fetchArchiveStats(currentProject?.id)
    store.fetchCleanupEstimate(currentProject?.id)
    break
   case'recovery':
    store.fetchRecoveryStatus()
    break
   case'system':
    store.fetchSystemStats()
    break
  }
 },[activeSection,currentProject?.id])

 useEffect(()=>{
  loadSectionData()
 },[loadSectionData])

 const handleCreateBackup=async()=>{
  await store.createBackup()
  addToast('バックアップを作成しました','success')
 }

 const handleRestoreBackup=async(name:string)=>{
  const success=await store.restoreBackup(name)
  if(success){
   addToast('バックアップを復元しました','success')
  }else{
   addToast('バックアップの復元に失敗しました','error')
  }
  setConfirmDialog(null)
 }

 const handleDeleteBackup=async(name:string)=>{
  await store.deleteBackup(name)
  addToast('バックアップを削除しました','success')
  setConfirmDialog(null)
 }

 const handleCleanup=async()=>{
  const deleted=await store.runCleanup(currentProject?.id)
  addToast(`${deleted}件のトレースをクリーンアップしました`,'success')
 }

 const handleExport=async()=>{
  if(!currentProject)return
  const filename=await store.exportArchive(currentProject.id)
  if(filename){
   addToast(`エクスポート完了: ${filename}`,'success')
   await store.fetchArchives()
  }
 }

 const handleExportAndCleanup=async()=>{
  if(!currentProject)return
  const result=await store.exportAndCleanup(currentProject.id)
  if(result){
   addToast(`エクスポート完了: ${result.filename} (${result.deleted}件クリーンアップ)`,'success')
   await store.fetchArchives()
  }
 }

 const handleDeleteArchive=async(name:string)=>{
  await store.deleteArchive(name)
  addToast('アーカイブを削除しました','success')
  setConfirmDialog(null)
 }

 const handleDownloadArchive=(name:string)=>{
  const url=archiveApi.getDownloadUrl(name)
  window.open(url,'_blank')
 }

 const handleRetryAll=async()=>{
  const count=await store.retryAllRecovery()
  addToast(`${count}件のエージェントをリトライしました`,'success')
 }

 const handleSetRetention=async()=>{
  await store.setRetention(retentionDays)
  addToast(`保持期間を${retentionDays}日に設定しました`,'success')
 }

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   <div className="flex-1 flex gap-3 overflow-hidden">
    <div className="w-48 flex-shrink-0 flex flex-col overflow-hidden">
     <Card className="flex flex-col overflow-hidden">
      <CardHeader>
       <DiamondMarker>データ管理</DiamondMarker>
      </CardHeader>
      <CardContent className="p-0">
       <div className="divide-y divide-nier-border-light">
        {sections.map(section=>(
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
       <div className="p-3 border-t border-nier-border-light">
        <Button variant="ghost" size="sm" className="w-full" onClick={loadSectionData}>
         <RefreshCw size={14}/>
         <span className="ml-1">更新</span>
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>

    <div className="flex-1 min-h-0 overflow-y-auto space-y-4">
     {activeSection==='backup'&&(
      <>
       <Card>
        <CardHeader>
         <DiamondMarker><span className="flex items-center gap-2"><HardDrive size={14} className="text-nier-text-light"/>バックアップ</span></DiamondMarker>
         <Button variant="primary" size="sm" className="ml-auto" onClick={handleCreateBackup} disabled={!!store.loading.createBackup}>
          {store.loading.createBackup?'作成中...':'新規作成'}
         </Button>
        </CardHeader>
        <CardContent>
         {store.loading.backups?(
          <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
):store.backups.length===0?(
          <div className="text-center py-8 text-nier-text-light">バックアップがありません</div>
):(
          <div className="divide-y divide-nier-border-light">
           {store.backups.map(backup=>(
            <div key={backup.name} className="flex items-center justify-between py-2 px-1">
             <div className="flex-1 min-w-0">
              <div className="text-nier-small text-nier-text-main truncate">{backup.name}</div>
              <div className="text-nier-caption text-nier-text-light">
               {formatSize(backup.size)}/{formatDate(backup.createdAt)}
              </div>
             </div>
             <div className="flex items-center gap-1 ml-2">
              <Button
               variant="ghost" size="sm"
               onClick={()=>setConfirmDialog({type:'restore',name:backup.name,message:`バックアップ「${backup.name}」を復元しますか？現在のデータは上書きされます。`})}
              >
               <RotateCcw size={12}/>
              </Button>
              <Button
               variant="ghost" size="sm"
               onClick={()=>setConfirmDialog({type:'deleteBackup',name:backup.name,message:`バックアップ「${backup.name}」を削除しますか？`})}
              >
               <Trash2 size={12}/>
              </Button>
             </div>
            </div>
))}
          </div>
)}
        </CardContent>
       </Card>
      </>
)}

     {activeSection==='archive'&&(
      <>
       {store.archiveStats&&(
        <Card>
         <CardHeader>
          <DiamondMarker><span className="flex items-center gap-2"><Archive size={14} className="text-nier-text-light"/>アーカイブ統計</span></DiamondMarker>
         </CardHeader>
         <CardContent>
          <div className="grid grid-cols-2 gap-3 text-nier-small">
           <div>
            <span className="text-nier-text-light">アーカイブ数</span>
            <div className="text-nier-text-main">{store.archiveStats.totalArchives}</div>
           </div>
           <div>
            <span className="text-nier-text-light">合計サイズ</span>
            <div className="text-nier-text-main">{formatSize(store.archiveStats.totalSize)}</div>
           </div>
           <div>
            <span className="text-nier-text-light">最古</span>
            <div className="text-nier-text-main">{store.archiveStats.oldestArchive?formatDate(store.archiveStats.oldestArchive):'-'}</div>
           </div>
           <div>
            <span className="text-nier-text-light">最新</span>
            <div className="text-nier-text-main">{store.archiveStats.newestArchive?formatDate(store.archiveStats.newestArchive):'-'}</div>
           </div>
          </div>
         </CardContent>
        </Card>
)}

       <Card>
        <CardHeader>
         <DiamondMarker>クリーンアップ</DiamondMarker>
        </CardHeader>
        <CardContent>
         <div className="space-y-3">
          {store.cleanupEstimate&&(
           <div className="text-nier-small text-nier-text-light">
            対象: {store.cleanupEstimate.tracesCount}件 ({formatSize(store.cleanupEstimate.estimatedSize)})
           </div>
)}
          <div className="flex items-center gap-2">
           <Button variant="default" size="sm" onClick={handleCleanup} disabled={!!store.loading.cleanup}>
            {store.loading.cleanup?'実行中...':'クリーンアップ実行'}
           </Button>
           {currentProject&&(
            <>
             <Button variant="default" size="sm" onClick={handleExport} disabled={!!store.loading.export}>
              {store.loading.export?'エクスポート中...':'エクスポート'}
             </Button>
             <Button variant="default" size="sm" onClick={handleExportAndCleanup} disabled={!!store.loading.exportCleanup}>
              {store.loading.exportCleanup?'実行中...':'エクスポート&クリーンアップ'}
             </Button>
            </>
)}
          </div>
          <div className="flex items-center gap-2 pt-2 border-t border-nier-border-light">
           <label className="text-nier-small text-nier-text-light">保持期間(日)</label>
           <input
            type="number" min={1} max={365}
            className="w-20 bg-nier-bg-panel border border-nier-border-light px-2 py-1 text-nier-small focus:outline-none focus:border-nier-border-dark"
            value={retentionDays}
            onChange={e=>setRetentionDays(Number(e.target.value))}
           />
           <Button variant="ghost" size="sm" onClick={handleSetRetention} disabled={!!store.loading.retention}>
            設定
           </Button>
          </div>
         </div>
        </CardContent>
       </Card>

       <Card>
        <CardHeader>
         <DiamondMarker>アーカイブ一覧</DiamondMarker>
        </CardHeader>
        <CardContent>
         {store.loading.archives?(
          <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
):store.archives.length===0?(
          <div className="text-center py-8 text-nier-text-light">アーカイブがありません</div>
):(
          <div className="divide-y divide-nier-border-light">
           {store.archives.map(archive=>(
            <div key={archive.name} className="flex items-center justify-between py-2 px-1">
             <div className="flex-1 min-w-0">
              <div className="text-nier-small text-nier-text-main truncate">{archive.name}</div>
              <div className="text-nier-caption text-nier-text-light">
               {formatSize(archive.size)}/{formatDate(archive.createdAt)}
              </div>
             </div>
             <div className="flex items-center gap-1 ml-2">
              <Button variant="ghost" size="sm" onClick={()=>handleDownloadArchive(archive.name)}>
               <Download size={12}/>
              </Button>
              <Button
               variant="ghost" size="sm"
               onClick={()=>setConfirmDialog({type:'deleteArchive',name:archive.name,message:`アーカイブ「${archive.name}」を削除しますか？`})}
              >
               <Trash2 size={12}/>
              </Button>
             </div>
            </div>
))}
          </div>
)}
        </CardContent>
       </Card>
      </>
)}

     {activeSection==='recovery'&&(
      <Card>
       <CardHeader>
        <DiamondMarker><span className="flex items-center gap-2"><Activity size={14} className="text-nier-text-light"/>リカバリー</span></DiamondMarker>
       </CardHeader>
       <CardContent>
        {store.loading.recovery?(
         <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
):store.recoveryStatus?(
         <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-nier-small">
           <div>
            <span className="text-nier-text-light">中断エージェント数</span>
            <div className="text-nier-text-main">{store.recoveryStatus.interruptedAgents}</div>
           </div>
           <div>
            <span className="text-nier-text-light">中断プロジェクト数</span>
            <div className="text-nier-text-main">{store.recoveryStatus.interruptedProjects}</div>
           </div>
          </div>
          <Button
           variant="primary" size="sm"
           onClick={handleRetryAll}
           disabled={!!store.loading.retryAll||store.recoveryStatus.interruptedAgents===0}
          >
           <RotateCcw size={14}/>
           <span className="ml-1">{store.loading.retryAll?'リトライ中...':'全件リトライ'}</span>
          </Button>
         </div>
):(
         <div className="text-center py-8 text-nier-text-light">データなし</div>
)}
       </CardContent>
      </Card>
)}

     {activeSection==='system'&&(
      <Card>
       <CardHeader>
        <DiamondMarker><span className="flex items-center gap-2"><Server size={14} className="text-nier-text-light"/>システム情報</span></DiamondMarker>
       </CardHeader>
       <CardContent>
        {store.loading.system?(
         <div className="text-center py-8 text-nier-text-light">読み込み中...</div>
):store.systemStats?(
         <div className="space-y-4 text-nier-small">
          <div>
           <div className="text-nier-text-light mb-1">バックアップ</div>
           <div className="pl-2 space-y-0.5">
            <div className="flex justify-between">
             <span className="text-nier-text-light">件数</span>
             <span className="text-nier-text-main">{store.systemStats.backups.count}</span>
            </div>
            <div className="flex justify-between">
             <span className="text-nier-text-light">合計サイズ</span>
             <span className="text-nier-text-main">{formatSize(store.systemStats.backups.totalSize)}</span>
            </div>
           </div>
          </div>
          <div className="border-t border-nier-border-light pt-3">
           <div className="text-nier-text-light mb-1">アーカイブ</div>
           <div className="pl-2 space-y-0.5">
            <div className="flex justify-between">
             <span className="text-nier-text-light">件数</span>
             <span className="text-nier-text-main">{store.systemStats.archives.totalArchives}</span>
            </div>
            <div className="flex justify-between">
             <span className="text-nier-text-light">合計サイズ</span>
             <span className="text-nier-text-main">{formatSize(store.systemStats.archives.totalSize)}</span>
            </div>
           </div>
          </div>
          <div className="border-t border-nier-border-light pt-3">
           <div className="text-nier-text-light mb-1">レートリミッター</div>
           <div className="pl-2">
            <div className="flex justify-between">
             <span className="text-nier-text-light">アクティブキー数</span>
             <span className="text-nier-text-main">{store.systemStats.rateLimiter.activeKeys}</span>
            </div>
           </div>
          </div>
         </div>
):(
         <div className="text-center py-8 text-nier-text-light">データなし</div>
)}
       </CardContent>
      </Card>
)}

     {store.error&&(
      <div className="px-3 py-2 border border-nier-accent-red text-nier-accent-red text-nier-small">
       {store.error}
      </div>
)}
    </div>
   </div>

   {confirmDialog&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-[90vw] md:max-w-sm lg:max-w-md">
      <CardHeader>
       <div className="flex items-center gap-2 text-nier-text-main">
        <AlertTriangle size={18}/>
        <span>確認</span>
       </div>
      </CardHeader>
      <CardContent>
       <p className="text-nier-body mb-6">{confirmDialog.message}</p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setConfirmDialog(null)}>
         キャンセル
        </Button>
        <Button
         variant="danger"
         onClick={()=>{
          if(confirmDialog.type==='restore')handleRestoreBackup(confirmDialog.name)
          else if(confirmDialog.type==='deleteBackup')handleDeleteBackup(confirmDialog.name)
          else if(confirmDialog.type==='deleteArchive')handleDeleteArchive(confirmDialog.name)
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
