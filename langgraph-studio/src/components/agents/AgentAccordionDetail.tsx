import{useRef,useEffect,useState,useMemo,useCallback}from'react'
import{Pause,Play,RotateCcw,MessageCircle,AlertTriangle}from'lucide-react'
import{cn}from'@/lib/utils'
import{Button}from'@/components/ui/Button'
import{SequenceDiagram}from'./SequenceDiagram'
import{SequenceDetailPanel}from'./SequenceDetailPanel'
import{SystemPromptPanel}from'./SystemPromptPanel'
import{agentApi}from'@/services/apiService'
import type{Agent,AgentLogEntry,SequenceData,SequenceMessage,AgentSystemPrompt}from'@/types/agent'

interface AgentAccordionDetailProps{
 agent:Agent
 logs:AgentLogEntry[]
 onRetry?:()=>void
 onPause?:()=>void
 onResume?:()=>void
 onExecute?:()=>void
 onExecuteWithWorkers?:()=>void
}

type TabId='log'|'sequence'|'prompt'

const formatTimestamp=(timestamp:string)=>{
 const d=new Date(timestamp)
 const mm=String(d.getMonth()+1).padStart(2,'0')
 const dd=String(d.getDate()).padStart(2,'0')
 const time=d.toLocaleTimeString('ja-JP',{
  hour:'2-digit',
  minute:'2-digit',
  second:'2-digit',
  fractionalSecondDigits:3
 })
 return`${mm}/${dd} ${time}`
}

const levelStyle:Record<string,string>={
 error:'text-nier-accent-red',
 warning:'text-nier-accent-orange',
 info:'text-nier-text-light',
 debug:'text-nier-text-light opacity-70'
}

export function AgentAccordionDetail({
 agent,
 logs,
 onRetry,
 onPause,
 onResume,
 onExecute,
 onExecuteWithWorkers
}:AgentAccordionDetailProps):JSX.Element{
 const contentRef=useRef<HTMLDivElement>(null)
 const logRef=useRef<HTMLDivElement>(null)
 const seqRef=useRef<HTMLDivElement>(null)
 const[maxH,setMaxH]=useState(0)
 const prevLogCountRef=useRef(logs.length)
 const seqScrollPosRef=useRef(0)
 const[activeTab,setActiveTab]=useState<TabId>('log')
 const[seqData,setSeqData]=useState<SequenceData|null>(null)
 const[seqLoading,setSeqLoading]=useState(false)
 const[seqError,setSeqError]=useState<string|null>(null)
 const[promptData,setPromptData]=useState<AgentSystemPrompt|null>(null)
 const[promptLoading,setPromptLoading]=useState(false)
 const[promptError,setPromptError]=useState<string|null>(null)
 const promptFetchedRef=useRef(false)
 const[detailPanelOpen,setDetailPanelOpen]=useState(false)
 const[selectedMessage,setSelectedMessage]=useState<SequenceMessage|null>(null)
 const prevStatusRef=useRef(agent.status)

 useEffect(()=>{
  if(contentRef.current){
   setMaxH(contentRef.current.scrollHeight)
  }
 })

 useEffect(()=>{
  if(!logRef.current)return
  const el=logRef.current
  const prevCount=prevLogCountRef.current
  const newCount=logs.length
  if(newCount>prevCount){
   const isAtBottom=el.scrollHeight-el.scrollTop-el.clientHeight<50
   if(isAtBottom){
    requestAnimationFrame(()=>{
     el.scrollTop=el.scrollHeight
    })
   }
  }
  prevLogCountRef.current=newCount
 },[logs.length])

 const seqFetchedRef=useRef(false)

 const fetchSequence=useCallback(async()=>{
  if(seqRef.current)seqScrollPosRef.current=seqRef.current.scrollTop
  setSeqLoading(true)
  setSeqError(null)
  try{
   const result=await agentApi.getSequence(agent.id)
   setSeqData(result)
   requestAnimationFrame(()=>{
    if(seqRef.current)seqRef.current.scrollTop=seqScrollPosRef.current
   })
  }catch{
   setSeqError('シーケンスデータの取得に失敗しました')
  }finally{
   setSeqLoading(false)
   seqFetchedRef.current=true
  }
 },[agent.id])

 useEffect(()=>{
  if(activeTab==='sequence'&&!seqFetchedRef.current&&!seqLoading){
   fetchSequence()
  }
 },[activeTab,seqLoading,fetchSequence])

 const fetchPrompt=useCallback(async()=>{
  setPromptLoading(true)
  setPromptError(null)
  try{
   const result=await agentApi.getSystemPrompt(agent.id)
   setPromptData(result)
  }catch{
   setPromptError('システムプロンプトの取得に失敗しました')
  }finally{
   setPromptLoading(false)
   promptFetchedRef.current=true
  }
 },[agent.id])

 useEffect(()=>{
  if(activeTab==='prompt'&&!promptFetchedRef.current&&!promptLoading){
   fetchPrompt()
  }
 },[activeTab,promptLoading,fetchPrompt])

 useEffect(()=>{
  const prev=prevStatusRef.current
  const curr=agent.status
  prevStatusRef.current=curr
  const terminalStatuses=['completed','failed']
  if(terminalStatuses.includes(curr)&&!terminalStatuses.includes(prev)){
   seqFetchedRef.current=false
   if(activeTab==='sequence'){
    fetchSequence()
   }
  }
 },[agent.status,activeTab,fetchSequence])

 const handleMessageClick=useCallback((msg:SequenceMessage)=>{
  if(!msg.sourceId)return
  setSelectedMessage(msg)
  setDetailPanelOpen(true)
 },[])

 const sortedLogs=useMemo(()=>
  [...logs].sort((a,b)=>new Date(a.timestamp).getTime()-new Date(b.timestamp).getTime())
 ,[logs])

 const hasControls=(agent.status==='running'||agent.status==='waiting_approval')&&onPause
  ||(agent.status==='paused'||agent.status==='waiting_response')&&onResume
  ||(agent.status==='failed'||agent.status==='interrupted')&&onRetry
  ||onExecute||onExecuteWithWorkers

 return(
  <div
   ref={contentRef}
   className="overflow-hidden transition-all duration-300 ease-in-out bg-nier-bg-selected"
   style={{maxHeight:maxH>0?`${maxH}px`:'none'}}
  >
   <div className="px-3 py-2 space-y-2">
    {hasControls&&(
     <div className="flex items-center gap-2">
      {(agent.status==='running'||agent.status==='waiting_approval')&&onPause&&(
       <Button size="sm" onClick={onPause} className="gap-1.5">
        <Pause size={12}/>
        一時停止
       </Button>
)}
      {(agent.status==='paused'||agent.status==='waiting_response')&&onResume&&(
       <Button size="sm" variant="success" onClick={onResume} className="gap-1.5">
        <Play size={12}/>
        {agent.status==='waiting_response'?'返答して再開':'再開'}
       </Button>
)}
      {agent.status==='waiting_response'&&(
       <span className="text-nier-caption text-nier-text-light flex items-center gap-1">
        <MessageCircle size={10}/>
        オペレーター返答待ち
       </span>
)}
      {(agent.status==='failed'||agent.status==='interrupted')&&onRetry&&(
       <Button size="sm" variant="success" onClick={onRetry} className="gap-1.5">
        <RotateCcw size={12}/>
        リトライ
       </Button>
)}
      {onExecute&&(
       <Button size="sm" onClick={onExecute} className="gap-1.5">
        <Play size={12}/>
        実行
       </Button>
)}
      {onExecuteWithWorkers&&(
       <Button size="sm" onClick={onExecuteWithWorkers} className="gap-1.5">
        <Play size={12}/>
        Workers含め実行
       </Button>
)}
     </div>
)}

    {agent.status==='failed'&&agent.error&&(
     <div className="flex items-start gap-1.5 px-2 py-1.5 border border-nier-accent-red bg-nier-bg-panel">
      <AlertTriangle size={12} className="text-nier-accent-red flex-shrink-0 mt-0.5"/>
      <p className="text-nier-caption text-nier-accent-red">{agent.error}</p>
     </div>
)}

    <div className="flex gap-1 border-b border-nier-border-light">
     <button
      onClick={()=>setActiveTab('log')}
      className={cn(
       'px-3 py-1 text-nier-caption transition-colors',
       activeTab==='log'
        ?'text-nier-text-main border-b-2 border-nier-text-main'
        :'text-nier-text-light hover:text-nier-text-main'
)}
     >
      ログ
     </button>
     <button
      onClick={()=>setActiveTab('sequence')}
      className={cn(
       'px-3 py-1 text-nier-caption transition-colors',
       activeTab==='sequence'
        ?'text-nier-text-main border-b-2 border-nier-text-main'
        :'text-nier-text-light hover:text-nier-text-main'
)}
     >
      シーケンス
     </button>
     <button
      onClick={()=>setActiveTab('prompt')}
      className={cn(
       'px-3 py-1 text-nier-caption transition-colors',
       activeTab==='prompt'
        ?'text-nier-text-main border-b-2 border-nier-text-main'
        :'text-nier-text-light hover:text-nier-text-main'
)}
     >
      プロンプト
     </button>
    </div>

    {activeTab==='log'&&sortedLogs.length>0&&(
     <div
      ref={logRef}
      className="font-mono text-nier-caption bg-nier-bg-panel border border-nier-border-light px-2 py-1 nier-log-panel"
     >
      {agent.status==='running'&&(
       <div className="flex items-center gap-1.5 py-0.5 text-nier-accent-green">
        <div className="w-1.5 h-1.5 bg-nier-accent-green rounded-full animate-pulse"/>
        LIVE
       </div>
)}
      {sortedLogs.map((log,i)=>(
       <div key={log.id} data-log-row className={cn('flex gap-2 py-px',i%2===0?'bg-nier-bg-panel':'bg-nier-bg-main/40')} style={{lineHeight:'1.3'}}>
        <span className="text-nier-text-light flex-shrink-0 opacity-60 px-1">{formatTimestamp(log.timestamp)}</span>
        <span className={cn('flex-1 break-all',levelStyle[log.level]||'text-nier-text-light')}>
         {log.message}
        </span>
       </div>
))}
     </div>
)}

    {activeTab==='log'&&sortedLogs.length===0&&(
     <div className="py-4 text-center text-nier-text-light text-nier-caption">
      ログがありません
     </div>
)}

    {activeTab==='sequence'&&(
     <div ref={seqRef} className="min-h-[100px] nier-sequence-panel">
      {seqLoading&&(
       <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
        読み込み中...
       </div>
)}
      {seqError&&(
       <div className="flex items-center justify-center py-8 text-nier-accent-red text-nier-caption">
        {seqError}
       </div>
)}
      {!seqLoading&&!seqError&&seqData&&(
       <SequenceDiagram data={seqData} onMessageClick={handleMessageClick}/>
)}
      <SequenceDetailPanel
       isOpen={detailPanelOpen}
       onClose={()=>setDetailPanelOpen(false)}
       selectedMessage={selectedMessage}
      />
      {!seqLoading&&!seqError&&!seqData&&(
       <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
        シーケンスデータがありません
       </div>
)}
     </div>
)}

    {activeTab==='prompt'&&(
     <div className="min-h-[100px] nier-sequence-panel">
      {promptLoading&&(
       <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
        読み込み中...
       </div>
)}
      {promptError&&(
       <div className="flex items-center justify-center py-8 text-nier-accent-red text-nier-caption">
        {promptError}
       </div>
)}
      {!promptLoading&&!promptError&&promptData&&(
       <SystemPromptPanel data={promptData}/>
)}
      {!promptLoading&&!promptError&&!promptData&&(
       <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
        プロンプトデータがありません
       </div>
)}
     </div>
)}
   </div>
  </div>
)
}
