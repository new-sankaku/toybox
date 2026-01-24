import{useState,useMemo,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{AgentCard}from'./AgentCard'
import type{Agent,AgentStatus}from'@/types/agent'
import{cn}from'@/lib/utils'
import{Filter,Play,CheckCircle,XCircle,Clock,Pause,CircleDashed,AlertCircle}from'lucide-react'

const getDisplayName=(agent:Agent):string=>{
 return(agent.metadata?.displayName as string)||agent.type
}

interface AgentListViewProps{
 agents:Agent[]
 onSelectAgent:(agent:Agent)=>void
 selectedAgentId?:string
 loading?:boolean
}

type FilterStatus='all'|'incomplete'|AgentStatus

const filterOptions:{value:FilterStatus;label:string;icon:typeof Filter}[]=[
 {value:'all',label:'全て',icon:Filter},
 {value:'incomplete',label:'未完了',icon:CircleDashed},
 {value:'running',label:'実行中',icon:Play},
 {value:'waiting_approval',label:'承認待ち',icon:AlertCircle},
 {value:'pending',label:'待機中',icon:Clock},
 {value:'completed',label:'完了',icon:CheckCircle},
 {value:'failed',label:'エラー',icon:XCircle},
 {value:'blocked',label:'ブロック',icon:Pause}
]

export default function AgentListView({
 agents,
 onSelectAgent,
 selectedAgentId,
 loading=false
}:AgentListViewProps):JSX.Element{
 const[filterStatus,setFilterStatus]=useState<FilterStatus>('incomplete')

 const filteredAgents=useMemo(()=>{
  if(filterStatus==='all')return agents
  if(filterStatus==='incomplete')return agents.filter((agent)=>agent.status!=='completed')
  return agents.filter((agent)=>agent.status===filterStatus)
 },[agents,filterStatus])

 const statusCounts=useMemo(()=>{
  const incomplete=agents.filter((a)=>a.status!=='completed').length
  return{
   all:agents.length,
   incomplete,
   running:agents.filter((a)=>a.status==='running').length,
   waiting_approval:agents.filter((a)=>a.status==='waiting_approval').length,
   pending:agents.filter((a)=>a.status==='pending').length,
   completed:agents.filter((a)=>a.status==='completed').length,
   failed:agents.filter((a)=>a.status==='failed').length,
   blocked:agents.filter((a)=>a.status==='blocked').length
  }
 },[agents])

 const agentsByPhase=useMemo(()=>{
  const phase1Types=['concept','design','scenario','character','world','task_split',
   'concept_leader','design_leader','scenario_leader','character_leader','world_leader','task_split_leader']
  const phase2Types=['code_leader','asset_leader','code_worker','asset_worker']
  const phase3Types=['integrator','tester','reviewer']

  return{
   phase1:filteredAgents.filter((a)=>phase1Types.includes(a.type)),
   phase2:filteredAgents.filter((a)=>phase2Types.includes(a.type)),
   phase3:filteredAgents.filter((a)=>phase3Types.includes(a.type))
  }
 },[filteredAgents])

 const getWaitingFor=useCallback((agent:Agent):string|undefined=>{
  if(agent.status!=='pending')return undefined

  const runningAgents=agents.filter(a=>a.status==='running')
  if(runningAgents.length>0){
   const runningNames=runningAgents.map(a=>getDisplayName(a))
   if(runningNames.length===1){
    return`${runningNames[0]} 完了待ち`
   }
   return`${runningNames.join(', ')} 完了待ち`
  }

  const pendingBeforeMe=agents.filter(a=>
   a.id!==agent.id&&
      (a.status==='pending'||a.status==='running')
)

  if(pendingBeforeMe.length===0){
   const hasCompleted=agents.some(a=>a.status==='completed')
   if(!hasCompleted){
    return'プロジェクト開始待ち'
   }
   return'開始待機'
  }

  if(runningAgents.length>0){
   const names=runningAgents.map(a=>getDisplayName(a))
   return`${names.join(', ')} 完了待ち`
  }

  return'プロジェクト開始待ち'
 },[agents])

 const renderPhaseSection=(title:string,phaseAgents:Agent[])=>{
  if(phaseAgents.length===0)return null

  const completed=phaseAgents.filter(a=>a.status==='completed').length
  const running=phaseAgents.filter(a=>a.status==='running').length

  return(
   <Card className="mb-3">
    <CardHeader>
     <DiamondMarker>{title}</DiamondMarker>
     <span className="ml-auto text-nier-caption text-nier-text-light">
      {completed}/{phaseAgents.length}完了
      {running>0&&<span className="ml-2 text-nier-text-light">{running}稼働中</span>}
     </span>
    </CardHeader>
    <CardContent className="p-0">
     <div className="divide-y divide-nier-border-light">
      {phaseAgents.map((agent)=>(
       <AgentCard
        key={agent.id}
        agent={agent}
        onSelect={onSelectAgent}
        isSelected={selectedAgentId===agent.id}
        waitingFor={getWaitingFor(agent)}
       />
))}
     </div>
    </CardContent>
   </Card>
)
 }

 return(
  <div className="p-4 animate-nier-fade-in h-full flex gap-3">
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
) : filteredAgents.length===0?(
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
      {renderPhaseSection('PHASE 1 - Planning',agentsByPhase.phase1)}
      {renderPhaseSection('PHASE 2 - Development',agentsByPhase.phase2)}
      {renderPhaseSection('PHASE 3 - Quality',agentsByPhase.phase3)}
     </div>
)}
   </div>

   {/*Filter Sidebar*/}
   <div className="w-40 md:w-48 flex-shrink-0 flex flex-col gap-3">
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
        <span className="text-nier-text-main">{filteredAgents.length}件</span>
       </div>
      </div>
     </CardContent>
    </Card>
   </div>
  </div>
)
}
