import{useState,useMemo,useEffect,useRef}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{FloatingPanel}from'@/components/ui/FloatingPanel'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useLogStore}from'@/stores/logStore'
import{logsApi,type ApiSystemLog}from'@/services/apiService'
import{cn}from'@/lib/utils'
import{Search,AlertCircle,Info,AlertTriangle,Bug,FolderOpen,ChevronDown,Check}from'lucide-react'

interface SystemLog{
 id:string
 timestamp:string
 level:'debug'|'info'|'warn'|'error'
 source:string
 message:string
 details?:string
}

function convertApiLog(apiLog:ApiSystemLog):SystemLog{
 return{
  id:apiLog.id,
  timestamp:apiLog.timestamp,
  level:apiLog.level,
  source:apiLog.source,
  message:apiLog.message,
  details:apiLog.details||undefined,
 }
}

type LogLevel='all'|'debug'|'info'|'warn'|'error'

const levelConfig={
 debug:{icon:Bug,color:'text-nier-text-light',bg:'bg-nier-bg-panel'},
 info:{icon:Info,color:'text-nier-accent-blue',bg:'bg-nier-bg-panel'},
 warn:{icon:AlertTriangle,color:'text-nier-accent-yellow',bg:'bg-nier-bg-panel'},
 error:{icon:AlertCircle,color:'text-nier-accent-red',bg:'bg-nier-bg-panel'}
}

export default function LogsView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{definitions:_definitions,getLabel}=useAgentDefinitionStore()
 const logStore=useLogStore()
 const logVersion=useLogStore(s=>s.version)
 const[initialLoading,setInitialLoading]=useState(true)
 const[filterLevel,setFilterLevel]=useState<LogLevel>('all')
 const[selectedAgents,setSelectedAgents]=useState<Set<string>>(new Set())
 const[searchQuery,setSearchQuery]=useState('')
 const[selectedLog,setSelectedLog]=useState<SystemLog|null>(null)
 const[dropdownOpen,setDropdownOpen]=useState(false)
 const dropdownRef=useRef<HTMLDivElement>(null)

 const logs=useMemo(()=>logStore.logs.map(convertApiLog),[logStore.logs])

 const availableSources=useMemo(()=>{
  const sources=new Set<string>()
  logs.forEach(log=>sources.add(log.source))
  return Array.from(sources).sort()
 },[logs])

 const getSourceLabel=(source:string):string=>{
  if(source==='System')return'System'
  return getLabel(source)
 }

 useEffect(()=>{
  const handleClickOutside=(e:MouseEvent)=>{
   if(dropdownRef.current&&!dropdownRef.current.contains(e.target as Node)){
    setDropdownOpen(false)
   }
  }
  document.addEventListener('mousedown',handleClickOutside)
  return()=>document.removeEventListener('mousedown',handleClickOutside)
 },[])

 useEffect(()=>{
  setFilterLevel('all')
  setSelectedAgents(new Set())
  setSearchQuery('')
  setSelectedLog(null)
 },[logVersion])

 useEffect(()=>{
  if(!currentProject){
   logStore.setLogs([])
   setInitialLoading(false)
   return
  }

  const fetchLogs=async()=>{
   setInitialLoading(true)
   try{
    const data=await logsApi.getByProject(currentProject.id)
    logStore.setLogs(data)
   }catch(error){
    console.error('Failed to fetch logs:',error)
    logStore.setError(error instanceof Error?error.message:'ログの取得に失敗しました')
   }finally{
    setInitialLoading(false)
   }
  }

  fetchLogs()
 },[currentProject?.id,logVersion])

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

 const filteredLogs=useMemo(()=>{
  let filtered=logs

  if(filterLevel!=='all'){
   filtered=filtered.filter(log=>log.level===filterLevel)
  }

  if(selectedAgents.size>0){
   filtered=filtered.filter(log=>selectedAgents.has(log.source))
  }

  if(searchQuery){
   const query=searchQuery.toLowerCase()
   filtered=filtered.filter(log=>
    log.message.toLowerCase().includes(query)||
        log.source.toLowerCase().includes(query)
)
  }

  return filtered.sort((a,b)=>new Date(b.timestamp).getTime()-new Date(a.timestamp).getTime())
 },[logs,filterLevel,selectedAgents,searchQuery])

 const levelCounts=useMemo(()=>({
  all:logs.length,
  debug:logs.filter(l=>l.level==='debug').length,
  info:logs.filter(l=>l.level==='info').length,
  warn:logs.filter(l=>l.level==='warn').length,
  error:logs.filter(l=>l.level==='error').length
 }),[logs])

 const agentCounts=useMemo(()=>{
  const counts:Record<string,number>={}
  availableSources.forEach(source=>{
   counts[source]=logs.filter(l=>l.source===source).length
  })
  return counts
 },[logs,availableSources])

 const formatTime=(timestamp:string)=>{
  return new Date(timestamp).toLocaleTimeString('ja-JP',{
   hour:'2-digit',
   minute:'2-digit',
   second:'2-digit'
  })
 }

 const toggleAgent=(source:string)=>{
  setSelectedAgents(prev=>{
   const next=new Set(prev)
   if(next.has(source)){
    next.delete(source)
   }else{
    next.add(source)
   }
   return next
  })
 }

 const selectAllAgents=()=>{
  if(selectedAgents.size===availableSources.length){
   setSelectedAgents(new Set())
  }else{
   setSelectedAgents(new Set(availableSources))
  }
 }

 const getDropdownLabel=():string=>{
  if(selectedAgents.size===0)return'全て'
  if(selectedAgents.size===1)return getSourceLabel(Array.from(selectedAgents)[0])
  return`${selectedAgents.size}件選択`
 }

 return(
  <div className="p-4 animate-nier-fade-in h-full flex gap-3 overflow-hidden">
   {/*Log List and Details-Main Content*/}
   <div className="flex-1 flex flex-col gap-3 overflow-hidden">
    <Card className="flex-1 flex flex-col overflow-hidden">
      <CardHeader className="flex-shrink-0">
       <DiamondMarker>ログ一覧</DiamondMarker>
       <span className="text-nier-caption text-nier-text-light ml-auto">
        {filteredLogs.length}件
       </span>
      </CardHeader>
      <CardContent className="p-0 flex-1 overflow-y-auto">
       {initialLoading&&logs.length===0?(
        <div className="p-8 text-center text-nier-text-light">
         読み込み中...
        </div>
) : filteredLogs.length===0?(
        <div className="p-8 text-center text-nier-text-light">
         ログがありません
        </div>
) : (
        <div className="divide-y divide-nier-border-light">
         {filteredLogs.map(log=>{
          const config=levelConfig[log.level]
          const Icon=config.icon
          return(
           <div
            key={log.id}
            className={cn(
             'px-4 py-2 cursor-pointer transition-colors hover:bg-nier-bg-panel',
             selectedLog?.id===log.id&&'bg-nier-bg-selected'
)}
            onClick={()=>setSelectedLog(log)}
           >
            <div className="grid grid-cols-[70px_20px_100px_1fr] items-start gap-2">
             <span className="text-nier-caption text-nier-text-light">
              {formatTime(log.timestamp)}
             </span>
             <span className={cn('flex items-center justify-center',config.color)}>
              <Icon size={12}/>
             </span>
             <span className={cn('text-nier-caption truncate',config.color)}>
              {getSourceLabel(log.source)}
             </span>
             <span className="text-nier-small text-nier-text-main truncate">
              {log.message}
             </span>
            </div>
           </div>
)
         })}
        </div>
)}
      </CardContent>
     </Card>

   </div>

   {/*Filter Sidebar*/}
   <div className="w-40 md:w-48 flex-shrink-0 flex flex-col gap-3 overflow-y-auto">
    {/*Search*/}
    <Card>
     <CardHeader>
      <DiamondMarker>検索</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex items-center gap-2">
       <Search size={14} className="text-nier-text-light flex-shrink-0"/>
       <input
        type="text"
        className="bg-transparent border-b border-nier-border-light px-1 py-1 text-nier-small w-full focus:outline-none focus:border-nier-border-dark"
        placeholder="検索..."
        value={searchQuery}
        onChange={(e)=>setSearchQuery(e.target.value)}
       />
      </div>
     </CardContent>
    </Card>

    {/*Level Filter*/}
    <Card>
     <CardHeader>
      <DiamondMarker>レベル</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex flex-col gap-1">
       {(['all','error','warn','info','debug']as LogLevel[]).map(level=>(
        <button
         key={level}
         className={cn(
          'flex items-center gap-2 px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
          filterLevel===level
           ?'bg-nier-bg-selected text-nier-text-main'
           : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
         onClick={()=>setFilterLevel(level)}
        >
         {level!=='all'&&(()=>{
          const Icon=levelConfig[level].icon
          return<Icon size={14} className={levelConfig[level].color}/>
         })()}
         {level==='all'&&<span className="w-[14px]"/>}
         <span className="flex-1">{level==='all'?'全て' : level.toUpperCase()}</span>
         <span className="text-nier-caption opacity-70">({levelCounts[level]})</span>
        </button>
))}
      </div>
     </CardContent>
    </Card>

    {/*Agent Filter-Dropdown*/}
    <Card>
     <CardHeader>
      <DiamondMarker>エージェント</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="relative" ref={dropdownRef}>
       <button
        onClick={()=>setDropdownOpen(!dropdownOpen)}
        className="w-full flex items-center justify-between px-2 py-1.5 text-nier-small border border-nier-border-light hover:border-nier-border-dark transition-colors"
       >
        <span className={selectedAgents.size===0?'text-nier-text-light' : 'text-nier-text-main'}>
         {getDropdownLabel()}
        </span>
        <ChevronDown size={14} className={cn('text-nier-text-light transition-transform',dropdownOpen&&'rotate-180')}/>
       </button>
       {dropdownOpen&&(
        <div className="absolute top-full left-0 right-0 mt-1 bg-nier-bg-panel border border-nier-border-light z-10 max-h-48 overflow-y-auto">
         <button
          onClick={selectAllAgents}
          className="w-full flex items-center gap-2 px-2 py-1.5 text-nier-small hover:bg-nier-bg-selected transition-colors text-left border-b border-nier-border-light"
         >
          <span className={cn('w-4 h-4 border flex items-center justify-center',
           selectedAgents.size===availableSources.length
            ?'bg-nier-bg-selected border-nier-border-dark'
            : 'border-nier-border-light'
)}>
           {selectedAgents.size===availableSources.length&&<Check size={12}/>}
          </span>
          <span className="text-nier-text-light">全選択/解除</span>
         </button>
         {availableSources.map(source=>(
          <button
           key={source}
           onClick={()=>toggleAgent(source)}
           className="w-full flex items-center gap-2 px-2 py-1.5 text-nier-small hover:bg-nier-bg-selected transition-colors text-left"
          >
           <span className={cn('w-4 h-4 border flex items-center justify-center',
            selectedAgents.has(source)
             ?'bg-nier-bg-selected border-nier-border-dark'
             : 'border-nier-border-light'
)}>
            {selectedAgents.has(source)&&<Check size={12}/>}
           </span>
           <span className="flex-1 text-nier-text-main">{getSourceLabel(source)}</span>
           <span className="text-nier-caption text-nier-text-light">({agentCounts[source]})</span>
          </button>
))}
        </div>
)}
      </div>
     </CardContent>
    </Card>

    {/*Stats*/}
    <Card>
     <CardHeader>
      <DiamondMarker>統計</DiamondMarker>
     </CardHeader>
     <CardContent>
      <div className="space-y-1">
       <div className="flex justify-between text-nier-small">
        <span className="text-nier-text-light">エラー</span>
        <span className="text-nier-text-main">{levelCounts.error}</span>
       </div>
       <div className="flex justify-between text-nier-small">
        <span className="text-nier-text-light">警告</span>
        <span className="text-nier-text-main">{levelCounts.warn}</span>
       </div>
       <div className="flex justify-between text-nier-small">
        <span className="text-nier-text-light">情報</span>
        <span className="text-nier-text-main">{levelCounts.info}</span>
       </div>
       <div className="flex justify-between text-nier-small">
        <span className="text-nier-text-light">デバッグ</span>
        <span className="text-nier-text-main">{levelCounts.debug}</span>
       </div>
      </div>
     </CardContent>
    </Card>
   </div>

   <FloatingPanel
    isOpen={!!selectedLog}
    onClose={()=>setSelectedLog(null)}
    title="ログ詳細"
    size="lg"
    panelId="log-detail"
   >
    {selectedLog&&(
     <div className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">タイムスタンプ</span>
        <span className="text-nier-small text-nier-text-main">{new Date(selectedLog.timestamp).toLocaleString('ja-JP')}</span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">レベル</span>
        <span className={cn('text-nier-small',levelConfig[selectedLog.level].color)}>
         {selectedLog.level.toUpperCase()}
        </span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">ソース</span>
        <span className="text-nier-small text-nier-text-main">{getSourceLabel(selectedLog.source)}</span>
       </div>
      </div>
      <div>
       <span className="text-nier-caption text-nier-text-light block mb-1">メッセージ</span>
       <span className="text-nier-small text-nier-text-main">{selectedLog.message}</span>
      </div>
      {selectedLog.details&&(
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">詳細情報</span>
        <pre className="text-nier-caption bg-nier-bg-selected p-3 overflow-auto max-h-60 text-nier-text-main">
         {selectedLog.details}
        </pre>
       </div>
)}
     </div>
)}
   </FloatingPanel>
  </div>
)
}
