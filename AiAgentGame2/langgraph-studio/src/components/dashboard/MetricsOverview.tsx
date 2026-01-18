import { useEffect, useState } from 'react'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { useProjectStore } from '@/stores/projectStore'
import { useMetricsStore } from '@/stores/metricsStore'
import { metricsApi, type ApiProjectMetrics } from '@/services/apiService'
import { formatNumber, cn } from '@/lib/utils'

export default function MetricsOverview(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { projectMetrics, setProjectMetrics, isLoading } = useMetricsStore()
  const [initialLoading, setInitialLoading] = useState(true)

  // Initial data fetch only (no polling) - rely on WebSocket for updates
  useEffect(() => {
    if (!currentProject) {
      setProjectMetrics(null)
      setInitialLoading(false)
      return
    }

    const fetchMetrics = async () => {
      setInitialLoading(true)
      try {
        const data = await metricsApi.getByProject(currentProject.id)
        // Convert API format to store format
        setProjectMetrics({
          projectId: currentProject.id,
          totalTokensUsed: data.totalTokensUsed,
          estimatedTotalTokens: data.estimatedTotalTokens,
          completedTasks: data.completedTasks,
          totalTasks: data.totalTasks,
          progressPercent: data.progressPercent,
          currentPhase: data.currentPhase,
          phaseName: data.phaseName
        })
      } catch (error) {
        console.error('Failed to fetch metrics:', error)
        setProjectMetrics(null)
      } finally {
        setInitialLoading(false)
      }
    }

    fetchMetrics()
  }, [currentProject?.id, setProjectMetrics])

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>メトリクス</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  const metrics = projectMetrics
  const actualTokens = metrics?.totalTokensUsed || 0
  const estimatedTokens = metrics?.estimatedTotalTokens || 0
  const completedTasks = metrics?.completedTasks || 0
  const totalTasks = metrics?.totalTasks || 0
  const progress = metrics?.progressPercent || 0

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>メトリクス</DiamondMarker>
      </CardHeader>
      <CardContent>
        {(initialLoading || isLoading) && !metrics ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            読み込み中...
          </div>
        ) : (
          <>
            <div className="space-y-2 mb-4">
              <div className="nier-status-row">
                <span className="nier-status-label">消費トークン:</span>
                <span className="nier-status-value">{formatNumber(actualTokens)}</span>
              </div>
              <div className="nier-status-row">
                <span className="nier-status-label">予想トークン:</span>
                <span className="nier-status-value">{formatNumber(estimatedTokens)}</span>
              </div>
              {metrics?.phaseName && (
                <div className="nier-status-row">
                  <span className="nier-status-label">フェーズ:</span>
                  <span className="nier-status-value">{metrics.phaseName}</span>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <div className="flex justify-between text-nier-small">
                <span className="text-nier-text-light">タスク:</span>
                <span>{completedTasks}/{totalTasks} 完了</span>
              </div>
              <div className="flex items-center gap-3">
                <Progress value={progress} className="flex-1" />
                <span className="text-nier-small text-nier-text-light w-10">
                  {progress}%
                </span>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  )
}
