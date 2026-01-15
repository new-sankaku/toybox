import { Card, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { cn } from '@/lib/utils'
import type { Agent } from '@/types/agent'
import { Cpu, Play, CheckCircle, XCircle, Pause, Clock } from 'lucide-react'

interface AgentCardProps {
  agent: Agent
  onSelect: (agent: Agent) => void
  isSelected?: boolean
}

const statusConfig = {
  pending: {
    color: 'bg-[#8A857A]',
    icon: Clock,
    text: '待機中',
    pulse: false
  },
  running: {
    color: 'bg-nier-accent-orange',
    icon: Play,
    text: '実行中',
    pulse: true
  },
  completed: {
    color: 'bg-nier-accent-green',
    icon: CheckCircle,
    text: '完了',
    pulse: false
  },
  failed: {
    color: 'bg-nier-accent-red',
    icon: XCircle,
    text: 'エラー',
    pulse: false
  },
  blocked: {
    color: 'bg-nier-accent-yellow',
    icon: Pause,
    text: 'ブロック',
    pulse: true
  }
}

const agentTypeLabels: Record<string, string> = {
  concept: 'コンセプト',
  design: 'デザイン',
  scenario: 'シナリオ',
  character: 'キャラクター',
  world: 'ワールド',
  task_split: 'タスク分割',
  code_leader: 'コードリーダー',
  asset_leader: 'アセットリーダー',
  code_worker: 'コードワーカー',
  asset_worker: 'アセットワーカー',
  integrator: 'インテグレーター',
  tester: 'テスター',
  reviewer: 'レビュアー'
}

export function AgentCard({
  agent,
  onSelect,
  isSelected = false
}: AgentCardProps): JSX.Element {
  const status = statusConfig[agent.status]
  const StatusIcon = status.icon

  const getRuntime = () => {
    if (!agent.startedAt) return '-'
    const start = new Date(agent.startedAt).getTime()
    const end = agent.completedAt
      ? new Date(agent.completedAt).getTime()
      : Date.now()
    const seconds = Math.floor((end - start) / 1000)

    if (seconds < 60) return `${seconds}秒`
    const minutes = Math.floor(seconds / 60)
    const remainingSeconds = seconds % 60
    return `${minutes}分${remainingSeconds}秒`
  }

  return (
    <Card
      className={cn(
        'cursor-pointer transition-all duration-nier-normal',
        'hover:shadow-md hover:translate-x-1',
        isSelected && 'ring-2 ring-nier-accent-blue'
      )}
      onClick={() => onSelect(agent)}
    >
      <CardContent className="p-3">
        {/* Header Row */}
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            {/* Status Indicator */}
            <div
              className={cn(
                'w-1 h-8',
                status.color,
                status.pulse && 'animate-nier-pulse'
              )}
            />

            {/* Agent Info */}
            <div>
              <div className="flex items-center gap-1.5 mb-0.5">
                <Cpu size={12} className="text-nier-text-light" />
                <span className="text-nier-caption text-nier-text-light tracking-nier">
                  AGENT
                </span>
              </div>
              <h3 className="text-nier-small font-medium text-nier-text-main">
                {agentTypeLabels[agent.type] || agent.type}
              </h3>
            </div>
          </div>

          {/* Time, Tokens, Status Badge */}
          <div className="flex items-center gap-2">
            <span className="text-nier-caption text-nier-text-light flex items-center gap-1">
              <Clock size={10} />
              {getRuntime()}
            </span>
            <span className="text-nier-caption text-nier-text-light">
              {agent.tokensUsed.toLocaleString()}tk
            </span>
            <div className={cn(
              'px-1.5 py-0.5 text-nier-caption tracking-nier flex items-center gap-1',
              status.color === 'bg-nier-accent-green' && 'bg-nier-accent-green/20 text-nier-accent-green',
              status.color === 'bg-nier-accent-red' && 'bg-nier-accent-red/20 text-nier-accent-red',
              status.color === 'bg-nier-accent-orange' && 'bg-nier-accent-orange/20 text-nier-accent-orange',
              status.color === 'bg-nier-accent-yellow' && 'bg-nier-accent-yellow/20 text-nier-text-main',
              status.color === 'bg-[#8A857A]' && 'bg-[#8A857A]/20 text-nier-text-light'
            )}>
              <StatusIcon size={10} />
              {status.text}
            </div>
          </div>
        </div>

        {/* Progress Bar (only for running agents) */}
        {agent.status === 'running' && (
          <div className="mb-2 pl-3">
            <Progress value={agent.progress} className="h-1" />
            <div className="flex justify-between mt-1">
              <span className="text-nier-caption text-nier-text-light">
                {agent.currentTask || '処理中...'}
              </span>
              <span className="text-nier-caption text-nier-accent-orange">
                {agent.progress}%
              </span>
            </div>
          </div>
        )}

        {/* Error Message */}
        {agent.status === 'failed' && agent.error && (
          <div className="mt-2 pt-2 border-t border-nier-border-light pl-3">
            <p className="text-nier-caption text-nier-accent-red line-clamp-2">
              {agent.error}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
