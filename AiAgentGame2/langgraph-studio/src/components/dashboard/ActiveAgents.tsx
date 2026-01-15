import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { CategoryMarker } from '@/components/ui/CategoryMarker'
import { Progress } from '@/components/ui/Progress'
import { formatNumber, cn } from '@/lib/utils'

type AgentStatus = 'running' | 'pending' | 'completed' | 'failed' | 'blocked'

interface DashboardAgent {
  id: string
  name: string
  status: AgentStatus
  progress: number | null
  tokensUsed: number
  tokensEstimated: number
}

const statusLabels: Record<AgentStatus, string> = {
  running: '実行中',
  pending: '待機',
  completed: '完了',
  failed: '失敗',
  blocked: 'ブロック'
}

export default function ActiveAgents(): JSX.Element {
  // Mock data - including all agents
  const agents: DashboardAgent[] = [
    { id: '1', name: 'Concept', status: 'completed', progress: 100, tokensUsed: 5200, tokensEstimated: 5000 },
    { id: '2', name: 'Design', status: 'completed', progress: 100, tokensUsed: 8400, tokensEstimated: 8000 },
    { id: '3', name: 'Scenario', status: 'running', progress: 67, tokensUsed: 12450, tokensEstimated: 18000 },
    { id: '4', name: 'Character', status: 'pending', progress: null, tokensUsed: 0, tokensEstimated: 10000 },
    { id: '5', name: 'World', status: 'pending', progress: null, tokensUsed: 0, tokensEstimated: 12000 },
    { id: '6', name: 'TaskSplit', status: 'pending', progress: null, tokensUsed: 0, tokensEstimated: 6000 }
  ]

  const runningCount = agents.filter(a => a.status === 'running').length
  const completedCount = agents.filter(a => a.status === 'completed').length

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>Agents</DiamondMarker>
        <span className="ml-auto text-nier-caption text-nier-text-light">
          {runningCount > 0 && <span className="text-nier-accent-orange mr-2">{runningCount}実行中</span>}
          <span className="text-nier-accent-green">{completedCount}/{agents.length}完了</span>
        </span>
      </CardHeader>
      <CardContent>
        <div className="flex gap-3 flex-wrap">
          {agents.map((agent) => (
            <div
              key={agent.id}
              className={cn(
                'flex items-center gap-2 px-3 py-2 bg-nier-bg-main border border-nier-border-light min-w-[180px] cursor-pointer hover:bg-nier-bg-selected transition-colors',
                agent.status === 'completed' && 'opacity-60'
              )}
            >
              <CategoryMarker status={agent.status === 'completed' ? 'complete' : agent.status} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-nier-small font-medium truncate">{agent.name}</span>
                  <span className={cn(
                    'text-nier-caption shrink-0',
                    agent.status === 'running' && 'text-nier-accent-orange',
                    agent.status === 'completed' && 'text-nier-accent-green',
                    agent.status === 'failed' && 'text-nier-accent-red',
                    agent.status === 'pending' && 'text-nier-text-light'
                  )}>
                    {statusLabels[agent.status]}
                  </span>
                </div>
                <div className="text-nier-caption text-nier-text-light">
                  {formatNumber(agent.tokensUsed)}tk
                </div>
                {agent.status === 'running' && agent.progress !== null && (
                  <Progress value={agent.progress} className="h-1 mt-1" />
                )}
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}
