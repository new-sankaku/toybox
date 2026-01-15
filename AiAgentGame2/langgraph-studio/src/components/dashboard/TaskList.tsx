import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { cn } from '@/lib/utils'

interface AgentTasks {
  agent: string
  completed: number
  total: number
  status: 'pending' | 'running' | 'completed'
}

export default function TaskList(): JSX.Element {
  // Mock data - tasks per agent
  const agentTasks: AgentTasks[] = [
    { agent: 'Concept', completed: 3, total: 3, status: 'completed' },
    { agent: 'Design', completed: 5, total: 5, status: 'completed' },
    { agent: 'Scenario', completed: 4, total: 8, status: 'running' },
    { agent: 'Character', completed: 0, total: 6, status: 'pending' },
    { agent: 'World', completed: 0, total: 4, status: 'pending' },
    { agent: 'TaskSplit', completed: 0, total: 3, status: 'pending' }
  ]

  const totalCompleted = agentTasks.reduce((acc, a) => acc + a.completed, 0)
  const totalTasks = agentTasks.reduce((acc, a) => acc + a.total, 0)
  const runningCount = agentTasks.filter(a => a.status === 'running').length

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>Tasks</DiamondMarker>
        <span className="ml-auto text-nier-caption text-nier-text-light">
          {runningCount > 0 && <span className="text-nier-accent-orange mr-2">{runningCount}実行中</span>}
          <span className="text-nier-accent-green">{totalCompleted}/{totalTasks}</span>
        </span>
      </CardHeader>
      <CardContent className="space-y-2">
        {agentTasks.map((item) => {
          const progress = item.total > 0 ? (item.completed / item.total) * 100 : 0
          return (
            <div key={item.agent} className="flex items-center gap-3">
              <span className={cn(
                'text-nier-small w-20 truncate',
                item.status === 'running' && 'text-nier-accent-orange',
                item.status === 'completed' && 'text-nier-text-light',
                item.status === 'pending' && 'text-nier-text-light'
              )}>
                {item.agent}
              </span>
              <Progress value={progress} className="flex-1 h-1.5" />
              <span className={cn(
                'text-nier-caption w-12 text-right',
                progress === 100 ? 'text-nier-accent-green' : 'text-nier-text-light'
              )}>
                {item.completed}/{item.total}
              </span>
            </div>
          )
        })}
      </CardContent>
    </Card>
  )
}
