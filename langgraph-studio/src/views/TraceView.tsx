import{useState,useMemo,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{FloatingPanel}from'@/components/ui/FloatingPanel'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useTraceStore,type AgentTrace}from'@/stores/traceStore'
import{traceApi}from'@/services/apiService'
import{cn}from'@/lib/utils'
import{FolderOpen,ChevronDown,ChevronRight,Clock,Cpu,RefreshCw,Trash2,CheckCircle,XCircle,Loader}from'lucide-react'

type StatusFilter='all'|'running'|'completed'|'error'

const statusConfig={
 running:{icon:Loader,color:'text-nier-text-light',label:'実行中'},
 completed:{icon:CheckCircle,color:'text-nier-text-light',label:'完了'},
 error:{icon:XCircle,color:'text-nier-accent-orange',label:'エラー'}
}

export default function TraceView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{getLabel}=useAgentDefinitionStore()
 const{traces,setTraces,expandedTraceIds,toggleExpanded,expandAll,collapseAll,reset}=useTraceStore()
 const[loading,setLoading]=useState(true)
 const[statusFilter,setStatusFilter]=useState<StatusFilter>('all')
 const[selectedTrace,setSelectedTrace]=useState<AgentTrace|null>(null)
 const[autoRefresh,setAutoRefresh]=useState(false)

 useEffect(()=>{
  if(!currentProject){
   reset()
   setLoading(false)
   return
  }
  fetchTraces()
 },[currentProject?.id])

 useEffect(()=>{
  if(!autoRefresh||!currentProject)return
  const interval=setInterval(fetchTraces,3000)
  return()=>clearInterval(interval)
 },[autoRefresh,currentProject?.id])

 const fetchTraces=async()=>{
  if(!currentProject)return
  try{
   setLoading(true)
   const data=await traceApi.listByProject(currentProject.id)
   setTraces(data)
  }catch(error){
   console.error('Failed to fetch traces:',error)
  }finally{
   setLoading(false)
  }
 }

 const handleClearTraces=async()=>{
  if(!currentProject)return
  if(!confirm('全てのトレースを削除しますか？'))return
  try{
   await traceApi.deleteByProject(currentProject.id)
   reset()
  }catch(error){
   console.error('Failed to clear traces:',error)
  }
 }

 const filteredTraces=useMemo(()=>{
  if(statusFilter==='all')return traces
  return traces.filter(t=>t.status===statusFilter)
 },[traces,statusFilter])

 const statusCounts=useMemo(()=>({
  all:traces.length,
  running:traces.filter(t=>t.status==='running').length,
  completed:traces.filter(t=>t.status==='completed').length,
  error:traces.filter(t=>t.status==='error').length
 }),[traces])

 const formatDuration=(ms:number):string=>{
  if(ms<1000)return`${ms}ms`
  return`${(ms/1000).toFixed(2)}s`
 }

 const formatTime=(timestamp:string|null):string=>{
  if(!timestamp)return'-'
  return new Date(timestamp).toLocaleTimeString('ja-JP',{
   hour:'2-digit',minute:'2-digit',second:'2-digit'
  })
 }

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <Card>
     <CardContent>
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
       <p className="text-nier-body">プロジェクトを選択してください</p>
      </div>
     </CardContent>
    </Card>
   </div>
  )
 }

 return(
  <div className="p-4 animate-nier-fade-in h-full flex gap-3 overflow-hidden">
   <div className="flex-1 flex flex-col gap-3 overflow-hidden">
    <Card className="flex-1 flex flex-col overflow-hidden">
     <CardHeader className="flex-shrink-0">
      <DiamondMarker>Agent Trace</DiamondMarker>
      <div className="ml-auto flex items-center gap-2">
       <button
        onClick={()=>setAutoRefresh(!autoRefresh)}
        className={cn(
         'px-2 py-1 text-nier-caption border transition-colors flex items-center gap-1',
         autoRefresh
          ?'border-nier-border-dark bg-nier-bg-selected text-nier-text-main'
          :'border-nier-border-light text-nier-text-light hover:border-nier-border-dark'
        )}
       >
        <RefreshCw size={12} className={autoRefresh?'animate-spin':''}/>
        自動更新
       </button>
       <button
        onClick={fetchTraces}
        className="px-2 py-1 text-nier-caption border border-nier-border-light text-nier-text-light hover:border-nier-border-dark transition-colors"
       >
        更新
       </button>
       <button
        onClick={expandAll}
        className="px-2 py-1 text-nier-caption border border-nier-border-light text-nier-text-light hover:border-nier-border-dark transition-colors"
       >
        全展開
       </button>
       <button
        onClick={collapseAll}
        className="px-2 py-1 text-nier-caption border border-nier-border-light text-nier-text-light hover:border-nier-border-dark transition-colors"
       >
        全閉
       </button>
       <button
        onClick={handleClearTraces}
        className="px-2 py-1 text-nier-caption border border-nier-border-light text-nier-accent-orange hover:border-nier-accent-orange transition-colors flex items-center gap-1"
       >
        <Trash2 size={12}/>
        削除
       </button>
       <span className="text-nier-caption text-nier-text-light">
        {filteredTraces.length}件
       </span>
      </div>
     </CardHeader>
     <CardContent className="p-0 flex-1 overflow-y-auto">
      {loading&&traces.length===0?(
       <div className="p-8 text-center text-nier-text-light">読み込み中...</div>
      ):filteredTraces.length===0?(
       <div className="p-8 text-center text-nier-text-light">
        トレースがありません。APIモードでAgentを実行するとトレースが記録されます。
       </div>
      ):(
       <div className="divide-y divide-nier-border-light">
        {filteredTraces.map(trace=>{
         const isExpanded=expandedTraceIds.has(trace.id)
         const config=statusConfig[trace.status]
         const StatusIcon=config.icon
         return(
          <div key={trace.id} className="border-l-4 border-transparent hover:border-nier-accent-orange">
           <div
            className={cn(
             'px-4 py-3 cursor-pointer transition-colors hover:bg-nier-bg-panel',
             isExpanded&&'bg-nier-bg-selected'
            )}
            onClick={()=>toggleExpanded(trace.id)}
           >
            <div className="flex items-center gap-3">
             <span className="text-nier-text-light">
              {isExpanded?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
             </span>
             <StatusIcon size={16} className={cn(config.color,trace.status==='running'&&'animate-spin')}/>
             <span className="text-nier-body font-medium text-nier-text-main">
              {getLabel(trace.agentType)}
             </span>
             <span className="text-nier-caption text-nier-text-light">
              ({trace.agentType})
             </span>
             <div className="ml-auto flex items-center gap-4 text-nier-caption text-nier-text-light">
              <span className="flex items-center gap-1">
               <Clock size={12}/>
               {formatDuration(trace.durationMs)}
              </span>
              <span className="flex items-center gap-1">
               <Cpu size={12}/>
               {trace.tokensInput+trace.tokensOutput} tokens
              </span>
              <span>{formatTime(trace.startedAt)}</span>
              <span className={config.color}>{config.label}</span>
             </div>
            </div>
           </div>
           {isExpanded&&(
            <div className="px-4 pb-4 space-y-3 bg-nier-bg-panel">
             <div className="grid grid-cols-4 gap-4 text-nier-small">
              <div>
               <span className="text-nier-caption text-nier-text-light block">モデル</span>
               <span className="text-nier-text-main">{trace.modelUsed||'-'}</span>
              </div>
              <div>
               <span className="text-nier-caption text-nier-text-light block">入力トークン</span>
               <span className="text-nier-text-main">{trace.tokensInput.toLocaleString()}</span>
              </div>
              <div>
               <span className="text-nier-caption text-nier-text-light block">出力トークン</span>
               <span className="text-nier-text-main">{trace.tokensOutput.toLocaleString()}</span>
              </div>
              <div>
               <span className="text-nier-caption text-nier-text-light block">処理時間</span>
               <span className="text-nier-text-main">{formatDuration(trace.durationMs)}</span>
              </div>
             </div>
             {trace.errorMessage&&(
              <div>
               <span className="text-nier-caption text-nier-accent-orange block mb-1">エラー</span>
               <pre className="text-nier-caption bg-nier-bg-selected p-2 overflow-auto max-h-20 text-nier-accent-orange">
                {trace.errorMessage}
               </pre>
              </div>
             )}
             <div className="flex gap-2">
              <button
               onClick={(e)=>{e.stopPropagation();setSelectedTrace(trace)}}
               className="px-3 py-1.5 text-nier-caption border border-nier-border-light text-nier-text-main hover:border-nier-border-dark transition-colors"
              >
               詳細を表示
              </button>
             </div>
            </div>
           )}
          </div>
         )
        })}
       </div>
      )}
     </CardContent>
    </Card>
   </div>

   <div className="w-40 md:w-48 flex-shrink-0 flex flex-col gap-3 overflow-y-auto">
    <Card>
     <CardHeader>
      <DiamondMarker>ステータス</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex flex-col gap-1">
       {(['all','completed','running','error']as StatusFilter[]).map(status=>(
        <button
         key={status}
         className={cn(
          'flex items-center gap-2 px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
          statusFilter===status
           ?'bg-nier-bg-selected text-nier-text-main'
           :'text-nier-text-light hover:bg-nier-bg-panel'
         )}
         onClick={()=>setStatusFilter(status)}
        >
         {status!=='all'&&(()=>{
          const Icon=statusConfig[status].icon
          return<Icon size={14} className={statusConfig[status].color}/>
         })()}
         {status==='all'&&<span className="w-[14px]"/>}
         <span className="flex-1">{status==='all'?'全て':statusConfig[status].label}</span>
         <span className="text-nier-caption opacity-70">({statusCounts[status]})</span>
        </button>
       ))}
      </div>
     </CardContent>
    </Card>

    <Card>
     <CardHeader>
      <DiamondMarker>統計</DiamondMarker>
     </CardHeader>
     <CardContent>
      <div className="space-y-1">
       <div className="flex justify-between text-nier-small">
        <span className="text-nier-text-light">総トレース</span>
        <span className="text-nier-text-main">{traces.length}</span>
       </div>
       <div className="flex justify-between text-nier-small">
        <span className="text-nier-text-light">総トークン</span>
        <span className="text-nier-text-main">
         {traces.reduce((sum,t)=>sum+t.tokensInput+t.tokensOutput,0).toLocaleString()}
        </span>
       </div>
       <div className="flex justify-between text-nier-small">
        <span className="text-nier-text-light">平均時間</span>
        <span className="text-nier-text-main">
         {traces.length>0
          ?formatDuration(Math.round(traces.reduce((sum,t)=>sum+t.durationMs,0)/traces.length))
          :'-'}
        </span>
       </div>
      </div>
     </CardContent>
    </Card>
   </div>

   <FloatingPanel
    isOpen={!!selectedTrace}
    onClose={()=>setSelectedTrace(null)}
    title="トレース詳細"
    size="xl"
    panelId="trace-detail"
   >
    {selectedTrace&&(
     <div className="space-y-4 max-h-[70vh] overflow-y-auto">
      <div className="grid grid-cols-4 gap-4">
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">Agent</span>
        <span className="text-nier-small text-nier-text-main">{getLabel(selectedTrace.agentType)}</span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">タイプ</span>
        <span className="text-nier-small text-nier-text-main">{selectedTrace.agentType}</span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">ステータス</span>
        <span className={cn('text-nier-small',statusConfig[selectedTrace.status].color)}>
         {statusConfig[selectedTrace.status].label}
        </span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">モデル</span>
        <span className="text-nier-small text-nier-text-main">{selectedTrace.modelUsed||'-'}</span>
       </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">開始時刻</span>
        <span className="text-nier-small text-nier-text-main">
         {selectedTrace.startedAt?new Date(selectedTrace.startedAt).toLocaleString('ja-JP'):'-'}
        </span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">完了時刻</span>
        <span className="text-nier-small text-nier-text-main">
         {selectedTrace.completedAt?new Date(selectedTrace.completedAt).toLocaleString('ja-JP'):'-'}
        </span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">処理時間</span>
        <span className="text-nier-small text-nier-text-main">{formatDuration(selectedTrace.durationMs)}</span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">トークン</span>
        <span className="text-nier-small text-nier-text-main">
         {selectedTrace.tokensInput} in / {selectedTrace.tokensOutput} out
        </span>
       </div>
      </div>

      {selectedTrace.errorMessage&&(
       <div>
        <span className="text-nier-caption text-nier-accent-orange block mb-1">エラーメッセージ</span>
        <pre className="text-nier-caption bg-nier-bg-selected p-3 overflow-auto max-h-32 text-nier-accent-orange whitespace-pre-wrap">
         {selectedTrace.errorMessage}
        </pre>
       </div>
      )}

      {selectedTrace.inputContext&&Object.keys(selectedTrace.inputContext).length>0&&(
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">入力コンテキスト</span>
        <pre className="text-nier-caption bg-nier-bg-selected p-3 overflow-auto max-h-40 text-nier-text-main">
         {JSON.stringify(selectedTrace.inputContext,null,2)}
        </pre>
       </div>
      )}

      {selectedTrace.promptSent&&(
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">送信プロンプト</span>
        <pre className="text-nier-caption bg-nier-bg-selected p-3 overflow-auto max-h-60 text-nier-text-main whitespace-pre-wrap">
         {selectedTrace.promptSent}
        </pre>
       </div>
      )}

      {selectedTrace.llmResponse&&(
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">LLMレスポンス</span>
        <pre className="text-nier-caption bg-nier-bg-selected p-3 overflow-auto max-h-60 text-nier-text-main whitespace-pre-wrap">
         {selectedTrace.llmResponse}
        </pre>
       </div>
      )}

      {selectedTrace.outputData&&Object.keys(selectedTrace.outputData).length>0&&(
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">出力データ</span>
        <pre className="text-nier-caption bg-nier-bg-selected p-3 overflow-auto max-h-40 text-nier-text-main">
         {JSON.stringify(selectedTrace.outputData,null,2)}
        </pre>
       </div>
      )}
     </div>
    )}
   </FloatingPanel>
  </div>
 )
}
