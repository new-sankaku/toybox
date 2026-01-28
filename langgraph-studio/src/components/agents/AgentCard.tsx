import{Progress}from'@/components/ui/Progress'
import{cn}from'@/lib/utils'
import type{Agent,QualityCheckConfig}from'@/types/agent'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import{Cpu,Play,CheckCircle,XCircle,Pause,Clock,Shield,ShieldOff,Sparkles,AlertCircle,RotateCcw,Ban,Zap}from'lucide-react'

interface AgentCardProps{
 agent:Agent
 onSelect:(agent:Agent)=>void
 isSelected?:boolean
 qualityCheckConfig?:QualityCheckConfig
 /**待機中の場合、何を待っているかの説明*/
 waitingFor?:string
 /**再試行ボタンクリック時のコールバック*/
 onRetry?:(agent:Agent)=>void
 /**Worker表示（インデント付き）*/
 isWorker?:boolean
}

const statusConfig={
 pending:{
  color:'bg-nier-border-dark',
  textColor:'text-nier-text-light',
  icon:Clock,
  text:'待機中',
  pulse:false
 },
 running:{
  color:'bg-nier-accent-orange',
  textColor:'text-nier-text-light',
  icon:Play,
  text:'実行中',
  pulse:true
 },
 waiting_approval:{
  color:'bg-nier-accent-yellow',
  textColor:'text-nier-text-light',
  icon:AlertCircle,
  text:'承認待ち',
  pulse:true
 },
 completed:{
  color:'bg-nier-accent-green',
  textColor:'text-nier-text-light',
  icon:CheckCircle,
  text:'完了',
  pulse:false
 },
 failed:{
  color:'bg-nier-accent-red',
  textColor:'text-nier-text-light',
  icon:XCircle,
  text:'エラー',
  pulse:false
 },
 blocked:{
  color:'bg-nier-accent-red',
  textColor:'text-nier-text-light',
  icon:Pause,
  text:'ブロック',
  pulse:false
 },
 interrupted:{
  color:'bg-nier-accent-orange',
  textColor:'text-nier-text-light',
  icon:Zap,
  text:'中断',
  pulse:false
 },
 cancelled:{
  color:'bg-nier-border-dark',
  textColor:'text-nier-text-light',
  icon:Ban,
  text:'キャンセル',
  pulse:false
 },
 paused:{
  color:'bg-nier-accent-blue',
  textColor:'text-nier-text-light',
  icon:Pause,
  text:'一時停止',
  pulse:false
 },
 waiting_response:{
  color:'bg-nier-accent-yellow',
  textColor:'text-nier-text-light',
  icon:AlertCircle,
  text:'応答待ち',
  pulse:true
 },
 waiting_provider:{
  color:'bg-nier-accent-blue',
  textColor:'text-nier-text-light',
  icon:Clock,
  text:'プロバイダ待ち',
  pulse:true
 }
}

const getDisplayName=(agent:Agent):string=>{
 return(agent.metadata?.displayName as string)||agent.type
}

export function AgentCard({
 agent,
 onSelect,
 isSelected=false,
 qualityCheckConfig,
 waitingFor,
 onRetry,
 isWorker=false
}:AgentCardProps):JSX.Element{
 const status=statusConfig[agent.status]||statusConfig.pending
 const StatusIcon=status.icon
 const{getAgentRole,getRoleLabel}=useUIConfigStore()
 const role=getAgentRole(agent.type)
 const roleLabel=getRoleLabel(role)
 const isRetryable=agent.status==='failed'||agent.status==='interrupted'||agent.status==='cancelled'

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
  if(agent.status==='interrupted')return agent.currentTask||'サーバー再起動により中断'
  if(agent.status==='cancelled')return'キャンセル済み'
  if(agent.status==='paused')return'一時停止中'
  if(agent.status==='waiting_response')return'応答待ち'
  if(agent.status==='waiting_provider')return'プロバイダ待ち'
  return''
 }

 const handleRetryClick=(e:React.MouseEvent)=>{
  e.stopPropagation()
  if(onRetry&&isRetryable){
   onRetry(agent)
  }
 }

 const isUsingLLM=agent.status==='running'&&agent.progress>0

 return(
  <div
   className={cn(
    'cursor-pointer transition-all duration-nier-normal px-3 py-2',
    'hover:bg-nier-bg-selected',
    isSelected&&'bg-nier-bg-selected',
    status.pulse&&'animate-nier-pulse',
    isWorker&&'pl-8 bg-nier-bg-main/30'
)}
   onClick={()=>onSelect(agent)}
  >
   <div className="grid grid-cols-[4px_clamp(40px,3.5vw,56px)_2fr_3fr_clamp(100px,9vw,150px)_clamp(70px,7vw,110px)] items-center gap-x-[clamp(4px,0.5vw,8px)]">
    <div className={cn(
     'w-1 h-6 transition-opacity',
     status.color,
     status.pulse&&'animate-pulse'
)}/>

    <span className="text-[clamp(9px,0.65vw,11px)] text-nier-text-light whitespace-nowrap leading-none">
     [{roleLabel}]
    </span>

    <div className="flex items-center gap-1 min-w-0">
     <Cpu size={12} className="text-nier-text-light flex-shrink-0"/>
     <span className="text-[clamp(10px,0.75vw,13px)] font-medium text-nier-text-main truncate leading-tight">
      {getDisplayName(agent)}
     </span>
    </div>

    <div className="flex items-center gap-1.5 min-w-0 pl-2">
     {isUsingLLM&&(
      <Sparkles size={12} className="text-nier-accent-gold flex-shrink-0 animate-pulse"/>
)}
     <span className="text-[clamp(9px,0.6vw,11px)] truncate text-nier-text-light leading-tight">
      {getTaskText()}
     </span>
    </div>

    <div className="flex items-center gap-1.5 whitespace-nowrap">
     {(agent.status==='running'||agent.status==='waiting_approval')?(
      <>
       <Progress value={agent.progress} className="h-1.5 w-[clamp(32px,3vw,48px)]"/>
       <span className="text-[clamp(9px,0.6vw,11px)] text-nier-text-light">
        {agent.progress}%
       </span>
      </>
) : (
      <span className="w-[clamp(50px,4.5vw,76px)]"/>
)}
     <span className="text-[clamp(9px,0.6vw,11px)] text-nier-text-light flex items-center gap-0.5">
      <Clock size={10} className="flex-shrink-0"/>
      {getRuntime()}
     </span>
    </div>

    <div className="flex items-center gap-2 whitespace-nowrap">
     <span className="text-[clamp(9px,0.6vw,11px)] text-nier-text-light tabular-nums text-right min-w-[3em]">
      {agent.tokensUsed.toLocaleString()}tk
     </span>
     {qualityCheckConfig&&(
      <span
       className="text-[clamp(9px,0.6vw,11px)] text-nier-text-light flex items-center gap-0.5"
       title={qualityCheckConfig.enabled?'品質チェックON' : '品質チェックOFF'}
      >
       {qualityCheckConfig.enabled?<Shield size={10}/>:<ShieldOff size={10}/>}
       QC
      </span>
)}
     {isRetryable&&onRetry&&(
      <button
       onClick={handleRetryClick}
       className="text-[clamp(9px,0.6vw,11px)] text-nier-accent-blue hover:text-nier-text-main flex items-center gap-0.5 px-1 py-0.5 border border-nier-border-light hover:bg-nier-bg-selected transition-colors"
       title="再試行"
      >
       <RotateCcw size={10}/>
       再試行
      </button>
)}
     <span className={cn(
      'text-[clamp(9px,0.6vw,11px)] flex items-center gap-0.5',
      status.textColor
)}>
      <StatusIcon size={10}/>
      {status.text}
     </span>
    </div>
   </div>
  </div>
)
}
