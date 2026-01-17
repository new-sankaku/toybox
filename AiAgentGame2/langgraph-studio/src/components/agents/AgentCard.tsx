import { Progress } from '@/components/ui/Progress'
import { cn } from '@/lib/utils'
import type { Agent, QualityCheckConfig } from '@/types/agent'
import { Cpu, Play, CheckCircle, XCircle, Pause, Clock, Shield, ShieldOff, Sparkles } from 'lucide-react'

interface AgentCardProps {
  agent: Agent
  onSelect: (agent: Agent) => void
  isSelected?: boolean
  qualityCheckConfig?: QualityCheckConfig
  /** 待機中の場合、何を待っているかの説明 */
  waitingFor?: string
}

const statusConfig = {
  pending: {
    color: 'bg-nier-border-dark',
    icon: Clock,
    text: '待機中',
    pulse: false
  },
  running: {
    color: 'bg-nier-border-dark',
    icon: Play,
    text: '実行中',
    pulse: false
  },
  completed: {
    color: 'bg-nier-border-dark',
    icon: CheckCircle,
    text: '完了',
    pulse: false
  },
  failed: {
    color: 'bg-nier-border-dark',
    icon: XCircle,
    text: 'エラー',
    pulse: false
  },
  blocked: {
    color: 'bg-nier-border-dark',
    icon: Pause,
    text: 'ブロック',
    pulse: false
  }
}

// エージェント表示名を取得（バックエンドの metadata.displayName を使用）
const getDisplayName = (agent: Agent): string => {
  return (agent.metadata?.displayName as string) || agent.type
}

// Agent role (Leader/Worker) labels - ALL agents must have a role
const getAgentRole = (type: string): { role: string } => {
  // Explicit Leader types
  if (type.endsWith('_leader')) {
    return { role: 'Leader' }
  }
  // Explicit Worker types
  if (type.endsWith('_worker')) {
    return { role: 'Worker' }
  }
  // Phase 3 agents - assign roles based on function
  if (type === 'integrator') {
    return { role: 'Leader' }  // Coordinates integration
  }
  if (type === 'tester') {
    return { role: 'Worker' }  // Executes tests
  }
  if (type === 'reviewer') {
    return { role: 'Leader' }  // Reviews and approves
  }
  // Phase 1 standalone agents (without _leader suffix) - treat as Leaders
  if (['concept', 'design', 'scenario', 'character', 'world', 'task_split'].includes(type)) {
    return { role: 'Leader' }
  }
  // Default to Worker for any unknown type
  return { role: 'Worker' }
}

export function AgentCard({
  agent,
  onSelect,
  isSelected = false,
  qualityCheckConfig,
  waitingFor
}: AgentCardProps): JSX.Element {
  const status = statusConfig[agent.status]
  const StatusIcon = status.icon
  const agentRole = getAgentRole(agent.type)

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

  // Get detailed task/status text based on role
  const getTaskText = () => {
    if (agent.status === 'running') {
      return agent.currentTask || '処理中'
    }
    if (agent.status === 'pending') return waitingFor || '開始待機'
    if (agent.status === 'blocked') return '承認待ち'
    if (agent.status === 'completed') return '完了'
    if (agent.status === 'failed') return agent.error || 'エラー発生'
    return ''
  }

  // Check if LLM is being used (simulation)
  const isUsingLLM = agent.status === 'running' && agent.progress > 0

  return (
    <div
      className={cn(
        'cursor-pointer transition-all duration-nier-normal px-3 py-2',
        'hover:bg-nier-bg-selected',
        isSelected && 'bg-nier-bg-selected'
      )}
      onClick={() => onSelect(agent)}
    >
        {/* Grid Layout for aligned columns - each column has fixed width for vertical alignment */}
        <div className="grid grid-cols-[4px_55px_140px_1fr_140px_auto] items-center gap-2">
          {/* Col 1: Status Indicator */}
          <div className="w-1 h-6 bg-nier-border-dark" />

          {/* Col 2: Role badge (fixed width) - comes BEFORE agent type */}
          <div className="flex items-center">
            <span className="text-nier-caption text-nier-text-light">
              [{agentRole.role}]
            </span>
          </div>

          {/* Col 3: Agent Type (fixed width) */}
          <div className="flex items-center gap-1.5">
            <Cpu size={12} className="text-nier-text-light flex-shrink-0" />
            <span className="text-nier-small font-medium text-nier-text-main">
              {getDisplayName(agent)}
            </span>
          </div>

          {/* Col 4: Task/Status Text (flexible) */}
          <div className="flex items-center gap-2 min-w-0">
            {isUsingLLM && (
              <Sparkles size={12} className="text-nier-accent-gold flex-shrink-0 animate-pulse" title="LLM生成中" />
            )}
            <span className="text-nier-caption truncate text-nier-text-light">
              {getTaskText()}
            </span>
          </div>

          {/* Col 5: Progress Bar + Time (fixed width) */}
          <div className="flex items-center gap-2">
            {agent.status === 'running' ? (
              <>
                <Progress value={agent.progress} className="h-1.5 w-12" />
                <span className="text-nier-caption text-nier-text-light w-8">
                  {agent.progress}%
                </span>
              </>
            ) : (
              <span className="w-[76px]" />
            )}
            <span className="text-nier-caption text-nier-text-light flex items-center gap-1">
              <Clock size={10} />
              {getRuntime()}
            </span>
          </div>

          {/* Col 6: Right side info (auto width) */}
          <div className="flex items-center gap-2">
            <span className="text-nier-caption text-nier-text-light w-14 text-right">
              {agent.tokensUsed.toLocaleString()}tk
            </span>
            {/* Quality Check Badge */}
            {qualityCheckConfig && (
              <div
                className="px-1.5 py-0.5 text-nier-caption tracking-nier flex items-center gap-1 bg-nier-bg-selected text-nier-text-light border border-nier-border-light"
                title={qualityCheckConfig.enabled ? '品質チェックON' : '品質チェックOFF'}
              >
                {qualityCheckConfig.enabled ? <Shield size={10} /> : <ShieldOff size={10} />}
                <span>QC</span>
              </div>
            )}
            <div className="px-1.5 py-0.5 text-nier-caption tracking-nier flex items-center gap-1 w-16 justify-center bg-nier-bg-selected text-nier-text-light border border-nier-border-light">
              <StatusIcon size={10} />
              {status.text}
            </div>
          </div>
        </div>
    </div>
  )
}
