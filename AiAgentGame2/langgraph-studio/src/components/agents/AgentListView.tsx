import { useState, useMemo } from 'react'
import { Card, CardContent } from '@/components/ui/Card'
import { AgentCard } from './AgentCard'
import type { Agent, AgentStatus } from '@/types/agent'
import { cn } from '@/lib/utils'
import { Filter, Play, CheckCircle, XCircle, Clock, Pause } from 'lucide-react'

interface AgentListViewProps {
  agents: Agent[]
  onSelectAgent: (agent: Agent) => void
  selectedAgentId?: string
}

type FilterStatus = 'all' | AgentStatus

const filterOptions: { value: FilterStatus; label: string; icon: typeof Filter }[] = [
  { value: 'all', label: '全て', icon: Filter },
  { value: 'running', label: '実行中', icon: Play },
  { value: 'pending', label: '待機中', icon: Clock },
  { value: 'completed', label: '完了', icon: CheckCircle },
  { value: 'failed', label: 'エラー', icon: XCircle },
  { value: 'blocked', label: 'ブロック', icon: Pause }
]

export default function AgentListView({
  agents,
  onSelectAgent,
  selectedAgentId
}: AgentListViewProps): JSX.Element {
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('all')

  const filteredAgents = useMemo(() => {
    if (filterStatus === 'all') return agents
    return agents.filter((agent) => agent.status === filterStatus)
  }, [agents, filterStatus])

  const statusCounts = useMemo(() => {
    return {
      all: agents.length,
      running: agents.filter((a) => a.status === 'running').length,
      pending: agents.filter((a) => a.status === 'pending').length,
      completed: agents.filter((a) => a.status === 'completed').length,
      failed: agents.filter((a) => a.status === 'failed').length,
      blocked: agents.filter((a) => a.status === 'blocked').length
    }
  }, [agents])

  // Group agents by phase
  const agentsByPhase = useMemo(() => {
    const phase1Types = ['concept', 'design', 'scenario', 'character', 'world', 'task_split']
    const phase2Types = ['code_leader', 'asset_leader', 'code_worker', 'asset_worker']
    const phase3Types = ['integrator', 'tester', 'reviewer']

    return {
      phase1: filteredAgents.filter((a) => phase1Types.includes(a.type)),
      phase2: filteredAgents.filter((a) => phase2Types.includes(a.type)),
      phase3: filteredAgents.filter((a) => phase3Types.includes(a.type))
    }
  }, [filteredAgents])

  const renderPhaseSection = (title: string, phaseAgents: Agent[]) => {
    if (phaseAgents.length === 0) return null

    return (
      <div className="mb-6">
        <div className="flex items-center gap-2 mb-3">
          <div className="w-3 h-0.5 bg-nier-accent-blue" />
          <span className="text-nier-small text-nier-text-light tracking-nier-wide">
            {title}
          </span>
          <span className="text-nier-caption text-nier-text-light">
            ({phaseAgents.length})
          </span>
        </div>
        <div className="space-y-3">
          {phaseAgents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onSelect={onSelectAgent}
              isSelected={selectedAgentId === agent.id}
            />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 animate-nier-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-6 bg-nier-accent-orange" />
          <h1 className="text-nier-h1 font-medium tracking-nier-wide">
            AGENTS
          </h1>
          <span className="text-nier-text-light">
            - Real-time Monitor
          </span>
        </div>
        <div className="text-nier-small">
          {statusCounts.running > 0 && (
            <span className="text-nier-accent-orange animate-nier-pulse">
              {statusCounts.running}件実行中
            </span>
          )}
        </div>
      </div>

      {/* Filters */}
      <Card className="mb-6">
        <CardContent className="py-3">
          <div className="flex items-center gap-1 flex-wrap">
            {filterOptions.map((option) => {
              const Icon = option.icon
              const count = statusCounts[option.value]
              if (option.value !== 'all' && count === 0) return null

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
        </CardContent>
      </Card>

      {/* Agent List */}
      {filteredAgents.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <div className="text-nier-text-light">
              <p className="text-nier-body mb-2">エージェントがありません</p>
              <p className="text-nier-small">
                プロジェクトを開始するとエージェントが表示されます
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <>
          {renderPhaseSection('PHASE 1 - Planning', agentsByPhase.phase1)}
          {renderPhaseSection('PHASE 2 - Development', agentsByPhase.phase2)}
          {renderPhaseSection('PHASE 3 - Quality', agentsByPhase.phase3)}
        </>
      )}

      {/* Summary Stats */}
      <Card className="mt-6">
        <CardContent className="py-3">
          <div className="flex items-center justify-between text-nier-small text-nier-text-light">
            <div className="flex items-center gap-6">
              <span>
                総エージェント: <span className="text-nier-text-main">{statusCounts.all}</span>
              </span>
              <span>
                完了率:{' '}
                <span className="text-nier-accent-green">
                  {statusCounts.all > 0
                    ? Math.round((statusCounts.completed / statusCounts.all) * 100)
                    : 0}
                  %
                </span>
              </span>
              {statusCounts.failed > 0 && (
                <span>
                  エラー: <span className="text-nier-accent-red">{statusCounts.failed}</span>
                </span>
              )}
            </div>
            <span>表示中: {filteredAgents.length}件</span>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
