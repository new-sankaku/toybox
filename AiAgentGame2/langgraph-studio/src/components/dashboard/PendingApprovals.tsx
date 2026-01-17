import { useEffect, useState } from 'react'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { CategoryMarker } from '@/components/ui/CategoryMarker'
import { useProjectStore } from '@/stores/projectStore'
import { useNavigationStore } from '@/stores/navigationStore'
import { checkpointApi, type ApiCheckpoint } from '@/services/apiService'

export default function PendingApprovals(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { navigateToCheckpoint } = useNavigationStore()
  const [checkpoints, setCheckpoints] = useState<ApiCheckpoint[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!currentProject) {
      setCheckpoints([])
      return
    }

    const fetchCheckpoints = async () => {
      setLoading(true)
      try {
        const data = await checkpointApi.listByProject(currentProject.id)
        // Filter only pending checkpoints
        const pending = data.filter(cp => cp.status === 'pending')
        setCheckpoints(pending)
      } catch (error) {
        console.error('Failed to fetch checkpoints:', error)
        setCheckpoints([])
      } finally {
        setLoading(false)
      }
    }

    fetchCheckpoints()
    const interval = setInterval(fetchCheckpoints, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

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
        <DiamondMarker>承認待ち ({checkpoints.length})</DiamondMarker>
      </CardHeader>
      <CardContent>
        {loading && checkpoints.length === 0 ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            読み込み中...
          </div>
        ) : checkpoints.length === 0 ? (
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            承認待ちなし
          </div>
        ) : (
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {checkpoints.slice(0, 5).map((checkpoint) => (
              <div
                key={checkpoint.id}
                className="nier-list-item cursor-pointer hover:bg-nier-bg-selected"
                onClick={() => navigateToCheckpoint(checkpoint.id)}
              >
                <CategoryMarker status="pending" />
                <div className="flex-1 min-w-0">
                  <div className="text-nier-small truncate">{checkpoint.title}</div>
                </div>
                <div className="text-nier-caption text-nier-accent-red shrink-0">
                  {formatWaitingTime(checkpoint.createdAt)}
                </div>
              </div>
            ))}
            {checkpoints.length > 5 && (
              <button
                onClick={() => navigateToCheckpoint(checkpoints[0].id)}
                className="w-full text-center text-nier-caption text-nier-accent-blue hover:underline py-1"
              >
                他 {checkpoints.length - 5} 件を表示...
              </button>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
