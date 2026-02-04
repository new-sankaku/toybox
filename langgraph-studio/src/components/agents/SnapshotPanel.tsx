import{useState}from'react'
import{RotateCcw,Clock,CheckCircle,ChevronDown,ChevronRight,AlertTriangle}from'lucide-react'
import{cn}from'@/lib/utils'
import{Button}from'@/components/ui/Button'
import type{WorkflowSnapshot}from'@/types/agent'

interface SnapshotPanelProps{
 snapshots:WorkflowSnapshot[]
 onRestore:(snapshotId:string)=>void
 restoring:boolean
}

const stepTypeLabel:Record<string,string>={
 leader_completed:'Leader分析',
 worker_completed:'Worker実行',
 integration_completed:'統合処理',
}

const stepTypeIcon:Record<string,string>={
 leader_completed:'text-nier-accent-blue',
 worker_completed:'text-nier-accent-green',
 integration_completed:'text-nier-accent-orange',
}

const statusStyle:Record<string,string>={
 active:'border-nier-border-light',
 restored:'border-nier-accent-blue',
 invalidated:'border-nier-border-light opacity-40',
}

const formatTime=(timestamp:string)=>{
 const d=new Date(timestamp)
 const mm=String(d.getMonth()+1).padStart(2,'0')
 const dd=String(d.getDate()).padStart(2,'0')
 const time=d.toLocaleTimeString('ja-JP',{
  hour:'2-digit',
  minute:'2-digit',
  second:'2-digit',
 })
 return`${mm}/${dd} ${time}`
}

export function SnapshotPanel({snapshots,onRestore,restoring}:SnapshotPanelProps):JSX.Element{
 const[expandedId,setExpandedId]=useState<string|null>(null)

 if(snapshots.length===0){
  return(
   <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
    スナップショットがありません
   </div>
)
 }

 const grouped:Record<string,WorkflowSnapshot[]>={}
 for(const snap of snapshots){
  const key=snap.workflowRunId
  if(!grouped[key])grouped[key]=[]
  grouped[key].push(snap)
 }

 return(
  <div className="space-y-3">
   {Object.entries(grouped).map(([runId,runSnapshots])=>(
    <div key={runId} className="border border-nier-border-light bg-nier-bg-panel">
     <div className="px-3 py-1.5 nier-surface-header text-nier-caption flex items-center gap-2">
      <Clock size={12}/>
      <span className="flex-1">実行: {runId}</span>
      <span className="opacity-60">{runSnapshots.length}ステップ</span>
     </div>
     <div className="p-2 space-y-1">
      {runSnapshots.map((snap,idx)=>(
       <div
        key={snap.id}
        className={cn(
         'border px-2 py-1.5 transition-colors',
         statusStyle[snap.status]||statusStyle.active,
         snap.status==='invalidated'&&'line-through'
)}
       >
        <div className="flex items-center gap-2">
         <button
          onClick={()=>setExpandedId(expandedId===snap.id?null:snap.id)}
          className="flex-shrink-0 text-nier-text-light hover:text-nier-text-main"
         >
          {expandedId===snap.id?<ChevronDown size={12}/>:<ChevronRight size={12}/>}
         </button>
         <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <CheckCircle size={12} className={cn(stepTypeIcon[snap.stepType]||'text-nier-text-light')}/>
          <span className="text-nier-caption truncate">{snap.label}</span>
          <span className="text-nier-caption text-nier-text-light opacity-60 flex-shrink-0">
           {stepTypeLabel[snap.stepType]||snap.stepType}
          </span>
         </div>
         <span className="text-nier-caption text-nier-text-light opacity-60 flex-shrink-0">
          {formatTime(snap.createdAt)}
         </span>
         {snap.status==='active'&&snap.stepType!=='integration_completed'&&(
          <Button
           size="sm"
           onClick={()=>onRestore(snap.id)}
           disabled={restoring}
           className="gap-1 flex-shrink-0"
          >
           <RotateCcw size={10}/>
           復元
          </Button>
)}
         {snap.status==='restored'&&(
          <span className="text-nier-caption text-nier-accent-blue flex-shrink-0 flex items-center gap-1">
           <RotateCcw size={10}/>
           復元済み
          </span>
)}
        </div>
        {expandedId===snap.id&&snap.status!=='invalidated'&&(
         <div className="mt-2 pl-5 text-nier-caption text-nier-text-light border-t border-nier-border-light pt-2">
          <div className="space-y-1">
           <div>ステップID: {snap.stepId}</div>
           <div>ステータス: {snap.status}</div>
           {snap.workerTasks&&snap.workerTasks.length>0&&(
            <div>Workerタスク数: {snap.workerTasks.length}</div>
)}
          </div>
         </div>
)}
       </div>
))}
     </div>
    </div>
))}
   <div className="flex items-start gap-1.5 px-2 py-1.5 text-nier-caption text-nier-text-light">
    <AlertTriangle size={12} className="flex-shrink-0 mt-0.5 opacity-60"/>
    <span>復元するとその時点以降のスナップショットは無効化されます。次回実行時に復元時点から再開します。</span>
   </div>
  </div>
)
}
