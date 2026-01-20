import{Clock,Play,CheckCircle,AlertCircle,Loader2}from'lucide-react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{cn}from'@/lib/utils'

export interface QueuedTask{
 id:string
 name:string
 description?:string
 status:'queued' | 'running' | 'completed' | 'failed'
 priority?:'high' | 'normal' | 'low'
 estimatedTime?:number // seconds
 startedAt?:string
 completedAt?:string
}

interface TaskQueueProps{
 tasks:QueuedTask[]
 title?:string
 showCompleted?:boolean
 maxVisible?:number
}

const statusConfig = {
 queued:{icon:Clock,color:'text-nier-text-light',bg:'bg-nier-bg-selected'},
 running:{icon:Loader2,color:'text-nier-accent-orange',bg:'bg-nier-accent-orange/10'},
 completed:{icon:CheckCircle,color:'text-nier-accent-green',bg:'bg-nier-accent-green/10'},
 failed:{icon:AlertCircle,color:'text-nier-accent-red',bg:'bg-nier-accent-red/10'}
}

const priorityColors = {
 high:'bg-nier-accent-red',
 normal:'bg-nier-accent-blue',
 low:'bg-nier-text-light'
}

export function TaskQueue({
 tasks,
 title = 'TASK QUEUE',
 showCompleted = false,
 maxVisible = 10
}:TaskQueueProps){
 const filteredTasks = showCompleted
  ? tasks
  : tasks.filter((t) => t.status !== 'completed')

 const visibleTasks = filteredTasks.slice(0,maxVisible)
 const hiddenCount = filteredTasks.length - maxVisible

 const runningCount = tasks.filter((t) => t.status === 'running').length
 const queuedCount = tasks.filter((t) => t.status === 'queued').length

 return(
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between w-full">
     <span className="text-nier-small">{title}</span>
     <div className="flex items-center gap-3 text-nier-caption">
      {runningCount > 0 && (
       <span className="text-nier-accent-orange">{runningCount} running</span>
      )}
      {queuedCount > 0 && (
       <span className="text-nier-text-header/70">{queuedCount} queued</span>
      )}
     </div>
    </div>
   </CardHeader>

   <CardContent className="p-0">
    {visibleTasks.length === 0 ? (
     <div className="px-4 py-6 text-center">
      <p className="text-nier-small text-nier-text-light">
       No tasks in queue
      </p>
     </div>
    ) : (
     <div className="divide-y divide-nier-border-light">
      {visibleTasks.map((task,index) => {
       const config = statusConfig[task.status]
       const Icon = config.icon

       return(
        <div
         key={task.id}
         className={cn(
          'flex items-center gap-3 px-4 py-3',
          config.bg
         )}
        >
         {/* Queue number / Status icon */}
         <div className="flex-shrink-0 w-8 flex justify-center">
          {task.status === 'queued' ? (
           <span className="text-nier-small text-nier-text-light">
            #{index + 1}
           </span>
          ) : (
           <Icon
            size={16}
            className={cn(
             config.color,
             task.status === 'running' && 'animate-spin'
            )}
           />
          )}
         </div>

         {/* Priority indicator */}
         {task.priority && (
          <div
           className={cn(
            'w-1 h-6 flex-shrink-0',
            priorityColors[task.priority]
           )}
          />
         )}

         {/* Task info */}
         <div className="flex-1 min-w-0">
          <div className="text-nier-small font-medium truncate">
           {task.name}
          </div>
          {task.description && (
           <p className="text-nier-caption text-nier-text-light truncate">
            {task.description}
           </p>
          )}
         </div>

         {/* Estimated time */}
         {task.estimatedTime && task.status === 'queued' && (
          <span className="text-nier-caption text-nier-text-light flex-shrink-0">
           ~{Math.ceil(task.estimatedTime / 60)}m
          </span>
         )}
        </div>
       )
      })}
     </div>
    )}

    {/* Hidden count */}
    {hiddenCount > 0 && (
     <div className="px-4 py-2 text-center border-t border-nier-border-light">
      <span className="text-nier-caption text-nier-text-light">
       +{hiddenCount} more tasks
      </span>
     </div>
    )}
   </CardContent>
  </Card>
 )
}
