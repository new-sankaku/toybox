import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{RefreshCw,Activity,ExternalLink,RotateCcw,HardDrive,Archive}from'lucide-react'
import{useDataManagementStore}from'@/stores/dataManagementStore'
import{useToastStore}from'@/stores/toastStore'

interface SectionConfig{
 id:string
 label:string
}

const sections:SectionConfig[]=[
 {id:'recovery',label:'リカバリー'},
 {id:'admin',label:'管理機能'}
]

export default function DataManagementView():JSX.Element{
 const addToast=useToastStore(s=>s.addToast)
 const store=useDataManagementStore()
 const[activeSection,setActiveSection]=useState('recovery')

 const loadSectionData=useCallback(()=>{
  if(activeSection==='recovery'){
   store.fetchRecoveryStatus()
  }
 },[activeSection])

 useEffect(()=>{
  loadSectionData()
 },[loadSectionData])

 const handleRetryAll=async()=>{
  const count=await store.retryAllRecovery()
  addToast(`${count}件のエージェントをリトライしました`,'success')
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

     {activeSection==='admin'&&(
      <div className="space-y-4">
       <Card>
        <CardHeader>
         <DiamondMarker>管理機能</DiamondMarker>
        </CardHeader>
        <CardContent>
         <div className="space-y-4">
          <div className="flex items-center gap-2 px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-small">
           <ExternalLink size={14} className="text-nier-accent-blue flex-shrink-0"/>
           <span className="text-nier-text-main">
            バックアップ・アーカイブ・システム管理はAdmin Consoleで操作してください
           </span>
          </div>
          <div className="grid grid-cols-2 gap-3">
           <div className="flex items-center gap-2 px-3 py-3 border border-nier-border-light text-nier-small">
            <HardDrive size={14} className="text-nier-text-light"/>
            <span className="text-nier-text-light">バックアップ管理</span>
           </div>
           <div className="flex items-center gap-2 px-3 py-3 border border-nier-border-light text-nier-small">
            <Archive size={14} className="text-nier-text-light"/>
            <span className="text-nier-text-light">アーカイブ管理</span>
           </div>
          </div>
         </div>
        </CardContent>
       </Card>
      </div>
     )}

     {store.error&&(
      <div className="px-3 py-2 border border-nier-accent-red text-nier-accent-red text-nier-small">
       {store.error}
      </div>
     )}
    </div>
   </div>
  </div>
 )
}
