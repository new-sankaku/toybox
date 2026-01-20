import { useEffect, useState } from 'react'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { CategoryMarker } from '@/components/ui/CategoryMarker'
import { Progress } from '@/components/ui/Progress'
import { useProjectStore } from '@/stores/projectStore'
import { useAgentStore } from '@/stores/agentStore'
import { agentApi } from '@/services/apiService'
import { formatNumber, cn } from '@/lib/utils'
import { Clock } from 'lucide-react'
import type { Agent, AgentStatus } from '@/types/agent'

const statusLabels: Record<AgentStatus, string> = {
  running: '実行中',
  pending: '待機',
  completed: '完了',
  failed: '失敗',
  blocked: 'ブロック'
}

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
  const { agents, setAgents, isLoading } = useAgentStore()
  const [initialLoading, setInitialLoading] = useState(true)
  const [, setTick] = useState(0)

  useEffect(() => {
    if (!currentProject) {
      setAgents([])
      setInitialLoading(false)
      return
    }

    const fetchInitialAgents = async () => {
      setInitialLoading(true)
      try {
        const data = await agentApi.listByProject(currentProject.id)
        const agentsData: Agent[] = data.map(a => ({
          id: a.id,
          projectId: a.projectId,
          type: a.type,
          phase: a.phase,
          status: a.status as AgentStatus,
          progress: a.progress,
          currentTask: a.currentTask,
          tokensUsed: a.tokensUsed,
          startedAt: a.startedAt,
          completedAt: a.completedAt,
          error: a.error,
          metadata: a.metadata
        }))
        setAgents(agentsData)
      } catch (error) {
        console.error('Failed to fetch agents:', error)
      } finally {
        setInitialLoading(false)
      }
    }

    fetchInitialAgents()
  }, [currentProject?.id, setAgents])

  useEffect(() => {
    const activeCount = agents.filter(a => a.status === 'running').length
    if (activeCount === 0) return

    const interval = setInterval(() => {
      setTick(t => t + 1)
    }, 1000)

    return () => clearInterval(interval)
  }, [agents])

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

  const projectAgents = agents.filter(a => a.projectId === currentProject.id)
  const activeAgents = projectAgents.filter(a => a.status === 'running' || a.status === 'pending')
  const runningCount = activeAgents.filter(a => a.status === 'running').length

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>Agents ({activeAgents.length})</DiamondMarker>
        {runningCount > 0 && (
          <span className="ml-auto text-nier-caption text-nier-accent-orange animate-pulse">
            {runningCount}実行中
          </span>
        )}
      </CardHeader>
      <CardContent>
        {(initialLoading || isLoading) && agents.length === 0 ? (
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
              const isRunning = agent.status === 'running'
              return (
                <div
                  key={agent.id}
                  className={cn(
                    'flex items-center gap-2 px-2 py-1.5 bg-nier-bg-main border border-nier-border-light cursor-pointer hover:bg-nier-bg-selected transition-colors',
                    isRunning && 'animate-nier-pulse'
                  )}
                >
                  <CategoryMarker status={agent.status === 'completed' ? 'complete' : agent.status} />
                  <span className="text-nier-small font-medium truncate flex-1 min-w-0">{displayName}</span>
                  <div className="flex items-center gap-2 ml-auto shrink-0">
                    <span className="text-nier-caption w-12 text-nier-text-light">
                      {statusLabels[agent.status] || agent.status}
                    </span>
                    {isRunning && agent.progress !== null ? (
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
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
