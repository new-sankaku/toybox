import { useEffect, useState } from 'react'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { useProjectStore } from '@/stores/projectStore'
import { metricsApi, agentApi, type ApiProjectMetrics, type ApiAgent } from '@/services/apiService'
import { cn } from '@/lib/utils'

interface Phase {
  id: number
  name: string
  progress: number
  status: 'current' | 'pending' | 'completed'
}

export default function PhaseProgress(): JSX.Element {
  const { currentProject } = useProjectStore()
  const [metrics, setMetrics] = useState<ApiProjectMetrics | null>(null)
  const [agents, setAgents] = useState<ApiAgent[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!currentProject) {
      setMetrics(null)
      setAgents([])
      return
    }

    const fetchData = async () => {
      setLoading(true)
      try {
        const [metricsData, agentsData] = await Promise.all([
          metricsApi.getByProject(currentProject.id),
          agentApi.listByProject(currentProject.id)
        ])
        setMetrics(metricsData)
        setAgents(agentsData)
      } catch (error) {
        console.error('Failed to fetch data:', error)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>フェーズ進捗</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  // Calculate phase progress from agents
  const currentPhase = metrics?.currentPhase || currentProject.currentPhase || 1
  const overallProgress = metrics?.progressPercent || 0

  const phases: Phase[] = [
    { id: 1, name: 'Phase 1', progress: currentPhase > 1 ? 100 : currentPhase === 1 ? overallProgress : 0, status: currentPhase === 1 ? 'current' : currentPhase > 1 ? 'completed' : 'pending' },
    { id: 2, name: 'Phase 2', progress: currentPhase > 2 ? 100 : currentPhase === 2 ? overallProgress : 0, status: currentPhase === 2 ? 'current' : currentPhase > 2 ? 'completed' : 'pending' },
    { id: 3, name: 'Phase 3', progress: currentPhase > 3 ? 100 : currentPhase === 3 ? overallProgress : 0, status: currentPhase === 3 ? 'current' : currentPhase > 3 ? 'completed' : 'pending' }
  ]

  // Find running agent
  const runningAgent = agents.find(a => a.status === 'running')
  const currentAgentName = runningAgent ? ((runningAgent.metadata?.displayName as string) || runningAgent.type) : null
  const currentAgentProgress = runningAgent?.progress || 0

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>フェーズ進捗</DiamondMarker>
        <span className="ml-auto text-nier-caption text-nier-text-light">
          全体 {overallProgress}%
        </span>
      </CardHeader>
      <CardContent className="space-y-3">
        {loading && !metrics ? (
          <div className="text-nier-text-light text-center py-2 text-nier-small">
            読み込み中...
          </div>
        ) : (
          <>
            {/* Phase Bars */}
            {phases.map((phase) => (
              <div key={phase.id} className="flex items-center gap-3">
                <span className="text-nier-caption w-16 text-nier-text-light">
                  {phase.name}
                </span>
                <Progress
                  value={phase.progress}
                  className="flex-1 h-1.5"
                />
                <span className="text-nier-caption text-nier-text-light w-8 text-right">
                  {phase.progress}%
                </span>
              </div>
            ))}

            {/* Current Agent */}
            {currentAgentName && (
              <div className="pt-2 border-t border-nier-border-light">
                <div className="flex justify-between text-nier-caption mb-1">
                  <span className="text-nier-text-light">実行中:</span>
                  <span className="text-nier-accent-orange">{currentAgentName} ({currentAgentProgress}%)</span>
                </div>
                <Progress value={currentAgentProgress} className="h-1" />
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
