import { useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/Card'
import { CheckpointCard } from './CheckpointCard'
import type { Checkpoint } from '@/types/checkpoint'
import { cn } from '@/lib/utils'
import { Filter, Clock, CheckCircle, XCircle, RotateCcw } from 'lucide-react'

interface CheckpointListViewProps {
  checkpoints: Checkpoint[]
  onSelectCheckpoint: (checkpoint: Checkpoint) => void
  selectedCheckpointId?: string
}

type FilterStatus = 'all' | 'pending' | 'approved' | 'rejected' | 'revision_requested'

const filterOptions: { value: FilterStatus; label: string; icon: typeof Filter }[] = [
  { value: 'all', label: '全て', icon: Filter },
  { value: 'pending', label: '承認待ち', icon: Clock },
  { value: 'approved', label: '承認済み', icon: CheckCircle },
  { value: 'rejected', label: '却下', icon: XCircle },
  { value: 'revision_requested', label: '修正要求', icon: RotateCcw }
]

export default function CheckpointListView({
  checkpoints,
  onSelectCheckpoint,
  selectedCheckpointId
}: CheckpointListViewProps): JSX.Element {
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all')
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest')

  const filteredCheckpoints = useMemo(() => {
    let filtered = checkpoints

    // Apply status filter
    if (filterStatus !== 'all') {
      filtered = filtered.filter(cp => cp.status === filterStatus)
    }

    // Apply sort
    filtered = [...filtered].sort((a, b) => {
      const dateA = new Date(a.createdAt).getTime()
      const dateB = new Date(b.createdAt).getTime()
      return sortOrder === 'newest' ? dateB - dateA : dateA - dateB
    })

    return filtered
  }, [checkpoints, filterStatus, sortOrder])

  const statusCounts = useMemo(() => {
    return {
      all: checkpoints.length,
      pending: checkpoints.filter(cp => cp.status === 'pending').length,
      approved: checkpoints.filter(cp => cp.status === 'approved').length,
      rejected: checkpoints.filter(cp => cp.status === 'rejected').length,
      revision_requested: checkpoints.filter(cp => cp.status === 'revision_requested').length
    }
  }, [checkpoints])

  return (
    <div className="p-6 animate-nier-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-6 bg-nier-accent-yellow" />
          <h1 className="text-nier-h1 font-medium tracking-nier-wide">
            CHECKPOINTS
          </h1>
          <span className="text-nier-text-light">
            - Human Review Queue
          </span>
        </div>
        <div className="text-nier-small text-nier-text-light">
          {statusCounts.pending > 0 && (
            <span className="text-nier-accent-yellow">
              {statusCounts.pending}件の承認待ち
            </span>
          )}
        </div>
      </div>

      {/* Filters */}
      <Card className="mb-4">
        <CardContent className="py-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              {filterOptions.map(option => {
                const Icon = option.icon
                const count = statusCounts[option.value]
                return (
                  <button
                    key={option.value}
                    className={cn(
                      'flex items-center gap-2 px-3 py-1.5 text-nier-small tracking-nier transition-colors',
                      filterStatus === option.value
                        ? 'bg-nier-bg-selected text-nier-text-main'
                        : 'text-nier-text-light hover:bg-nier-bg-panel'
                    )}
                    onClick={() => setFilterStatus(option.value)}
                  >
                    <Icon size={14} />
                    <span>{option.label}</span>
                    <span className="text-nier-caption">({count})</span>
                  </button>
                )
              })}
            </div>

            <div className="flex items-center gap-2">
              <span className="text-nier-caption text-nier-text-light">並び順:</span>
              <button
                className={cn(
                  'px-2 py-1 text-nier-caption tracking-nier',
                  sortOrder === 'newest' ? 'bg-nier-bg-selected' : 'hover:bg-nier-bg-panel'
                )}
                onClick={() => setSortOrder('newest')}
              >
                新しい順
              </button>
              <button
                className={cn(
                  'px-2 py-1 text-nier-caption tracking-nier',
                  sortOrder === 'oldest' ? 'bg-nier-bg-selected' : 'hover:bg-nier-bg-panel'
                )}
                onClick={() => setSortOrder('oldest')}
              >
                古い順
              </button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Summary Stats */}
      <div className="flex items-center gap-6 mb-4 text-nier-small text-nier-text-light">
        <span>
          総チェックポイント: <span className="text-nier-text-main">{statusCounts.all}</span>
        </span>
        <span>
          承認率: <span className="text-nier-accent-green">
            {statusCounts.all > 0
              ? Math.round((statusCounts.approved / statusCounts.all) * 100)
              : 0}%
          </span>
        </span>
        <span>
          表示中: <span className="text-nier-text-main">{filteredCheckpoints.length}件</span>
        </span>
      </div>

      {/* Checkpoint List */}
      {filteredCheckpoints.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <div className="text-nier-text-light">
              <p className="text-nier-body mb-2">チェックポイントがありません</p>
              <p className="text-nier-small">
                {filterStatus !== 'all'
                  ? `「${filterOptions.find(o => o.value === filterStatus)?.label}」のチェックポイントはありません`
                  : 'エージェントの実行を開始してください'}
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {filteredCheckpoints.map(checkpoint => (
            <CheckpointCard
              key={checkpoint.id}
              checkpoint={checkpoint}
              onSelect={onSelectCheckpoint}
              isSelected={selectedCheckpointId === checkpoint.id}
            />
          ))}
        </div>
      )}

    </div>
  )
}
