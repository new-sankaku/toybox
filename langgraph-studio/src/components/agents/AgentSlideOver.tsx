import{useEffect,useRef}from'react'
import{createPortal}from'react-dom'
import{X,Clock,Activity,FileText,Pause,Play,RotateCcw,MessageCircle}from'lucide-react'
import{cn}from'@/lib/utils'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{Progress}from'@/components/ui/Progress'
import{AgentLogStreaming}from'./AgentLog'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import type{Agent,AgentLogEntry}from'@/types/agent'

const statusBarColorMap:Record<string,string>={
 running:'bg-nier-accent-orange',
 waiting_approval:'bg-nier-accent-yellow',
 waiting_response:'bg-nier-accent-yellow',
 completed:'bg-nier-accent-green',
 failed:'bg-nier-accent-red',
 blocked:'bg-nier-accent-red',
 interrupted:'bg-nier-accent-orange',
 paused:'bg-nier-accent-blue',
 waiting_provider:'bg-nier-accent-blue',
 pending:'bg-nier-border-dark',
 cancelled:'bg-nier-border-dark'
}

interface AgentSlideOverProps{
 agent:Agent|null
 logs:AgentLogEntry[]
 onClose:()=>void
 onRetry?:()=>void
 onPause?:()=>void
 onResume?:()=>void
}

const getDisplayName=(agent:Agent):string=>{
 return(agent.metadata?.displayName as string)||agent.type
}

export function AgentSlideOver({
 agent,
 logs,
 onClose,
 onRetry,
 onPause,
 onResume
}:AgentSlideOverProps):JSX.Element|null{
 const panelRef=useRef<HTMLDivElement>(null)
 const getAgentStatusLabel=useUIConfigStore(s=>s.getAgentStatusLabel)

 useEffect(()=>{
  const handleKeyDown=(e:KeyboardEvent)=>{
   if(e.key==='Escape')onClose()
  }
  document.addEventListener('keydown',handleKeyDown)
  return()=>document.removeEventListener('keydown',handleKeyDown)
 },[onClose])

 if(!agent)return null

 const statusBarColor=statusBarColorMap[agent.status]||'bg-nier-border-dark'

 const getRuntime=()=>{
  if(!agent.startedAt)return'-'
  const start=new Date(agent.startedAt).getTime()
  const end=agent.completedAt
   ?new Date(agent.completedAt).getTime()
   : Date.now()
  const seconds=Math.floor((end-start)/1000)
  if(seconds<60)return`${seconds}秒`
  const minutes=Math.floor(seconds/60)
  const remainingSeconds=seconds%60
  return`${minutes}分${remainingSeconds}秒`
 }

 return createPortal(
  <div className="fixed inset-0 z-[100]">
   <div className="absolute inset-0 bg-black/20" onClick={onClose}/>
   <div
    ref={panelRef}
    className="absolute right-0 top-0 h-full w-[480px] max-w-[90vw] bg-nier-bg-panel border-l border-nier-border-dark shadow-lg flex flex-col animate-nier-slide-in-right"
   >
    <div className="flex items-center justify-between bg-nier-bg-header text-nier-text-header px-4 py-2.5">
     <div className="flex items-center gap-2 min-w-0">
      <div className={cn('w-1 h-5 flex-shrink-0',statusBarColor)}/>
      <h2 className="text-nier-body tracking-nier-wide truncate">{getDisplayName(agent)}</h2>
      <span className="text-nier-caption opacity-70 flex-shrink-0">{getAgentStatusLabel(agent.status)}</span>
     </div>
     <button
      onClick={onClose}
      className="text-nier-text-header hover:bg-white/10 p-1 transition-colors flex-shrink-0"
     >
      <X size={16}/>
     </button>
    </div>

    <div className="flex-1 overflow-y-auto">
     <div className="p-4 space-y-3">
      <div className="grid grid-cols-3 gap-3">
       <div className="bg-nier-bg-main p-2.5 border border-nier-border-light">
        <div className="flex items-center gap-1.5 text-nier-caption text-nier-text-light mb-1">
         <Clock size={12}/>
         実行時間
        </div>
        <div className="text-nier-small text-nier-text-main font-medium">{getRuntime()}</div>
       </div>
       <div className="bg-nier-bg-main p-2.5 border border-nier-border-light">
        <div className="flex items-center gap-1.5 text-nier-caption text-nier-text-light mb-1">
         <Activity size={12}/>
         Token
        </div>
        <div className="text-nier-small text-nier-text-main font-medium">{agent.tokensUsed.toLocaleString()}</div>
       </div>
       <div className="bg-nier-bg-main p-2.5 border border-nier-border-light">
        <div className="flex items-center gap-1.5 text-nier-caption text-nier-text-light mb-1">
         <FileText size={12}/>
         ログ
        </div>
        <div className="text-nier-small text-nier-text-main font-medium">{logs.length}件</div>
       </div>
      </div>

      <Card>
       <CardHeader>
        <DiamondMarker>進捗</DiamondMarker>
        <span className="ml-auto text-nier-caption text-nier-text-light">{agent.progress}%</span>
       </CardHeader>
       <CardContent className="space-y-2">
        <Progress value={agent.progress} className="h-2"/>
        {agent.currentTask&&(
         <div className="text-nier-caption text-nier-text-light">{agent.currentTask}</div>
)}
       </CardContent>
      </Card>

      <div className="flex gap-2">
       {(agent.status==='running'||agent.status==='waiting_approval')&&onPause&&(
        <Button size="sm" onClick={onPause} className="flex-1 gap-2">
         <Pause size={14}/>
         一時停止
        </Button>
)}
       {(agent.status==='paused'||agent.status==='waiting_response')&&onResume&&(
        <Button size="sm" variant="success" onClick={onResume} className="flex-1 gap-2">
         <Play size={14}/>
         {agent.status==='waiting_response'?'返答して再開':'再開'}
        </Button>
)}
       {agent.status==='waiting_response'&&(
        <div className="flex items-center gap-1.5 text-nier-caption text-nier-accent-yellow">
         <MessageCircle size={12}/>
         オペレーター返答待ち
        </div>
)}
       {(agent.status==='failed'||agent.status==='interrupted'||agent.status==='cancelled')&&onRetry&&(
        <Button size="sm" variant="success" onClick={onRetry} className="flex-1 gap-2">
         <RotateCcw size={14}/>
         リトライ
        </Button>
)}
      </div>

      {agent.status==='failed'&&agent.error&&(
       <Card className="border-nier-accent-red">
        <CardHeader className="bg-nier-accent-red">
         <span className="text-white text-nier-caption">エラー詳細</span>
        </CardHeader>
        <CardContent>
         <p className="text-nier-caption text-nier-accent-red">{agent.error}</p>
        </CardContent>
       </Card>
)}

      <AgentLogStreaming
       logs={logs}
       isStreaming={agent.status==='running'}
       maxHeight="400px"
      />
     </div>
    </div>
   </div>
  </div>,
  document.body
)
}
