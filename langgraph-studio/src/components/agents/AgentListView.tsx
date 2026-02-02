import{useState,useMemo,useCallback,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{AgentCard}from'./AgentCard'
import{AgentAccordionDetail}from'./AgentAccordionDetail'
import type{Agent,AgentStatus,AgentLogEntry}from'@/types/agent'
import{cn}from'@/lib/utils'
import{Filter,Play,CheckCircle,XCircle,Clock,Pause,CircleDashed,AlertCircle,Zap,MessageCircle,ChevronDown,ChevronRight,Users,Loader,RotateCcw}from'lucide-react'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useProjectStore}from'@/stores/projectStore'
import type{AssetGenerationOptions}from'@/config/projectOptions'

const getDisplayName=(agent:Agent):string=>{
 return(agent.metadata?.displayName as string)||agent.type
}

interface AgentListViewProps{
 agents:Agent[]
 onToggleAgent:(agent:Agent)=>void
 openAgentIds:Set<string>
 loading?:boolean
 onRetryAgent?:(agent:Agent)=>void
 onPauseAgent?:(agent:Agent)=>void
 onResumeAgent?:(agent:Agent)=>void
 onExecuteAgent?:(agent:Agent)=>void
 onExecuteWithWorkers?:(agent:Agent)=>void
 onRetryAll?:()=>Promise<number>
 agentLogsMap:Record<string,AgentLogEntry[]>
}

type FilterStatus='all'|'incomplete'|AgentStatus

const filterOptions:{value:FilterStatus;label:string;icon:typeof Filter}[]=[
 {value:'all',label:'全て',icon:Filter},
 {value:'incomplete',label:'未完了',icon:CircleDashed},
 {value:'running',label:'実行中',icon:Play},
 {value:'waiting_approval',label:'承認待ち',icon:AlertCircle},
 {value:'waiting_response',label:'返答待ち',icon:MessageCircle},
 {value:'paused',label:'一時停止',icon:Pause},
 {value:'pending',label:'待機中',icon:Clock},
 {value:'completed',label:'完了',icon:CheckCircle},
 {value:'failed',label:'エラー',icon:XCircle},
 {value:'interrupted',label:'中断',icon:Zap},
 {value:'waiting_provider',label:'プロバイダ待ち',icon:Loader}
]

export default function AgentListView({
 agents,
 onToggleAgent,
 openAgentIds,
 loading=false,
 onRetryAgent,
 onPauseAgent,
 onResumeAgent,
 onExecuteAgent,
 onExecuteWithWorkers,
 onRetryAll,
 agentLogsMap
}:AgentListViewProps):JSX.Element{
 const[filterStatus,setFilterStatus]=useState<FilterStatus>('incomplete')
 const[collapsedWorkers,setCollapsedWorkers]=useState<Record<string,boolean>>({})
 const{fetchDefinitions,loaded,getFilteredUIPhases,getEnabledAgents}=useAgentDefinitionStore()
 const{currentProject}=useProjectStore()

 useEffect(()=>{
  if(!loaded)fetchDefinitions()
 },[loaded,fetchDefinitions])

 const assetGeneration=currentProject?.config?.assetGeneration as AssetGenerationOptions|undefined
 const enabledAgents=useMemo(()=>getEnabledAgents(assetGeneration),[assetGeneration,getEnabledAgents])
 const uiPhases=useMemo(()=>getFilteredUIPhases(assetGeneration),[assetGeneration,getFilteredUIPhases])

 const workersByParent=useMemo(()=>{
  const map:Record<string,Agent[]>={}
  for(const agent of agents){
   if(agent.parentAgentId){
    if(!map[agent.parentAgentId])map[agent.parentAgentId]=[]
    map[agent.parentAgentId].push(agent)
   }
  }
  return map
 },[agents])

 const leaderAgents=useMemo(()=>{
  return agents.filter(a=>enabledAgents.has(a.type)&&!a.parentAgentId)
 },[agents,enabledAgents])

 const applyFilter=(agentList:Agent[]):Agent[]=>{
  if(filterStatus==='all')return agentList
  if(filterStatus==='incomplete')return agentList.filter(a=>a.status!=='completed'||openAgentIds.has(a.id))
  return agentList.filter(a=>a.status===filterStatus||openAgentIds.has(a.id))
 }

 const filteredLeaders=useMemo(()=>applyFilter(leaderAgents),[leaderAgents,filterStatus,openAgentIds])

 const allAgentsForCount=useMemo(()=>{
  const leaders=agents.filter(a=>enabledAgents.has(a.type)&&!a.parentAgentId)
  const workers=agents.filter(a=>!!a.parentAgentId)
  return[...leaders,...workers]
 },[agents,enabledAgents])

 const statusCounts=useMemo(()=>{
  const list=allAgentsForCount
  return{
   all:list.length,
   incomplete:list.filter(a=>a.status!=='completed').length,
   running:list.filter(a=>a.status==='running').length,
   waiting_approval:list.filter(a=>a.status==='waiting_approval').length,
   waiting_response:list.filter(a=>a.status==='waiting_response').length,
   paused:list.filter(a=>a.status==='paused').length,
   pending:list.filter(a=>a.status==='pending').length,
   completed:list.filter(a=>a.status==='completed').length,
   failed:list.filter(a=>a.status==='failed').length,
   interrupted:list.filter(a=>a.status==='interrupted').length,
   waiting_provider:list.filter(a=>a.status==='waiting_provider').length
  }
 },[allAgentsForCount])

 const agentsByPhase=useMemo(()=>{
  const result:Record<string,Agent[]>={}
  for(const phase of uiPhases){
   const phaseAgentSet=new Set(phase.agents)
   result[phase.id]=filteredLeaders.filter(a=>phaseAgentSet.has(a.type))
  }
  return result
 },[filteredLeaders,uiPhases])

 const getWaitingFor=useCallback((agent:Agent):string|undefined=>{
  if(agent.status!=='pending')return undefined

  const runningAgents=agents.filter(a=>a.status==='running'&&!a.parentAgentId)
  if(runningAgents.length>0){
   const runningNames=runningAgents.map(a=>getDisplayName(a))
   if(runningNames.length===1){
    return`${runningNames[0]} 完了待ち`
   }
   return`${runningNames.join(', ')} 完了待ち`
  }

  const pendingBeforeMe=agents.filter(a=>
   a.id!==agent.id&&!a.parentAgentId&&
      (a.status==='pending'||a.status==='running')
)

  if(pendingBeforeMe.length===0){
   const hasCompleted=agents.some(a=>a.status==='completed')
   if(!hasCompleted){
    return'プロジェクト開始待ち'
   }
   return'開始待機'
  }

  return'プロジェクト開始待ち'
 },[agents])

 const toggleWorkerCollapse=useCallback((agentId:string)=>{
  setCollapsedWorkers(prev=>({...prev,[agentId]:!prev[agentId]}))
 },[])

 const getFilteredWorkers=(parentId:string):Agent[]=>{
  const workers=workersByParent[parentId]||[]
  return applyFilter(workers)
 }

 const getPhaseAgentCount=(phaseId:string)=>{
  const phaseAgents=agentsByPhase[phaseId]||[]
  let total=phaseAgents.length
  let completed=phaseAgents.filter(a=>a.status==='completed').length
  let running=phaseAgents.filter(a=>a.status==='running').length
  for(const agent of phaseAgents){
   const workers=workersByParent[agent.id]||[]
   total+=workers.length
   completed+=workers.filter(w=>w.status==='completed').length
   running+=workers.filter(w=>w.status==='running').length
  }
  return{total,completed,running}
 }

 const displayCount=useMemo(()=>{
  let count=filteredLeaders.length
  for(const agent of filteredLeaders){
   count+=getFilteredWorkers(agent.id).length
  }
  return count
 },[filteredLeaders,workersByParent,filterStatus,openAgentIds])

 return(
  <div className="p-4 animate-nier-fade-in h-full flex gap-3 overflow-hidden">
   {/*Agent List-Main Content*/}
   <div className="flex-1 flex flex-col overflow-hidden">
    {loading&&agents.length===0?(
     <Card className="flex-1">
      <CardContent className="py-12 text-center">
       <div className="text-nier-text-light">
        <p className="text-nier-body">読み込み中...</p>
       </div>
      </CardContent>
     </Card>
) : filteredLeaders.length===0&&Object.values(workersByParent).every(w=>applyFilter(w).length===0)?(
     <Card className="flex-1">
      <CardContent className="py-12 text-center">
       <div className="text-nier-text-light">
        <p className="text-nier-body mb-2">エージェントがありません</p>
        <p className="text-nier-small">
         プロジェクトを開始するとエージェントが表示されます
        </p>
       </div>
      </CardContent>
     </Card>
) : (
     <div className="nier-scroll-list flex-1 overflow-y-auto">
      {uiPhases.map((phase,idx)=>{
       const phaseAgents=agentsByPhase[phase.id]||[]
       if(phaseAgents.length===0)return null
       const counts=getPhaseAgentCount(phase.id)
       return(
        <Card key={phase.id} className="mb-3">
         <CardHeader>
          <DiamondMarker>{`PHASE ${idx+1} - ${phase.label}`}</DiamondMarker>
          <span className="ml-auto text-nier-caption text-nier-text-light">
           {counts.completed}/{counts.total}完了
           {counts.running>0&&(
            <span className="ml-2 text-nier-text-light">{counts.running}稼働中</span>
)}
          </span>
         </CardHeader>
         <CardContent className="p-0">
          <div className="divide-y divide-nier-border-light">
           {phaseAgents.map((agent)=>{
            const workers=getFilteredWorkers(agent.id)
            const allWorkers=workersByParent[agent.id]||[]
            const hasWorkers=allWorkers.length>0
            const isCollapsed=collapsedWorkers[agent.id]??false
            return(
             <div key={agent.id}>
              <div className="flex items-stretch">
               <div className="flex-1">
                <AgentCard
                 agent={agent}
                 onSelect={onToggleAgent}
                 isSelected={openAgentIds.has(agent.id)}
                 waitingFor={getWaitingFor(agent)}
                 onRetry={onRetryAgent}
                />
               </div>
               {hasWorkers&&(
                <button
                 className="flex items-center gap-1 px-2 text-nier-caption text-nier-text-light hover:text-nier-text-main hover:bg-nier-bg-selected transition-colors border-l border-nier-border-light"
                 onClick={()=>toggleWorkerCollapse(agent.id)}
                 title={isCollapsed?'Workers展開':'Workers折りたたみ'}
                >
                 <Users size={12}/>
                 <span>{allWorkers.length}</span>
                 {isCollapsed?<ChevronRight size={12}/>:<ChevronDown size={12}/>}
                </button>
)}
              </div>
              {openAgentIds.has(agent.id)&&(
               <AgentAccordionDetail
                agent={agent}
                logs={agentLogsMap[agent.id]||[]}
                onRetry={['failed','interrupted','cancelled'].includes(agent.status)&&onRetryAgent?()=>onRetryAgent(agent):undefined}
                onPause={['running','waiting_approval'].includes(agent.status)&&onPauseAgent?()=>onPauseAgent(agent):undefined}
                onResume={['paused','waiting_response'].includes(agent.status)&&onResumeAgent?()=>onResumeAgent(agent):undefined}
                onExecute={['completed','failed','cancelled'].includes(agent.status)&&onExecuteAgent?()=>onExecuteAgent(agent):undefined}
                onExecuteWithWorkers={['completed','failed','cancelled'].includes(agent.status)&&agent.type.endsWith('_leader')&&onExecuteWithWorkers?()=>onExecuteWithWorkers(agent):undefined}
               />
)}
              {hasWorkers&&!isCollapsed&&workers.length>0&&(
               <div className="border-t border-nier-border-light/50">
                {workers.map(worker=>(
                 <div key={worker.id}>
                  <AgentCard
                   agent={worker}
                   onSelect={onToggleAgent}
                   isSelected={openAgentIds.has(worker.id)}
                   onRetry={onRetryAgent}
                   isWorker
                  />
                  {openAgentIds.has(worker.id)&&(
                   <AgentAccordionDetail
                    agent={worker}
                    logs={agentLogsMap[worker.id]||[]}
                    onRetry={['failed','interrupted','cancelled'].includes(worker.status)&&onRetryAgent?()=>onRetryAgent(worker):undefined}
                    onPause={['running','waiting_approval'].includes(worker.status)&&onPauseAgent?()=>onPauseAgent(worker):undefined}
                    onResume={['paused','waiting_response'].includes(worker.status)&&onResumeAgent?()=>onResumeAgent(worker):undefined}
                    onExecute={['completed','failed','cancelled'].includes(worker.status)&&onExecuteAgent?()=>onExecuteAgent(worker):undefined}
                   />
)}
                 </div>
))}
               </div>
)}
              {hasWorkers&&!isCollapsed&&workers.length===0&&allWorkers.length>0&&(
               <div className="pl-8 py-1.5 text-nier-caption text-nier-text-light border-t border-nier-border-light/50">
                Workers: {allWorkers.length}件（フィルタにより非表示）
               </div>
)}
             </div>
)
           })}
          </div>
         </CardContent>
        </Card>
)
      })}
     </div>
)}
   </div>

   {/*Filter Sidebar*/}
   <div className="w-40 md:w-48 flex-shrink-0 flex flex-col gap-3 overflow-y-auto">
    {/*Status Filter*/}
    <Card>
     <CardHeader>
      <DiamondMarker>ステータス</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex flex-col gap-1">
       {filterOptions.map((option)=>{
        const Icon=option.icon
        const count=statusCounts[option.value]
        if(option.value!=='all'&&option.value!=='incomplete'&&count===0)return null
        return(
         <button
          key={option.value}
          className={cn(
           'flex items-center gap-2 px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
           filterStatus===option.value
            ?'bg-nier-bg-selected text-nier-text-main'
            : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
          onClick={()=>setFilterStatus(option.value)}
         >
          <Icon size={14}/>
          <span className="flex-1">{option.label}</span>
          <span className="text-nier-caption opacity-70">({count})</span>
         </button>
)
       })}
      </div>
     </CardContent>
    </Card>

    {/*Summary Stats*/}
    <Card>
     <CardHeader>
      <DiamondMarker>統計</DiamondMarker>
     </CardHeader>
     <CardContent>
      <div className="space-y-1 text-nier-small">
       <div className="flex justify-between">
        <span className="text-nier-text-light">総数</span>
        <span className="text-nier-text-main">{statusCounts.all}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">完了率</span>
        <span className="text-nier-text-main">
         {statusCounts.all>0?Math.round((statusCounts.completed/statusCounts.all)*100) : 0}%
        </span>
       </div>
       {statusCounts.failed>0&&(
        <div className="flex justify-between">
         <span className="text-nier-text-light">エラー</span>
         <span className="text-nier-text-main">{statusCounts.failed}</span>
        </div>
)}
       <div className="flex justify-between border-t border-nier-border-light pt-1 mt-1">
        <span className="text-nier-text-light">表示中</span>
        <span className="text-nier-text-main">{displayCount}件</span>
       </div>
      </div>
     </CardContent>
    </Card>

    {/*Retry All Button*/}
    {onRetryAll&&(statusCounts.failed+statusCounts.interrupted)>0&&(
     <Button
      variant="primary"
      size="sm"
      className="w-full"
      onClick={onRetryAll}
     >
      <RotateCcw size={14}/>
      <span className="ml-1">全エージェント再起動</span>
     </Button>
)}

   </div>
  </div>
)
}
