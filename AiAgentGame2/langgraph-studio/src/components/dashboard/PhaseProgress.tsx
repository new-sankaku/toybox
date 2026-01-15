import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { cn } from '@/lib/utils'

export default function PhaseProgress(): JSX.Element {
  // Mock data
  const phases = [
    { id: 1, name: 'Phase 1', description: '企画・設計', progress: 33, status: 'current' as const },
    { id: 2, name: 'Phase 2', description: 'アセット生成', progress: 0, status: 'pending' as const },
    { id: 3, name: 'Phase 3', description: 'コード生成', progress: 0, status: 'pending' as const }
  ]

  const currentAgent = 'Scenario'
  const currentAgentProgress = 65
  const overallProgress = 17

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>フェーズ進捗</DiamondMarker>
        <span className="ml-auto text-nier-caption text-nier-text-light">
          全体 {overallProgress}%
        </span>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Phase Bars */}
        {phases.map((phase) => (
          <div key={phase.id} className="flex items-center gap-3">
            <span className={cn(
              'text-nier-caption w-16',
              phase.status === 'current' ? 'text-nier-accent-orange' : 'text-nier-text-light'
            )}>
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
        <div className="pt-2 border-t border-nier-border-light">
          <div className="flex justify-between text-nier-caption mb-1">
            <span className="text-nier-text-light">実行中:</span>
            <span className="text-nier-accent-orange">{currentAgent} ({currentAgentProgress}%)</span>
          </div>
          <Progress value={currentAgentProgress} className="h-1" />
        </div>
      </CardContent>
    </Card>
  )
}
