import{useMemo}from'react'
import{cn}from'@/lib/utils'
import{CheckCircle,Play,Clock}from'lucide-react'
import type{Agent}from'@/types/agent'
import type{UIPhase}from'@/services/apiService'

interface PhasePipelineBarProps{
 uiPhases:UIPhase[]
 agentsByPhase:Record<string,Agent[]>
 workersByParent:Record<string,Agent[]>
}

type PhaseStatus='pending'|'running'|'completed'

function getPhaseStatus(agents:Agent[],workers:Record<string,Agent[]>):PhaseStatus{
 if(agents.length===0)return'pending'
 const allAgents=[...agents]
 for(const a of agents){
  const w=workers[a.id]
  if(w)allAgents.push(...w)
 }
 const allCompleted=allAgents.every(a=>a.status==='completed')
 if(allCompleted)return'completed'
 const anyActive=allAgents.some(a=>
  a.status==='running'||a.status==='waiting_approval'||a.status==='waiting_response'||a.status==='waiting_provider'
)
 if(anyActive)return'running'
 const anyStarted=allAgents.some(a=>a.status!=='pending')
 if(anyStarted)return'running'
 return'pending'
}

function getPhaseProgress(agents:Agent[],workers:Record<string,Agent[]>):number{
 if(agents.length===0)return 0
 const allAgents=[...agents]
 for(const a of agents){
  const w=workers[a.id]
  if(w)allAgents.push(...w)
 }
 if(allAgents.length===0)return 0
 const totalProgress=allAgents.reduce((sum,a)=>sum+a.progress,0)
 return Math.round(totalProgress/allAgents.length)
}

const statusIcons={
 pending:Clock,
 running:Play,
 completed:CheckCircle
}

const statusColors={
 pending:'text-nier-text-light',
 running:'text-nier-accent-orange',
 completed:'text-nier-accent-green'
}

const barColors={
 pending:'bg-nier-border-dark',
 running:'bg-nier-accent-orange',
 completed:'bg-nier-accent-green'
}

const connectorColors={
 pending:'bg-nier-border-light',
 running:'bg-nier-accent-orange/50',
 completed:'bg-nier-accent-green/50'
}

export function PhasePipelineBar({uiPhases,agentsByPhase,workersByParent}:PhasePipelineBarProps):JSX.Element|null{
 const phaseData=useMemo(()=>{
  return uiPhases.map((phase,idx)=>{
   const agents=agentsByPhase[phase.id]||[]
   const status=getPhaseStatus(agents,workersByParent)
   const progress=getPhaseProgress(agents,workersByParent)
   return{phase,idx,status,progress,agents}
  })
 },[uiPhases,agentsByPhase,workersByParent])

 if(phaseData.length===0)return null

 return(
  <div className="mb-3 bg-nier-bg-panel border border-nier-border-light px-4 py-2.5">
   <div className="flex items-center gap-1">
    {phaseData.map((data,i)=>{
     const Icon=statusIcons[data.status]
     return(
      <div key={data.phase.id} className="contents">
       {i>0&&(
        <div className={cn('h-0.5 w-4 flex-shrink-0',connectorColors[data.status])}/>
)}
       <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5 mb-1">
         <Icon size={12} className={cn(statusColors[data.status],data.status==='running'&&'animate-pulse')}/>
         <span className={cn('text-[11px] font-medium truncate',statusColors[data.status])}>
          PHASE {data.idx+1}
         </span>
         <span className="text-[10px] text-nier-text-light truncate hidden md:inline">
          {data.phase.label}
         </span>
         <span className={cn('text-[10px] ml-auto flex-shrink-0',statusColors[data.status])}>
          {data.status==='completed'?'完了':data.status==='running'?`${data.progress}%`:'待機'}
         </span>
        </div>
        <div className="h-1 bg-nier-border-light overflow-hidden">
         <div
          className={cn('h-full transition-all duration-500',barColors[data.status])}
          style={{width:`${data.progress}%`}}
         />
        </div>
       </div>
      </div>
)
    })}
   </div>
  </div>
)
}
