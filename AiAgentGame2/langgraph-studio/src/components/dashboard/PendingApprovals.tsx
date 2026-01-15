import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { CategoryMarker } from '@/components/ui/CategoryMarker'

interface PendingCheckpoint {
  id: string
  title: string
  waitingTime: string
  type: string
}

export default function PendingApprovals(): JSX.Element {
  // Mock data
  const checkpoints: PendingCheckpoint[] = [
    { id: '1', title: 'Design Document Review', waitingTime: '1h 23m', type: 'design' },
    { id: '2', title: 'Character Designs', waitingTime: '45m', type: 'asset' }
  ]

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>承認待ち ({checkpoints.length})</DiamondMarker>
      </CardHeader>
      <CardContent>
        {checkpoints.length === 0 ? (
          <div className="text-nier-text-light text-center py-4">
            承認待ちのタスクはありません
          </div>
        ) : (
          <div className="space-y-2">
            {checkpoints.map((checkpoint) => (
              <div
                key={checkpoint.id}
                className="nier-list-item cursor-pointer hover:bg-nier-bg-selected"
              >
                <CategoryMarker status="pending" />
                <div className="flex-1">
                  <div className="text-nier-small">{checkpoint.title}</div>
                </div>
                <div className="text-nier-small text-nier-accent-red">
                  {checkpoint.waitingTime}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
