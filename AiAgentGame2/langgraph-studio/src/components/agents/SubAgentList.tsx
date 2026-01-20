import{ChevronRight,Play,CheckCircle,XCircle,Clock,Pause}from'lucide-react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{Progress}from'@/components/ui/Progress'
import{cn}from'@/lib/utils'
import type{Agent,AgentStatus}from'@/types/agent'

interface SubAgentListProps{
 agents:Agent[]
 onSelectAgent?:(agent:Agent)=>void
 selectedAgentId?:string
 title?:string
}

const statusIcons:Record<AgentStatus,typeof Play>={
 pending:Clock,
 running:Play,
 completed:CheckCircle,
 failed:XCircle,
 blocked:Pause
}

const statusColors:Record<AgentStatus,string>={
 pending:'text-nier-text-light',
 running:'text-nier-accent-orange',
 completed:'text-nier-accent-green',
 failed:'text-nier-accent-red',
 blocked:'text-nier-accent-yellow'
}

export function SubAgentList({
 agents,
 onSelectAgent,
 selectedAgentId,
 title='SUB-AGENTS'
}:SubAgentListProps){
 if(agents.length===0){
  return(
   <Card>
    <CardHeader>
     <span className="text-nier-small">{title}</span>
    </CardHeader>
    <CardContent>
     <p className="text-nier-small text-nier-text-light text-center py-4">
      No sub-agents active
     </p>
    </CardContent>
   </Card>
)
 }

 return(
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between w-full">
     <span className="text-nier-small">{title}</span>
     <span className="text-nier-caption text-nier-text-header/70">
      {agents.filter((a)=>a.status==='running').length} active
     </span>
    </div>
   </CardHeader>
   <CardContent className="p-0">
    <div className="divide-y divide-nier-border-light">
     {agents.map((agent)=>{
      const Icon=statusIcons[agent.status]
      const isSelected=selectedAgentId===agent.id

      return(
       <div
        key={agent.id}
        className={cn(
         'flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors',
         'hover:bg-nier-bg-selected',
         isSelected&&'bg-nier-bg-selected'
)}
        onClick={()=>onSelectAgent?.(agent)}
       >
        {/* Status Icon */}
        <Icon
         size={16}
         className={cn(
          statusColors[agent.status],
          agent.status==='running'&&'animate-nier-pulse'
)}
        />

        {/* Info */}
        <div className="flex-1 min-w-0">
         <div className="flex items-center gap-2">
          <span className="text-nier-small font-medium truncate">
           {agent.name||agent.type}
          </span>
          <span className="text-nier-caption text-nier-text-light">
           {agent.type}
          </span>
         </div>

         {/* Progress for running agents */}
         {agent.status==='running'&&(
          <div className="mt-1">
           <Progress value={agent.progress} size="sm"/>
          </div>
)}

         {/* Current task */}
         {agent.currentTask&&(
          <p className="text-nier-caption text-nier-text-light truncate mt-0.5">
           {agent.currentTask}
          </p>
)}
        </div>

        {/* Progress percentage */}
        <div className="text-nier-caption text-nier-text-light">
         {Math.round(agent.progress)}%
        </div>

        {/* Arrow */}
        {onSelectAgent&&(
         <ChevronRight size={16} className="text-nier-text-light"/>
)}
       </div>
)
     })}
    </div>
   </CardContent>
  </Card>
)
}
