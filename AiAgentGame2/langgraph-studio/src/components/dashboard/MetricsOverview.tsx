import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { formatNumber } from '@/lib/utils'

interface MetricRow {
  label: string
  value: string | number
  change?: 'up' | 'down'
}

export default function MetricsOverview(): JSX.Element {
  // Mock data
  const actualTokens = 20680 // Sum of agent tokensUsed
  const estimatedTokens = 53000 // Sum of agent tokensEstimated

  const metrics: MetricRow[] = [
    { label: '消費トークン', value: formatNumber(actualTokens) },
    { label: '完了時予想総トークン', value: formatNumber(estimatedTokens) },
    { label: '開始時間', value: '2026/01/16 14:32:10' },
    { label: '終了時間', value: '2026/01/16 15:17:23' },
    { label: '予想完了時間', value: '00:45:13' }
  ]

  const completedTasks = 12
  const totalTasks = 28
  const progress = Math.round((completedTasks / totalTasks) * 100)

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>メトリクス</DiamondMarker>
      </CardHeader>
      <CardContent>
        <div className="space-y-2 mb-4">
          {metrics.map((metric) => (
            <div key={metric.label} className="nier-status-row">
              <span className="nier-status-label">{metric.label}:</span>
              <span className="nier-status-value">{metric.value}</span>
            </div>
          ))}
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
      </CardContent>
    </Card>
  )
}
