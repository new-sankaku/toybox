import{Progress}from'@/components/ui/Progress'
import{cn}from'@/lib/utils'
import type{Agent,QualityCheckConfig}from'@/types/agent'
import{Cpu,Play,CheckCircle,XCircle,Pause,Clock,Shield,ShieldOff,Sparkles,AlertCircle}from'lucide-react'

interface AgentCardProps{
 agent:Agent
 onSelect:(agent:Agent)=>void
 isSelected?:boolean
 qualityCheckConfig?:QualityCheckConfig
 /**待機中の場合、何を待っているかの説明*/
 waitingFor?:string
}

const statusConfig={
 pending:{
  color:'bg-nier-border-dark',
  icon:Clock,
  text:'待機中',
  pulse:false
 },
 running:{
  color:'bg-nier-border-dark',
  icon:Play,
  text:'実行中',
  pulse:true
 },
 waiting_approval:{
  color:'bg-nier-border-dark',
  icon:AlertCircle,
  text:'承認待ち',
  pulse:true
 },
 completed:{
  color:'bg-nier-border-dark',
  icon:CheckCircle,
  text:'完了',
  pulse:false
 },
 failed:{
  color:'bg-nier-border-dark',
  icon:XCircle,
  text:'エラー',
  pulse:false
 },
 blocked:{
  color:'bg-nier-border-dark',
  icon:Pause,
  text:'ブロック',
  pulse:false
 }
}

const getDisplayName=(agent:Agent):string=>{
 return(agent.metadata?.displayName as string)||agent.type
}

const getAgentRole=(type:string):{role:string}=>{
 if(type.endsWith('_leader')){
  return{role:'Leader'}
 }
 if(type.endsWith('_worker')){
  return{role:'Worker'}
 }
 if(type==='integrator'){
  return{role:'Leader'}
 }
 if(type==='tester'){
  return{role:'Worker'}
 }
 if(type==='reviewer'){
  return{role:'Leader'}
 }
 if(['concept','design','scenario','character','world','task_split'].includes(type)){
  return{role:'Leader'}
 }
 return{role:'Worker'}
}

export function AgentCard({
 agent,
 onSelect,
 isSelected=false,
 qualityCheckConfig,
 waitingFor
}:AgentCardProps):JSX.Element{
 const status=statusConfig[agent.status]
 const StatusIcon=status.icon
 const agentRole=getAgentRole(agent.type)

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

 const getTaskText=()=>{
  if(agent.status==='running'){
   return agent.currentTask||'処理中'
  }
  if(agent.status==='waiting_approval')return'承認待ち'
  if(agent.status==='pending')return waitingFor||'開始待機'
  if(agent.status==='blocked')return'ブロック'
  if(agent.status==='completed')return'完了'
  if(agent.status==='failed')return agent.error||'エラー発生'
  return''
 }

 const isUsingLLM=agent.status==='running'&&agent.progress>0

 return(
  <div
   className={cn(
    'cursor-pointer transition-all duration-nier-normal px-3 py-2',
    'hover:bg-nier-bg-selected',
    isSelected&&'bg-nier-bg-selected',
    status.pulse&&'animate-nier-pulse'
)}
   onClick={()=>onSelect(agent)}
  >
   {/*Grid Layout for aligned columns*/}
   <div className="grid grid-cols-[4px_55px_180px_1fr_140px_auto] items-center gap-2">
    {/*Col 1: Status Indicator*/}
    <div className={cn(
     'w-1 h-6 bg-nier-border-dark transition-opacity',
     status.pulse&&'animate-pulse'
)}/>

    {/*Col 2: Role badge*/}
    <span className="text-nier-caption text-nier-text-light">
     [{agentRole.role}]
    </span>

    {/*Col 3: Agent Type*/}
    <div className="flex items-center gap-1.5 min-w-0">
     <Cpu size={12} className="text-nier-text-light flex-shrink-0"/>
     <span className="text-nier-small font-medium text-nier-text-main truncate">
      {getDisplayName(agent)}
     </span>
    </div>

    {/*Col 4: Task/Status Text*/}
    <div className="flex items-center gap-2 min-w-0 pl-4">
     {isUsingLLM&&(
      <Sparkles size={12} className="text-nier-accent-gold flex-shrink-0 animate-pulse"/>
)}
     <span className="text-nier-caption truncate text-nier-text-light">
      {getTaskText()}
     </span>
    </div>

    {/*Col 5: Progress Bar+Time*/}
    <div className="flex items-center gap-2">
     {(agent.status==='running'||agent.status==='waiting_approval')?(
      <>
       <Progress value={agent.progress} className="h-1.5 w-12"/>
       <span className="text-nier-caption text-nier-text-light w-8">
        {agent.progress}%
       </span>
      </>
) : (
      <span className="w-[76px]"/>
)}
     <span className="text-nier-caption text-nier-text-light flex items-center gap-1">
      <Clock size={10}/>
      {getRuntime()}
     </span>
    </div>

    {/*Col 6: Right side info*/}
    <div className="flex items-center gap-3">
     <span className="text-nier-caption text-nier-text-light w-14 text-right">
      {agent.tokensUsed.toLocaleString()}tk
     </span>
     {/*Quality Check Badge*/}
     {qualityCheckConfig&&(
      <span
       className="text-nier-caption text-nier-text-light flex items-center gap-1"
       title={qualityCheckConfig.enabled?'品質チェックON' : '品質チェックOFF'}
      >
       {qualityCheckConfig.enabled?<Shield size={10}/>:<ShieldOff size={10}/>}
       QC
      </span>
)}
     <span className="text-nier-caption text-nier-text-light flex items-center gap-1 w-14">
      <StatusIcon size={10}/>
      {status.text}
     </span>
    </div>
   </div>
  </div>
)
}
