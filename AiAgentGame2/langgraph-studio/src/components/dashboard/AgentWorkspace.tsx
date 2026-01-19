import { useMemo, useEffect } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { useProjectStore } from '@/stores/projectStore'
import { useAgentStore } from '@/stores/agentStore'
import { agentApi } from '@/services/apiService'
import type { Agent, AgentStatus } from '@/types/agent'

// Agent display configuration
interface AgentDisplayConfig {
  label: string
  color: string  // Background color for placeholder
}

// Get display config for agent type
function getAgentDisplayConfig(agentType: string): AgentDisplayConfig {
  const configs: Record<string, AgentDisplayConfig> = {
    // Phase 0: 企画
    concept: { label: 'ボス', color: '#4A90D9' },
    // Phase 1: タスク分割
    task_split_1: { label: '分配係', color: '#D9A04A' },
    task_split_2: { label: '分配係', color: '#D9A04A' },
    task_split_3: { label: '分配係', color: '#D9A04A' },
    task_split_4: { label: '分配係', color: '#D9A04A' },
    // Phase 2: 設計
    concept_detail: { label: '企画', color: '#E87A90' },
    scenario: { label: 'シナリオ', color: '#A87AE8' },
    world: { label: '世界観', color: '#7AE8A8' },
    game_design: { label: 'デザイン', color: '#E8D47A' },
    tech_spec: { label: 'テック', color: '#7AD4E8' },
    // Phase 4: アセット
    asset_character: { label: 'キャラ', color: '#FF9999' },
    asset_background: { label: '背景', color: '#99CC99' },
    asset_ui: { label: 'UI', color: '#9999CC' },
    asset_effect: { label: 'エフェクト', color: '#FFFF66' },
    asset_bgm: { label: 'BGM', color: '#CC99CC' },
    asset_voice: { label: 'ボイス', color: '#FFCCCC' },
    asset_sfx: { label: '効果音', color: '#99FFCC' },
    // Phase 6: 実装
    code: { label: 'コード', color: '#2A2A4E' },
    event: { label: 'イベント', color: '#2E3A4E' },
    ui_integration: { label: 'UI統合', color: '#3A2E4E' },
    asset_integration: { label: 'アセット統合', color: '#4E2E3A' },
    // Phase 8: テスト
    unit_test: { label: 'テスト1', color: '#00CC66' },
    integration_test: { label: 'テスト2', color: '#00AACC' },
  }
  return configs[agentType] || { label: 'Agent', color: '#888888' }
}

// Placeholder avatar component (will be replaced with PNG later)
function PlaceholderAvatar({
  agentType,
  status,
}: {
  agentType: string
  status: AgentStatus
}) {
  const config = getAgentDisplayConfig(agentType)
  const isWorking = status === 'running'
  const isPending = status === 'pending'
  const isCompleted = status === 'completed'

  return (
    <div
      className={`relative flex items-center justify-center ${isWorking ? 'animate-bounce' : ''} ${isPending ? 'opacity-30' : ''}`}
      style={{
        width: 56,
        height: 56,
        borderRadius: '50%',
        background: config.color,
        border: isWorking ? '3px solid #C4956C' : isCompleted ? '3px solid #7AAA7A' : '3px solid transparent',
        boxShadow: isWorking
          ? '0 0 15px rgba(196, 149, 108, 0.6)'
          : isCompleted
          ? '0 0 8px rgba(122, 170, 122, 0.4)'
          : 'none',
        fontSize: '24px',
      }}
    >
      {/* Placeholder: First character of label */}
      <span style={{ color: '#FFF', fontWeight: 'bold', textShadow: '1px 1px 2px rgba(0,0,0,0.5)' }}>
        {config.label.charAt(0)}
      </span>
    </div>
  )
}

// Single agent card
function AgentCharacterCard({ agent }: { agent: Agent }) {
  const config = getAgentDisplayConfig(agent.type)
  const isWorking = agent.status === 'running'
  const isWaiting = agent.status === 'waiting_approval'
  const isCompleted = agent.status === 'completed'
  const isFailed = agent.status === 'failed'

  return (
    <div
      className="relative flex flex-col items-center p-2 rounded-lg transition-all duration-300"
      style={{
        background: isWorking
          ? 'linear-gradient(135deg, rgba(196, 149, 108, 0.15) 0%, rgba(196, 149, 108, 0.05) 100%)'
          : isCompleted
          ? 'linear-gradient(135deg, rgba(122, 170, 122, 0.1) 0%, rgba(122, 170, 122, 0.05) 100%)'
          : 'transparent',
        border: isWorking ? '2px solid rgba(196, 149, 108, 0.4)' : '2px solid transparent',
        transform: isWorking ? 'scale(1.05)' : 'scale(1)',
        minWidth: 80,
      }}
    >
      {/* Status badge */}
      {isWorking && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[9px] font-bold whitespace-nowrap z-10"
          style={{
            background: 'linear-gradient(135deg, #C4956C 0%, #8B6914 100%)',
            color: '#FFF',
          }}
        >
          作業中
        </div>
      )}
      {isWaiting && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[9px] font-bold whitespace-nowrap z-10"
          style={{ background: '#D4C896', color: '#454138' }}
        >
          確認待ち
        </div>
      )}
      {isCompleted && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[9px] font-bold whitespace-nowrap z-10"
          style={{ background: '#7AAA7A', color: '#FFF' }}
        >
          完了
        </div>
      )}
      {isFailed && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[9px] font-bold whitespace-nowrap z-10"
          style={{ background: '#B85C5C', color: '#FFF' }}
        >
          エラー
        </div>
      )}

      {/* Avatar */}
      <div className="mt-1">
        <PlaceholderAvatar agentType={agent.type} status={agent.status} />
      </div>

      {/* Progress bar */}
      {(isWorking || isCompleted) && (
        <div className="w-14 h-1.5 mt-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(0,0,0,0.1)' }}>
          <div
            className="h-full transition-all duration-500"
            style={{
              width: `${agent.progress || (isCompleted ? 100 : 0)}%`,
              background: isCompleted
                ? 'linear-gradient(90deg, #7AAA7A 0%, #5C8A5C 100%)'
                : 'linear-gradient(90deg, #C4956C 0%, #8B6914 100%)',
            }}
          />
        </div>
      )}

      {/* Name */}
      <div className="mt-1 text-[10px] text-nier-text-main font-medium text-center">
        {config.label}
      </div>

      {/* Progress percentage for running */}
      {isWorking && (
        <div className="text-[9px] text-nier-accent-orange font-bold">
          {agent.progress || 0}%
        </div>
      )}
    </div>
  )
}

export default function AgentWorkspace(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { agents, setAgents } = useAgentStore()

  // Initial data fetch
  useEffect(() => {
    if (!currentProject) return

    const fetchAgents = async () => {
      try {
        const agentsData = await agentApi.listByProject(currentProject.id)
        const agentsConverted: Agent[] = agentsData.map(a => ({
          id: a.id,
          projectId: a.projectId,
          type: a.type,
          phase: a.phase,
          status: a.status as AgentStatus,
          progress: a.progress,
          currentTask: a.currentTask,
          tokensUsed: a.tokensUsed,
          startedAt: a.startedAt,
          completedAt: a.completedAt,
          error: a.error,
          parentAgentId: null,
          metadata: a.metadata,
          createdAt: a.startedAt || new Date().toISOString()
        }))
        setAgents(agentsConverted)
      } catch (error) {
        console.error('Failed to fetch agents:', error)
      }
    }

    fetchAgents()
  }, [currentProject?.id, setAgents])

  // Get agents for current project, prioritize running ones
  const displayAgents = useMemo(() => {
    if (!currentProject) return []

    const projectAgents = agents.filter(a => a.projectId === currentProject.id)

    // Sort: running first, then waiting_approval, then completed, then pending
    const statusOrder: Record<AgentStatus, number> = {
      running: 0,
      waiting_approval: 1,
      completed: 2,
      pending: 3,
      failed: 4,
      blocked: 5,
    }

    return projectAgents
      .sort((a, b) => statusOrder[a.status] - statusOrder[b.status])
      .slice(0, 16) // Show max 16 agents
  }, [agents, currentProject])

  const runningCount = displayAgents.filter(a => a.status === 'running').length
  const completedCount = displayAgents.filter(a => a.status === 'completed').length
  const totalCount = displayAgents.length

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>エージェント作業場</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>エージェント作業場</DiamondMarker>
        <div className="ml-auto flex items-center gap-4 text-nier-caption text-nier-text-light">
          {runningCount > 0 && (
            <span className="text-nier-accent-orange font-bold animate-pulse">
              作業中: {runningCount}
            </span>
          )}
          <span>完了: {completedCount}/{totalCount}</span>
        </div>
      </CardHeader>
      <CardContent>
        {displayAgents.length === 0 ? (
          <div className="text-nier-text-light text-center py-8 text-nier-small">
            エージェントがまだ起動していません
          </div>
        ) : (
          <div className="flex flex-wrap justify-center gap-3 py-2">
            {displayAgents.map(agent => (
              <AgentCharacterCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
