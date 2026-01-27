import{useState,useMemo,useCallback,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{AgentCard}from'./AgentCard'
import type{Agent,AgentStatus}from'@/types/agent'
import{cn}from'@/lib/utils'
import{Filter,Play,CheckCircle,XCircle,Clock,Pause,CircleDashed,AlertCircle,Zap,Ban,MessageCircle}from'lucide-react'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useProjectStore}from'@/stores/projectStore'
import type{AssetGenerationOptions}from'@/config/projectOptions'

const getDisplayName=(agent:Agent):string=>{
 return(agent.metadata?.displayName as string)||agent.type
}

interface AgentListViewProps{
 agents:Agent[]
 onSelectAgent:(agent:Agent)=>void
 selectedAgentId?:string
 loading?:boolean
 onRetryAgent?:(agent:Agent)=>void
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
 {value:'blocked',label:'ブロック',icon:Pause},
 {value:'interrupted',label:'中断',icon:Zap},
 {value:'cancelled',label:'キャンセル',icon:Ban}
]

export default function AgentListView({
 agents,
 onSelectAgent,
 selectedAgentId,
 loading=false,
 onRetryAgent
}:AgentListViewProps):JSX.Element{
 const[filterStatus,setFilterStatus]=useState<FilterStatus>('incomplete')
 const{fetchDefinitions,loaded,getFilteredUIPhases,getEnabledAgents}=useAgentDefinitionStore()
 const{currentProject}=useProjectStore()

 useEffect(()=>{
  if(!loaded)fetchDefinitions()
 },[loaded,fetchDefinitions])

 const assetGeneration=currentProject?.config?.assetGeneration as AssetGenerationOptions|undefined
 const enabledAgents=useMemo(()=>getEnabledAgents(assetGeneration),[assetGeneration,getEnabledAgents])
 const uiPhases=useMemo(()=>getFilteredUIPhases(assetGeneration),[assetGeneration,getFilteredUIPhases])

 const filteredAgents=useMemo(()=>{
  const enabledList=agents.filter(a=>enabledAgents.has(a.type))
  if(filterStatus==='all')return enabledList
  if(filterStatus==='incomplete')return enabledList.filter((agent)=>agent.status!=='completed')
  return enabledList.filter((agent)=>agent.status===filterStatus)
 },[agents,filterStatus,enabledAgents])

 const statusCounts=useMemo(()=>{
  const enabledList=agents.filter(a=>enabledAgents.has(a.type))
  const incomplete=enabledList.filter((a)=>a.status!=='completed').length
  return{
   all:enabledList.length,
   incomplete,
   running:enabledList.filter((a)=>a.status==='running').length,
   waiting_approval:enabledList.filter((a)=>a.status==='waiting_approval').length,
   waiting_response:enabledList.filter((a)=>a.status==='waiting_response').length,
   paused:enabledList.filter((a)=>a.status==='paused').length,
   pending:enabledList.filter((a)=>a.status==='pending').length,
   completed:enabledList.filter((a)=>a.status==='completed').length,
   failed:enabledList.filter((a)=>a.status==='failed').length,
   blocked:enabledList.filter((a)=>a.status==='blocked').length,
   interrupted:enabledList.filter((a)=>a.status==='interrupted').length,
   cancelled:enabledList.filter((a)=>a.status==='cancelled').length
  }
 },[agents,enabledAgents])

 const agentsByPhase=useMemo(()=>{
  const result:Record<string,Agent[]>={}
  for(const phase of uiPhases){
   const phaseAgentSet=new Set(phase.agents)
   result[phase.id]=filteredAgents.filter(a=>phaseAgentSet.has(a.type))
  }
  return result
 },[filteredAgents,uiPhases])

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
      {uiPhases.map((phase,idx)=>{
       const phaseAgents=agentsByPhase[phase.id]||[]
       if(phaseAgents.length===0)return null
       return(
        <Card key={phase.id} className="mb-3">
         <CardHeader>
          <DiamondMarker>{`PHASE ${idx+1} - ${phase.label}`}</DiamondMarker>
          <span className="ml-auto text-nier-caption text-nier-text-light">
           {phaseAgents.filter(a=>a.status==='completed').length}/{phaseAgents.length}完了
           {phaseAgents.filter(a=>a.status==='running').length>0&&(
            <span className="ml-2 text-nier-text-light">{phaseAgents.filter(a=>a.status==='running').length}稼働中</span>
)}
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
             onRetry={onRetryAgent}
            />
))}
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
        <span className="text-nier-text-main">{filteredAgents.length}件</span>
       </div>
      </div>
     </CardContent>
    </Card>
   </div>
  </div>
)
}
