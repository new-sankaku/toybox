import { Card, CardContent } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import type { Checkpoint } from '@/types/checkpoint'
import { Clock, FileText, Code } from 'lucide-react'

interface CheckpointCardProps {
  checkpoint: Checkpoint
  onSelect: (checkpoint: Checkpoint) => void
  isSelected?: boolean
}

const statusConfig = {
  pending: {
    color: 'bg-nier-accent-yellow',
    text: '承認待ち',
    pulse: true
  },
  approved: {
    color: 'bg-nier-accent-green',
    text: '承認済み',
    pulse: false
  },
  rejected: {
    color: 'bg-nier-accent-red',
    text: '却下',
    pulse: false
  },
  revision_requested: {
    color: 'bg-nier-accent-orange',
    text: '修正要求',
    pulse: true
  }
}

const typeConfig: Record<string, { icon: typeof FileText; label: string }> = {
  concept_review: { icon: FileText, label: 'コンセプト' },
  design_review: { icon: FileText, label: 'デザイン' },
  scenario_review: { icon: FileText, label: 'シナリオ' },
  character_review: { icon: FileText, label: 'キャラクター' },
  world_review: { icon: FileText, label: 'ワールド' },
  task_review: { icon: Code, label: 'タスク分割' }
}

export function CheckpointCard({
  checkpoint,
  onSelect,
  isSelected = false
}: CheckpointCardProps): JSX.Element {
  const status = statusConfig[checkpoint.status]
  const type = typeConfig[checkpoint.type] || { icon: FileText, label: checkpoint.type }
  const TypeIcon = type.icon

  const getWaitingTime = () => {
    const created = new Date(checkpoint.createdAt)
    const now = new Date()
    const diffMs = now.getTime() - created.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return '今すぐ'
    if (diffMins < 60) return `${diffMins}分前`
    const hours = Math.floor(diffMins / 60)
    if (hours < 24) return `${hours}時間前`
    const days = Math.floor(hours / 24)
    return `${days}日前`
  }

  return (
    <Card
      className={cn(
        'cursor-pointer transition-all duration-nier-normal',
        'hover:shadow-md hover:translate-x-1',
        isSelected && 'ring-2 ring-nier-accent-blue'
      )}
      onClick={() => onSelect(checkpoint)}
    >
      <CardContent className="p-3">
        {/* Header Row */}
        <div className="flex items-start justify-between mb-2">
          <div className="flex items-center gap-2">
            {/* Category Marker */}
            <div className={cn('w-1 h-8', status.color, status.pulse && 'animate-nier-pulse')} />

            {/* Type Icon & Title */}
            <div>
              <div className="flex items-center gap-1.5 mb-0.5">
                <TypeIcon size={12} className="text-nier-text-light" />
                <span className="text-nier-caption text-nier-text-light tracking-nier">
                  {type.label}
                </span>
              </div>
              <h3 className="text-nier-small font-medium text-nier-text-main">
                {checkpoint.title}
              </h3>
            </div>
          </div>

          {/* Status, Time, Tokens, Review Button */}
          <div className="flex items-center gap-2">
            <span className="text-nier-caption text-nier-text-light flex items-center gap-1">
              <Clock size={10} />
              {getWaitingTime()}
            </span>
            {checkpoint.output.tokensUsed && (
              <span className="text-nier-caption text-nier-text-light">
                {checkpoint.output.tokensUsed.toLocaleString()}tk
              </span>
            )}
            <div className={cn(
              'px-1.5 py-0.5 text-nier-caption tracking-nier',
              status.color === 'bg-nier-accent-yellow' && 'bg-nier-accent-yellow/20 text-nier-text-main',
              status.color === 'bg-nier-accent-green' && 'bg-nier-accent-green/20 text-nier-accent-green',
              status.color === 'bg-nier-accent-red' && 'bg-nier-accent-red/20 text-nier-accent-red',
              status.color === 'bg-nier-accent-orange' && 'bg-nier-accent-orange/20 text-nier-accent-orange'
            )}>
              {status.text}
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="text-nier-accent-blue py-0 px-1.5 text-nier-caption"
              onClick={(e) => {
                e.stopPropagation()
                onSelect(checkpoint)
              }}
            >
              レビュー
            </Button>
          </div>
        </div>

        {/* Summary */}
        {checkpoint.output.summary && (
          <p className="text-nier-caption text-nier-text-light line-clamp-2 pl-3">
            {checkpoint.output.summary}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
