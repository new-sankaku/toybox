import{useActivityFeedStore,type ActivityType}from'@/stores/activityFeedStore'
import{cn}from'@/lib/utils'
import{Play,CheckCircle,XCircle,Pause,AlertCircle,ArrowRight,Clock,MessageCircle,DollarSign,RotateCcw}from'lucide-react'

const typeConfig:Record<ActivityType,{icon:typeof Play;color:string}>={
 agent_started:{icon:Play,color:'text-nier-accent-orange'},
 agent_completed:{icon:CheckCircle,color:'text-nier-accent-green'},
 agent_failed:{icon:XCircle,color:'text-nier-accent-red'},
 agent_paused:{icon:Pause,color:'text-nier-accent-blue'},
 agent_resumed:{icon:Play,color:'text-nier-accent-orange'},
 agent_retry:{icon:RotateCcw,color:'text-nier-accent-blue'},
 checkpoint_created:{icon:AlertCircle,color:'text-nier-accent-yellow'},
 checkpoint_resolved:{icon:CheckCircle,color:'text-nier-accent-green'},
 phase_changed:{icon:ArrowRight,color:'text-nier-accent-blue'},
 agent_waiting_response:{icon:MessageCircle,color:'text-nier-accent-yellow'},
 agent_waiting_provider:{icon:Clock,color:'text-nier-accent-blue'},
 agent_progress:{icon:Play,color:'text-nier-accent-orange'},
 intervention_agent_question:{icon:MessageCircle,color:'text-nier-accent-orange'},
 budget_warning:{icon:DollarSign,color:'text-nier-accent-orange'}
}

function formatTimestamp(ts:string):string{
 const d=new Date(ts)
 const h=d.getHours().toString().padStart(2,'0')
 const m=d.getMinutes().toString().padStart(2,'0')
 const s=d.getSeconds().toString().padStart(2,'0')
 return`${h}:${m}:${s}`
}

export function ActivityFeed():JSX.Element{
 const{events}=useActivityFeedStore()

 if(events.length===0){
  return(
   <div className="text-nier-caption text-nier-text-light text-center py-4">
    イベントはまだありません
   </div>
)
 }

 return(
  <div className="space-y-0.5 max-h-[300px] overflow-y-auto">
   {events.map((event)=>{
    const config=typeConfig[event.type]||typeConfig.agent_started
    const Icon=config.icon
    return(
     <div key={event.id} className="flex items-start gap-1.5 px-1 py-1 text-[11px] animate-nier-fade-in">
      <span className="text-nier-text-light flex-shrink-0" style={{width:'clamp(40px,4vw,60px)'}}>
       {formatTimestamp(event.timestamp)}
      </span>
      <Icon size={12} className={cn('flex-shrink-0 mt-0.5',config.color)}/>
      <span className="text-nier-text-main leading-tight truncate">
       {event.message}
      </span>
     </div>
)
   })}
  </div>
)
}
