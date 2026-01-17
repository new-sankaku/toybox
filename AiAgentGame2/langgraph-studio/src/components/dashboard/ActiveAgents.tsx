import { useEffect, useState } from 'react'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { CategoryMarker } from '@/components/ui/CategoryMarker'
import { Progress } from '@/components/ui/Progress'
import { useProjectStore } from '@/stores/projectStore'
import { agentApi, type ApiAgent } from '@/services/apiService'
import { formatNumber, cn } from '@/lib/utils'
import { Clock } from 'lucide-react'

type AgentStatus = 'running' | 'pending' | 'completed' | 'failed' | 'blocked'

const statusLabels: Record<AgentStatus, string> = {
  running: '実行中',
  pending: '待機',
  completed: '完了',
  failed: '失敗',
  blocked: 'ブロック'
}

// Format elapsed time
const formatElapsedTime = (startedAt: string | null, completedAt: string | null): string => {
  if (!startedAt) return '-'
  const start = new Date(startedAt).getTime()
  const end = completedAt ? new Date(completedAt).getTime() : Date.now()
  const seconds = Math.floor((end - start) / 1000)
  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes < 60) return `${minutes}分${remainingSeconds}秒`
  const hours = Math.floor(minutes / 60)
  const remainingMinutes = minutes % 60
  return `${hours}時${remainingMinutes}分`
}

export default function ActiveAgents(): JSX.Element {
  const { currentProject } = useProjectStore()
  const [agents, setAgents] = useState<ApiAgent[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!currentProject) {
      setAgents([])
      return
    }

    const fetchAgents = async () => {
      setLoading(true)
      try {
        const data = await agentApi.listByProject(currentProject.id)
        setAgents(data)
      } catch (error) {
        console.error('Failed to fetch agents:', error)
        setAgents([])
      } finally {
        setLoading(false)
      }
    }

    fetchAgents()
    // Poll every 5 seconds
    const interval = setInterval(fetchAgents, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>Agents</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  // Only show running and pending agents
  const activeAgents = agents.filter(a => a.status === 'running' || a.status === 'pending')
  const runningCount = activeAgents.filter(a => a.status === 'running').length

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>Agents ({activeAgents.length})</DiamondMarker>
        {runningCount > 0 && (
          <span className="ml-auto text-nier-caption text-nier-accent-orange">
            {runningCount}実行中
          </span>
        )}
      </CardHeader>
      <CardContent>
        {loading && agents.length === 0 ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            読み込み中...
          </div>
        ) : activeAgents.length === 0 ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            待機・実行中なし
          </div>
        ) : (
          <div className="space-y-1 max-h-40 overflow-y-auto">
            {activeAgents.map((agent) => {
              const displayName = (agent.metadata?.displayName as string) || agent.type
              const elapsed = formatElapsedTime(agent.startedAt, agent.completedAt)
              return (
                <div
                  key={agent.id}
                  className="flex items-center gap-2 px-2 py-1.5 bg-nier-bg-main border border-nier-border-light cursor-pointer hover:bg-nier-bg-selected transition-colors"
                >
                  <CategoryMarker status={agent.status === 'completed' ? 'complete' : agent.status} />
                  <span className="text-nier-small font-medium truncate w-24">{displayName}</span>
                  <span className="text-nier-caption w-12 text-nier-text-light">
                    {statusLabels[agent.status as AgentStatus] || agent.status}
                  </span>
                  {agent.status === 'running' && agent.progress !== null ? (
                    <div className="flex items-center gap-1 w-16">
                      <Progress value={agent.progress} className="h-1 w-10" />
                      <span className="text-nier-caption text-nier-text-light">{agent.progress}%</span>
                    </div>
                  ) : (
                    <span className="w-16" />
                  )}
                  <span className="text-nier-caption text-nier-text-light flex items-center gap-0.5 w-14">
                    <Clock size={10} />
                    {elapsed}
                  </span>
                  <span className="text-nier-caption text-nier-text-light w-12 text-right">
                    {formatNumber(agent.tokensUsed)}tk
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
