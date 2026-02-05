import{Clock,Cpu,Zap,TrendingUp}from'lucide-react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{Progress}from'@/components/ui/Progress'
import type{AgentMetrics as AgentMetricsType}from'@/types/agent'

interface AgentMetricsProps{
 metrics:AgentMetricsType
 showHeader?:boolean
}

export function AgentMetrics({metrics,showHeader=true}:AgentMetricsProps){
 const completionRate=metrics.totalTasks>0
  ?(metrics.completedTasks/metrics.totalTasks)*100
  : 0

 const formatTime=(seconds:number):string=>{
  if(seconds<60)return`${seconds}s`
  if(seconds<3600)return`${Math.floor(seconds/60)}m ${seconds%60}s`
  const hours=Math.floor(seconds/3600)
  const mins=Math.floor((seconds%3600)/60)
  return`${hours}h ${mins}m`
 }

 return(
  <Card>
   {showHeader&&(
    <CardHeader>
     <span className="text-nier-small">AGENT METRICS</span>
    </CardHeader>
)}
   <CardContent className={showHeader?'' : 'pt-4'}>
    <div className="space-y-4">

     <div>
      <div className="flex items-center justify-between mb-1">
       <span className="text-nier-small text-nier-text-light">Progress</span>
       <span className="text-nier-small font-medium">{Math.round(metrics.progress)}%</span>
      </div>
      <Progress value={metrics.progress}/>
     </div>


     <div className="grid grid-cols-2 gap-3">

      <div className="flex items-center gap-2 p-2 bg-nier-bg-main">
       <Clock size={16} className="text-nier-accent-blue"/>
       <div>
        <div className="text-nier-caption text-nier-text-light">Runtime</div>
        <div className="text-nier-small font-medium">
         {formatTime(metrics.runtimeSeconds)}
        </div>
       </div>
      </div>


      <div className="flex items-center gap-2 p-2 bg-nier-bg-main">
       <Zap size={16} className="text-nier-accent-orange"/>
       <div>
        <div className="text-nier-caption text-nier-text-light">Tokens</div>
        <div className="text-nier-small font-medium">
         {metrics.tokensUsed.toLocaleString()}
        </div>
       </div>
      </div>


      <div className="flex items-center gap-2 p-2 bg-nier-bg-main">
       <Cpu size={16} className="text-nier-accent-green"/>
       <div>
        <div className="text-nier-caption text-nier-text-light">Tasks</div>
        <div className="text-nier-small font-medium">
         {metrics.completedTasks}/{metrics.totalTasks}
        </div>
       </div>
      </div>


      <div className="flex items-center gap-2 p-2 bg-nier-bg-main">
       <TrendingUp size={16} className="text-nier-accent-orange"/>
       <div>
        <div className="text-nier-caption text-nier-text-light">Rate</div>
        <div className="text-nier-small font-medium">
         {Math.round(completionRate)}%
        </div>
       </div>
      </div>
     </div>


     {metrics.currentTask&&(
      <div className="pt-3 border-t border-nier-border-light">
       <div className="text-nier-caption text-nier-text-light mb-1">
        CURRENT TASK
       </div>
       <div className="text-nier-small">{metrics.currentTask}</div>
      </div>
)}


     {metrics.estimatedRemainingSeconds>0&&(
      <div className="text-nier-caption text-nier-text-light text-center">
       Est. remaining: {formatTime(metrics.estimatedRemainingSeconds)}
      </div>
)}
    </div>
   </CardContent>
  </Card>
)
}
