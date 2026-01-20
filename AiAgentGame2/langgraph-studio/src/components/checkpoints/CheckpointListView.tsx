import { useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/Card'
import { CheckpointCard } from './CheckpointCard'
import type { Checkpoint } from '@/types/checkpoint'
import { cn } from '@/lib/utils'
import { Filter, Clock, CheckCircle, XCircle, RotateCcw, CircleDashed } from 'lucide-react'

interface CheckpointListViewProps {
  checkpoints: Checkpoint[]
  onSelectCheckpoint: (checkpoint: Checkpoint) => void
  selectedCheckpointId?: string
  loading?: boolean
}

type FilterStatus = 'all' | 'incomplete' | 'pending' | 'approved' | 'rejected' | 'revision_requested'

const filterOptions: { value: FilterStatus; label: string; icon: typeof Filter }[] = [
  { value: 'all', label: '全て', icon: Filter },
  { value: 'incomplete', label: '未完了', icon: CircleDashed },
  { value: 'pending', label: '承認待ち', icon: Clock },
  { value: 'approved', label: '承認済み', icon: CheckCircle },
  { value: 'rejected', label: '却下', icon: XCircle },
  { value: 'revision_requested', label: '修正要求', icon: RotateCcw }
]

export default function CheckpointListView({
  checkpoints,
  onSelectCheckpoint,
  selectedCheckpointId,
  loading = false
}: CheckpointListViewProps): JSX.Element {
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('incomplete')
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest')

  const filteredCheckpoints = useMemo(() => {
    let filtered = checkpoints

    if (filterStatus === 'incomplete') {
      filtered = filtered.filter(cp => cp.status !== 'approved')
    } else if (filterStatus !== 'all') {
      filtered = filtered.filter(cp => cp.status === filterStatus)
    }

    filtered = [...filtered].sort((a, b) => {
      const dateA = new Date(a.createdAt).getTime()
      const dateB = new Date(b.createdAt).getTime()
      return sortOrder === 'newest' ? dateB - dateA : dateA - dateB
    })

    return filtered
  }, [checkpoints, filterStatus, sortOrder])

  const statusCounts = useMemo(() => {
    const incomplete = checkpoints.filter(cp => cp.status !== 'approved').length
    return {
      all: checkpoints.length,
      incomplete,
      pending: checkpoints.filter(cp => cp.status === 'pending').length,
      approved: checkpoints.filter(cp => cp.status === 'approved').length,
      rejected: checkpoints.filter(cp => cp.status === 'rejected').length,
      revision_requested: checkpoints.filter(cp => cp.status === 'revision_requested').length
    }
  }, [checkpoints])

  return (
    <div className="p-4 animate-nier-fade-in">
      {/* Header */}
      <div className="nier-page-header-row">
        <div className="nier-page-header-left">
          <h1 className="nier-page-title">CHECKPOINTS</h1>
          <span className="nier-page-subtitle">- レビュー待ち</span>
        </div>
        <div className="nier-page-header-right" />
      </div>

      {/* Filters */}
      <Card className="mb-3">
        <CardContent className="py-1.5">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-1 flex-wrap">
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
      <div className="flex items-center gap-6 mb-3 text-nier-small text-nier-text-light">
        <span>
          総チェックポイント: <span className="text-nier-text-main">{statusCounts.all}</span>
        </span>
        <span>
          承認率: <span className="text-nier-text-main">
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
      {loading && checkpoints.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <div className="text-nier-text-light">
              <p className="text-nier-body">読み込み中...</p>
            </div>
          </CardContent>
        </Card>
      ) : filteredCheckpoints.length === 0 ? (
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
        <div className="space-y-2 nier-scroll-list">
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
