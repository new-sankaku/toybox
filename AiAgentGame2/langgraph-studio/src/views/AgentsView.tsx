import { useState } from 'react'
import { AgentListView, AgentDetailView } from '@/components/agents'
import type { Agent, AgentLogEntry } from '@/types/agent'

// Mock agent data for UI demonstration
const mockAgents: Agent[] = [
  {
    id: 'agent-concept',
    projectId: 'proj-001',
    type: 'concept',
    status: 'completed',
    progress: 100,
    currentTask: null,
    tokensUsed: 2450,
    startedAt: new Date(Date.now() - 1000 * 60 * 45).toISOString(),
    completedAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    error: null,
    parentAgentId: null,
    metadata: { version: '1.0' },
    createdAt: new Date(Date.now() - 1000 * 60 * 45).toISOString()
  },
  {
    id: 'agent-design',
    projectId: 'proj-001',
    type: 'design',
    status: 'completed',
    progress: 100,
    currentTask: null,
    tokensUsed: 3200,
    startedAt: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    completedAt: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
    error: null,
    parentAgentId: null,
    metadata: {},
    createdAt: new Date(Date.now() - 1000 * 60 * 30).toISOString()
  },
  {
    id: 'agent-scenario',
    projectId: 'proj-001',
    type: 'scenario',
    status: 'running',
    progress: 65,
    currentTask: 'Act 2のイベント生成中...',
    tokensUsed: 2100,
    startedAt: new Date(Date.now() - 1000 * 60 * 10).toISOString(),
    completedAt: null,
    error: null,
    parentAgentId: null,
    metadata: {},
    createdAt: new Date(Date.now() - 1000 * 60 * 10).toISOString()
  },
  {
    id: 'agent-character',
    projectId: 'proj-001',
    type: 'character',
    status: 'pending',
    progress: 0,
    currentTask: null,
    tokensUsed: 0,
    startedAt: null,
    completedAt: null,
    error: null,
    parentAgentId: null,
    metadata: {},
    createdAt: new Date().toISOString()
  },
  {
    id: 'agent-world',
    projectId: 'proj-001',
    type: 'world',
    status: 'pending',
    progress: 0,
    currentTask: null,
    tokensUsed: 0,
    startedAt: null,
    completedAt: null,
    error: null,
    parentAgentId: null,
    metadata: {},
    createdAt: new Date().toISOString()
  },
  {
    id: 'agent-task_split',
    projectId: 'proj-001',
    type: 'task_split',
    status: 'pending',
    progress: 0,
    currentTask: null,
    tokensUsed: 0,
    startedAt: null,
    completedAt: null,
    error: null,
    parentAgentId: null,
    metadata: {},
    createdAt: new Date().toISOString()
  }
]

// Mock logs for the running agent
const mockLogs: Record<string, AgentLogEntry[]> = {
  'agent-scenario': [
    { id: '1', timestamp: new Date(Date.now() - 1000 * 60 * 10).toISOString(), level: 'info', message: 'シナリオエージェント開始' },
    { id: '2', timestamp: new Date(Date.now() - 1000 * 60 * 9).toISOString(), level: 'info', message: 'コンセプトドキュメント読み込み完了', progress: 10 },
    { id: '3', timestamp: new Date(Date.now() - 1000 * 60 * 8).toISOString(), level: 'info', message: 'デザインドキュメント読み込み完了', progress: 15 },
    { id: '4', timestamp: new Date(Date.now() - 1000 * 60 * 7).toISOString(), level: 'info', message: 'Act 1 構造生成開始', progress: 20 },
    { id: '5', timestamp: new Date(Date.now() - 1000 * 60 * 5).toISOString(), level: 'info', message: 'Act 1 完了: 目覚めと旅立ち', progress: 35 },
    { id: '6', timestamp: new Date(Date.now() - 1000 * 60 * 4).toISOString(), level: 'info', message: 'Act 2 構造生成開始', progress: 40 },
    { id: '7', timestamp: new Date(Date.now() - 1000 * 60 * 3).toISOString(), level: 'debug', message: 'LLM呼び出し: gpt-4-turbo', metadata: { tokens: 1500 } },
    { id: '8', timestamp: new Date(Date.now() - 1000 * 60 * 2).toISOString(), level: 'info', message: 'イベントノード生成中: 12/20完了', progress: 55 },
    { id: '9', timestamp: new Date(Date.now() - 1000 * 60 * 1).toISOString(), level: 'info', message: 'イベントノード生成中: 16/20完了', progress: 65 },
    { id: '10', timestamp: new Date().toISOString(), level: 'info', message: 'Act 2のイベント生成中...', progress: 65 }
  ],
  'agent-concept': [
    { id: '1', timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(), level: 'info', message: 'コンセプトエージェント開始' },
    { id: '2', timestamp: new Date(Date.now() - 1000 * 60 * 44).toISOString(), level: 'info', message: 'ユーザー入力解析完了', progress: 20 },
    { id: '3', timestamp: new Date(Date.now() - 1000 * 60 * 42).toISOString(), level: 'info', message: 'ジャンル分析完了', progress: 40 },
    { id: '4', timestamp: new Date(Date.now() - 1000 * 60 * 38).toISOString(), level: 'info', message: 'コンセプトドキュメント生成中', progress: 70 },
    { id: '5', timestamp: new Date(Date.now() - 1000 * 60 * 32).toISOString(), level: 'info', message: 'レビュー用サマリー生成', progress: 90 },
    { id: '6', timestamp: new Date(Date.now() - 1000 * 60 * 30).toISOString(), level: 'info', message: 'コンセプトエージェント完了', progress: 100 }
  ],
  'agent-design': [
    { id: '1', timestamp: new Date(Date.now() - 1000 * 60 * 30).toISOString(), level: 'info', message: 'デザインエージェント開始' },
    { id: '2', timestamp: new Date(Date.now() - 1000 * 60 * 28).toISOString(), level: 'info', message: 'コンセプト分析完了', progress: 15 },
    { id: '3', timestamp: new Date(Date.now() - 1000 * 60 * 25).toISOString(), level: 'info', message: '戦闘システム設計中', progress: 35 },
    { id: '4', timestamp: new Date(Date.now() - 1000 * 60 * 20).toISOString(), level: 'info', message: '進行システム設計中', progress: 55 },
    { id: '5', timestamp: new Date(Date.now() - 1000 * 60 * 17).toISOString(), level: 'info', message: 'クエストシステム設計中', progress: 75 },
    { id: '6', timestamp: new Date(Date.now() - 1000 * 60 * 15).toISOString(), level: 'info', message: 'デザインエージェント完了', progress: 100 }
  ]
}

export default function AgentsView(): JSX.Element {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)

  const handleSelectAgent = (agent: Agent) => {
    setSelectedAgent(agent)
  }

  const handleBack = () => {
    setSelectedAgent(null)
  }

  const handleRetry = () => {
    console.log('Retry agent:', selectedAgent?.id)
  }

  // Show detail view if agent is selected
  if (selectedAgent) {
    const logs = mockLogs[selectedAgent.id] || []
    return (
      <AgentDetailView
        agent={selectedAgent}
        logs={logs}
        onBack={handleBack}
        onRetry={selectedAgent.status === 'failed' ? handleRetry : undefined}
      />
    )
  }

  // Show agent list
  return (
    <AgentListView
      agents={mockAgents}
      onSelectAgent={handleSelectAgent}
      selectedAgentId={undefined}
    />
  )
}
