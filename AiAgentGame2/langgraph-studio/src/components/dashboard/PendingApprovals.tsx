import { useEffect, useState } from 'react'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { CategoryMarker } from '@/components/ui/CategoryMarker'
import { useProjectStore } from '@/stores/projectStore'
import { useNavigationStore } from '@/stores/navigationStore'
import { useCheckpointStore } from '@/stores/checkpointStore'
import { checkpointApi, type ApiCheckpoint } from '@/services/apiService'
import type { Checkpoint, CheckpointType, CheckpointStatus } from '@/types/checkpoint'
import { cn } from '@/lib/utils'

export default function PendingApprovals(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { navigateToCheckpoint } = useNavigationStore()
  const { checkpoints, setCheckpoints, isLoading } = useCheckpointStore()
  const [initialLoading, setInitialLoading] = useState(true)
  // For updating waiting time display
  const [, setTick] = useState(0)

  // Initial data fetch only (no polling) - rely on WebSocket for updates
  useEffect(() => {
    if (!currentProject) {
      setCheckpoints([])
      setInitialLoading(false)
      return
    }

    const fetchCheckpoints = async () => {
      setInitialLoading(true)
      try {
        const data = await checkpointApi.listByProject(currentProject.id)
        // Convert API format to store format
        const checkpointsData: Checkpoint[] = data.map(cp => ({
          id: cp.id,
          projectId: cp.projectId,
          agentId: cp.agentId,
          type: cp.type as CheckpointType,
          title: cp.title,
          description: cp.description,
          status: cp.status as CheckpointStatus,
          content: cp.content,
          feedback: cp.feedback,
          createdAt: cp.createdAt,
          updatedAt: cp.updatedAt
        }))
        setCheckpoints(checkpointsData)
      } catch (error) {
        console.error('Failed to fetch checkpoints:', error)
      } finally {
        setInitialLoading(false)
      }
    }

    fetchCheckpoints()
  }, [currentProject?.id, setCheckpoints])

  // Timer for updating waiting time display (every minute)
  useEffect(() => {
    const pendingCount = checkpoints.filter(cp => cp.status === 'pending').length
    if (pendingCount === 0) return

    const interval = setInterval(() => {
      setTick(t => t + 1)
    }, 60000)

    return () => clearInterval(interval)
  }, [checkpoints])

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>承認待ち</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  // Filter pending checkpoints for current project
  const projectCheckpoints = checkpoints.filter(cp => cp.projectId === currentProject.id)
  const pendingCheckpoints = projectCheckpoints.filter(cp => cp.status === 'pending')

  const formatWaitingTime = (createdAt: string) => {
    const created = new Date(createdAt)
    const now = new Date()
    const diffMs = now.getTime() - created.getTime()
    const diffMins = Math.floor(diffMs / 60000)
    const hours = Math.floor(diffMins / 60)
    const mins = diffMins % 60
    if (hours > 0) {
      return `${hours}h ${mins}m`
    }
    return `${mins}m`
  }

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>承認待ち ({pendingCheckpoints.length})</DiamondMarker>
        {pendingCheckpoints.length > 0 && (
          <span className="ml-auto text-nier-caption text-nier-accent-orange animate-pulse">
            要確認
          </span>
        )}
      </CardHeader>
      <CardContent>
        {(initialLoading || isLoading) && checkpoints.length === 0 ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            読み込み中...
          </div>
        ) : pendingCheckpoints.length === 0 ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            承認待ちなし
          </div>
        ) : (
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {pendingCheckpoints.slice(0, 5).map((checkpoint) => (
              <div
                key={checkpoint.id}
                className={cn(
                  'nier-list-item cursor-pointer hover:bg-nier-bg-selected',
                  'animate-nier-fade-in'
                )}
                onClick={() => navigateToCheckpoint(checkpoint.id)}
              >
                <CategoryMarker status="pending" />
                <div className="flex-1 min-w-0">
                  <div className="text-nier-small truncate">{checkpoint.title}</div>
                </div>
                <div className="text-nier-caption text-nier-accent-orange shrink-0">
                  {formatWaitingTime(checkpoint.createdAt)}
                </div>
              </div>
            ))}
            {pendingCheckpoints.length > 5 && (
              <button
                onClick={() => navigateToCheckpoint(pendingCheckpoints[0].id)}
                className="w-full text-center text-nier-caption text-nier-text-light hover:underline py-1"
              >
                他 {pendingCheckpoints.length - 5} 件を表示...
              </button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
