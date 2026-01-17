import { useState, useEffect, useMemo } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { useProjectStore } from '@/stores/projectStore'
import { useNavigationStore } from '@/stores/navigationStore'
import { cn } from '@/lib/utils'
import {
  MessageSquare,
  Image,
  Music,
  Mic,
  FolderOpen,
  Clock,
  Zap,
  CheckCircle,
  XCircle,
  Loader2,
  ChevronDown,
  ChevronRight,
  Bot,
  User,
  CircleDashed,
  Filter
} from 'lucide-react'
import type { AgentType } from '@/types/agent'

type AIServiceType = 'llm' | 'image' | 'audio' | 'music'
type RequestStatus = 'pending' | 'processing' | 'completed' | 'failed'

interface AIRequest {
  id: string
  serviceType: AIServiceType
  serviceName: string
  agentId: string
  agentType: AgentType
  input: string
  output?: string
  status: RequestStatus
  tokensUsed?: number
  cost?: number
  duration?: number
  createdAt: string
  completedAt?: string
  error?: string
}

interface GroupedRequests {
  serviceName: string
  serviceType: AIServiceType
  requests: AIRequest[]
  stats: {
    total: number
    completed: number
    processing: number
    pending: number
    failed: number
    totalCost: number
    totalTokens: number
  }
}

const serviceConfig: Record<AIServiceType, { icon: typeof MessageSquare; label: string; color: string }> = {
  llm: { icon: MessageSquare, label: 'LLM', color: 'text-nier-text-light' },
  image: { icon: Image, label: '画像生成', color: 'text-nier-text-light' },
  audio: { icon: Mic, label: '音声生成', color: 'text-nier-text-light' },
  music: { icon: Music, label: '音楽生成', color: 'text-nier-text-light' }
}

const statusConfig: Record<RequestStatus, { icon: typeof CheckCircle; label: string; color: string }> = {
  pending: { icon: Clock, label: '待機中', color: 'text-nier-text-light' },
  processing: { icon: Loader2, label: '処理中', color: 'text-nier-text-light' },
  completed: { icon: CheckCircle, label: '完了', color: 'text-nier-text-light' },
  failed: { icon: XCircle, label: 'エラー', color: 'text-nier-text-light' }
}

const agentConfig: Record<AgentType, { label: string; shortLabel: string }> = {
  concept: { label: 'Concept Agent', shortLabel: 'CONCEPT' },
  design: { label: 'Design Agent', shortLabel: 'DESIGN' },
  scenario: { label: 'Scenario Agent', shortLabel: 'SCENARIO' },
  character: { label: 'Character Agent', shortLabel: 'CHARACTER' },
  world: { label: 'World Agent', shortLabel: 'WORLD' },
  task_split: { label: 'Task Split Agent', shortLabel: 'TASK_SPLIT' },
  code_leader: { label: 'Code Leader', shortLabel: 'CODE_L' },
  asset_leader: { label: 'Asset Leader', shortLabel: 'ASSET_L' },
  code_worker: { label: 'Code Worker', shortLabel: 'CODE_W' },
  asset_worker: { label: 'Asset Worker', shortLabel: 'ASSET_W' },
  integrator: { label: 'Integrator Agent', shortLabel: 'INTEGRATOR' },
  tester: { label: 'Tester Agent', shortLabel: 'TESTER' },
  reviewer: { label: 'Reviewer Agent', shortLabel: 'REVIEWER' }
}

// Mock data for demonstration
const mockRequests: AIRequest[] = [
  // Claude requests
  {
    id: 'ai-001',
    serviceType: 'llm',
    serviceName: 'Claude 3.5 Sonnet',
    agentId: 'agent-concept-001',
    agentType: 'concept',
    input: 'ボールを転がすパズルゲームのコンセプトドキュメントを作成してください。',
    output: '# ゲームコンセプト\n\n## 概要\nボールを操作してゴールを目指すシンプルなパズルゲーム。',
    status: 'completed',
    tokensUsed: 1250,
    cost: 0.015,
    duration: 3200,
    createdAt: new Date(Date.now() - 300000).toISOString(),
    completedAt: new Date(Date.now() - 296800).toISOString()
  },
  {
    id: 'ai-002',
    serviceType: 'llm',
    serviceName: 'Claude 3.5 Sonnet',
    agentId: 'agent-scenario-001',
    agentType: 'scenario',
    input: 'ステージ1〜5のシナリオを作成してください。',
    output: '# ステージシナリオ\n\n## ステージ1: はじまりの草原\nチュートリアルステージ...',
    status: 'completed',
    tokensUsed: 2100,
    cost: 0.025,
    duration: 4500,
    createdAt: new Date(Date.now() - 250000).toISOString(),
    completedAt: new Date(Date.now() - 245500).toISOString()
  },
  {
    id: 'ai-003',
    serviceType: 'llm',
    serviceName: 'Claude 3.5 Sonnet',
    agentId: 'agent-character-001',
    agentType: 'character',
    input: 'キャラクターの会話テキストを生成してください。',
    status: 'processing',
    createdAt: new Date(Date.now() - 5000).toISOString()
  },
  {
    id: 'ai-004',
    serviceType: 'llm',
    serviceName: 'Claude 3.5 Sonnet',
    agentId: 'agent-design-001',
    agentType: 'design',
    input: 'ゲームメカニクスの詳細設計を作成してください。',
    status: 'processing',
    createdAt: new Date(Date.now() - 3000).toISOString()
  },
  {
    id: 'ai-005',
    serviceType: 'llm',
    serviceName: 'Claude 3.5 Sonnet',
    agentId: 'agent-design-001',
    agentType: 'design',
    input: 'UI/UXデザインドキュメントを作成してください。',
    status: 'pending',
    createdAt: new Date(Date.now() - 1000).toISOString()
  },
  // DALL-E requests
  {
    id: 'ai-010',
    serviceType: 'image',
    serviceName: 'DALL-E 3',
    agentId: 'agent-asset-worker-001',
    agentType: 'asset_worker',
    input: 'キャラクターデザイン: 青い球体のかわいいキャラクター',
    output: '/assets/character_ball_001.png',
    status: 'completed',
    cost: 0.04,
    duration: 15000,
    createdAt: new Date(Date.now() - 200000).toISOString(),
    completedAt: new Date(Date.now() - 185000).toISOString()
  },
  {
    id: 'ai-011',
    serviceType: 'image',
    serviceName: 'DALL-E 3',
    agentId: 'agent-asset-worker-002',
    agentType: 'asset_worker',
    input: '背景画像: 草原ステージ',
    output: '/assets/bg_grassland.png',
    status: 'completed',
    cost: 0.04,
    duration: 12000,
    createdAt: new Date(Date.now() - 180000).toISOString(),
    completedAt: new Date(Date.now() - 168000).toISOString()
  },
  {
    id: 'ai-012',
    serviceType: 'image',
    serviceName: 'DALL-E 3',
    agentId: 'agent-asset-worker-003',
    agentType: 'asset_worker',
    input: '背景画像: 洞窟ステージ',
    status: 'processing',
    createdAt: new Date(Date.now() - 8000).toISOString()
  },
  {
    id: 'ai-013',
    serviceType: 'image',
    serviceName: 'DALL-E 3',
    agentId: 'agent-world-001',
    agentType: 'world',
    input: '背景画像: 空中庭園ステージ',
    status: 'pending',
    createdAt: new Date(Date.now() - 2000).toISOString()
  },
  {
    id: 'ai-014',
    serviceType: 'image',
    serviceName: 'DALL-E 3',
    agentId: 'agent-asset-worker-001',
    agentType: 'asset_worker',
    input: 'アイテムアイコン: コイン',
    status: 'pending',
    createdAt: new Date(Date.now() - 1500).toISOString()
  },
  // Suno requests
  {
    id: 'ai-020',
    serviceType: 'music',
    serviceName: 'Suno AI',
    agentId: 'agent-asset-worker-004',
    agentType: 'asset_worker',
    input: 'BGM: 明るい草原ステージ用の音楽',
    output: '/assets/bgm_grassland.mp3',
    status: 'completed',
    cost: 0.10,
    duration: 45000,
    createdAt: new Date(Date.now() - 400000).toISOString(),
    completedAt: new Date(Date.now() - 355000).toISOString()
  },
  {
    id: 'ai-021',
    serviceType: 'music',
    serviceName: 'Suno AI',
    agentId: 'agent-asset-worker-004',
    agentType: 'asset_worker',
    input: 'BGM: 神秘的な洞窟ステージ用の音楽',
    status: 'processing',
    createdAt: new Date(Date.now() - 30000).toISOString()
  },
  {
    id: 'ai-022',
    serviceType: 'music',
    serviceName: 'Suno AI',
    agentId: 'agent-asset-worker-005',
    agentType: 'asset_worker',
    input: 'BGM: 壮大な空中庭園ステージ用の音楽',
    status: 'pending',
    createdAt: new Date(Date.now() - 500).toISOString()
  },
  // ElevenLabs requests
  {
    id: 'ai-030',
    serviceType: 'audio',
    serviceName: 'ElevenLabs',
    agentId: 'agent-character-001',
    agentType: 'character',
    input: 'ナレーション: 「ようこそ、ボールの冒険へ！」',
    output: '/assets/audio/narration_001.mp3',
    status: 'completed',
    cost: 0.02,
    duration: 8000,
    createdAt: new Date(Date.now() - 150000).toISOString(),
    completedAt: new Date(Date.now() - 142000).toISOString()
  },
  {
    id: 'ai-031',
    serviceType: 'audio',
    serviceName: 'ElevenLabs',
    agentId: 'agent-character-001',
    agentType: 'character',
    input: 'ナレーション: 「ステージクリア！」',
    status: 'completed',
    cost: 0.02,
    duration: 6000,
    createdAt: new Date(Date.now() - 140000).toISOString(),
    completedAt: new Date(Date.now() - 134000).toISOString()
  }
]

export default function AIView(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { tabResetCounter } = useNavigationStore()
  const [requests, setRequests] = useState<AIRequest[]>([])
  const [filterType, setFilterType] = useState<AIServiceType | 'all'>('all')
  const [filterAgent, setFilterAgent] = useState<AgentType | 'all'>('all')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())

  // Reset expanded state when tab is clicked (even if same tab)
  useEffect(() => {
    setExpandedGroups(new Set())
  }, [tabResetCounter])

  useEffect(() => {
    if (!currentProject) {
      setRequests([])
      return
    }
    setRequests(mockRequests)
  }, [currentProject?.id])

  // Get unique agent types from requests
  const availableAgentTypes = useMemo<AgentType[]>(() => {
    const types = new Set<AgentType>()
    requests.forEach(r => types.add(r.agentType))
    return Array.from(types)
  }, [requests])

  // Group requests by serviceName
  const groupedRequests = useMemo<GroupedRequests[]>(() => {
    let filtered = requests

    if (filterType !== 'all') {
      filtered = filtered.filter(r => r.serviceType === filterType)
    }

    if (filterAgent !== 'all') {
      filtered = filtered.filter(r => r.agentType === filterAgent)
    }

    const groups = new Map<string, AIRequest[]>()

    filtered.forEach(req => {
      const existing = groups.get(req.serviceName) || []
      groups.set(req.serviceName, [...existing, req])
    })

    return Array.from(groups.entries()).map(([serviceName, reqs]) => ({
      serviceName,
      serviceType: reqs[0].serviceType,
      requests: reqs.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()),
      stats: {
        total: reqs.length,
        completed: reqs.filter(r => r.status === 'completed').length,
        processing: reqs.filter(r => r.status === 'processing').length,
        pending: reqs.filter(r => r.status === 'pending').length,
        failed: reqs.filter(r => r.status === 'failed').length,
        totalCost: reqs.reduce((sum, r) => sum + (r.cost || 0), 0),
        totalTokens: reqs.reduce((sum, r) => sum + (r.tokensUsed || 0), 0)
      }
    }))
  }, [requests, filterType, filterAgent])

  const toggleGroup = (serviceName: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      if (next.has(serviceName)) {
        next.delete(serviceName)
      } else {
        next.add(serviceName)
      }
      return next
    })
  }

  const stats = {
    total: requests.length,
    completed: requests.filter(r => r.status === 'completed').length,
    processing: requests.filter(r => r.status === 'processing').length,
    pending: requests.filter(r => r.status === 'pending').length,
    failed: requests.filter(r => r.status === 'failed').length
  }

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`
    return `${(ms / 1000).toFixed(1)}秒`
  }

  if (!currentProject) {
    return (
      <div className="p-4 animate-nier-fade-in">
        <div className="nier-page-header-row">
          <div className="nier-page-header-left">
            <h1 className="nier-page-title">AI</h1>
            <span className="nier-page-subtitle">- 外部AI連携</span>
          </div>
          <div className="nier-page-header-right" />
        </div>
        <Card>
          <CardContent>
            <div className="text-center py-12 text-nier-text-light">
              <FolderOpen size={48} className="mx-auto mb-4 opacity-50" />
              <p className="text-nier-body">プロジェクトを選択してください</p>
            </div>
          </CardContent>
        </Card>
      </div>
    )
  }

  return (
    <div className="p-4 animate-nier-fade-in">
      {/* Header */}
      <div className="nier-page-header-row">
        <div className="nier-page-header-left">
          <h1 className="nier-page-title">AI</h1>
          <span className="nier-page-subtitle">- 外部AI連携</span>
        </div>
        <div className="nier-page-header-right" />
      </div>

      {/* Filter */}
      <Card className="mb-3">
        <CardContent className="py-1.5 space-y-1.5">
          {/* Service Filter */}
          <div className="flex items-center gap-1 flex-wrap">
            <span className="text-nier-caption text-nier-text-light w-16">Service:</span>
            <button
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 text-nier-small tracking-nier transition-colors',
                filterType === 'all'
                  ? 'bg-nier-bg-selected text-nier-text-main'
                  : 'text-nier-text-light hover:bg-nier-bg-panel'
              )}
              onClick={() => setFilterType('all')}
            >
              <Zap size={14} />
              全て
              <span className="text-nier-caption opacity-70">({requests.length})</span>
            </button>
            {(Object.keys(serviceConfig) as AIServiceType[]).map(type => {
              const config = serviceConfig[type]
              const Icon = config.icon
              const count = requests.filter(r => r.serviceType === type).length
              if (count === 0) return null
              return (
                <button
                  key={type}
                  className={cn(
                    'flex items-center gap-2 px-3 py-1.5 text-nier-small tracking-nier transition-colors',
                    filterType === type
                      ? 'bg-nier-bg-selected text-nier-text-main'
                      : 'text-nier-text-light hover:bg-nier-bg-panel'
                  )}
                  onClick={() => setFilterType(type)}
                >
                  <Icon size={14} />
                  {config.label}
                  <span className="text-nier-caption opacity-70">({count})</span>
                </button>
              )
            })}
          </div>

          {/* Agent Filter */}
          <div className="flex items-center gap-1 flex-wrap border-t border-nier-border-light pt-2">
            <span className="text-nier-caption text-nier-text-light w-16">Agent:</span>
            <button
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 text-nier-small tracking-nier transition-colors',
                filterAgent === 'all'
                  ? 'bg-nier-bg-selected text-nier-text-main'
                  : 'text-nier-text-light hover:bg-nier-bg-panel'
              )}
              onClick={() => setFilterAgent('all')}
            >
              <Bot size={14} />
              全て
              <span className="text-nier-caption opacity-70">({requests.length})</span>
            </button>
            {availableAgentTypes.map(type => {
              const config = agentConfig[type]
              const count = requests.filter(r => r.agentType === type).length
              return (
                <button
                  key={type}
                  className={cn(
                    'flex items-center gap-2 px-3 py-2 text-nier-small tracking-nier transition-colors',
                    filterAgent === type
                      ? 'bg-nier-bg-selected text-nier-text-main'
                      : 'text-nier-text-light hover:bg-nier-bg-panel'
                  )}
                  onClick={() => setFilterAgent(type)}
                >
                  {config.shortLabel}
                  <span className="text-nier-caption opacity-70">({count})</span>
                </button>
              )
            })}
          </div>
        </CardContent>
      </Card>

      {/* Grouped Request List */}
      <div className="space-y-4 nier-scroll-list">
        {groupedRequests.length === 0 ? (
          <Card>
            <CardContent>
              <div className="text-center py-8 text-nier-text-light">
                <Zap size={32} className="mx-auto mb-2 opacity-50" />
                <p className="text-nier-small">AIリクエストがありません</p>
              </div>
            </CardContent>
          </Card>
        ) : (
          groupedRequests.map(group => {
            const serviceConf = serviceConfig[group.serviceType]
            const ServiceIcon = serviceConf.icon
            const isExpanded = expandedGroups.has(group.serviceName)

            return (
              <Card key={group.serviceName}>
                {/* Group Header */}
                <div
                  className="flex items-center justify-between p-4 cursor-pointer hover:bg-nier-bg-panel transition-colors"
                  onClick={() => toggleGroup(group.serviceName)}
                >
                  <div className="flex items-center gap-3">
                    {isExpanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                    <ServiceIcon size={18} className={serviceConf.color} />
                    <span className="text-nier-body font-medium text-nier-text-main">
                      {group.serviceName}
                    </span>
                    <span className={cn('text-nier-caption', serviceConf.color)}>
                      [{serviceConf.label}]
                    </span>
                  </div>

                  <div className="flex items-center gap-4 text-nier-small">
                    <span className="text-nier-text-light">{group.stats.completed}完了</span>
                    {group.stats.processing > 0 && (
                      <span className="text-nier-text-light flex items-center gap-1">
                        <Loader2 size={12} className="animate-spin" />
                        {group.stats.processing}処理中
                      </span>
                    )}
                    {group.stats.pending > 0 && (
                      <span className="text-nier-text-light">{group.stats.pending}待機中</span>
                    )}
                    {group.stats.failed > 0 && (
                      <span className="text-nier-text-light">{group.stats.failed}エラー</span>
                    )}
                    <span className="text-nier-text-main font-medium border-l border-nier-border-light pl-4">
                      {group.stats.total}件
                    </span>
                    {group.stats.totalCost > 0 && (
                      <span className="text-nier-text-main">${group.stats.totalCost.toFixed(3)}</span>
                    )}
                  </div>
                </div>

                {/* Expanded Request List */}
                {isExpanded && (
                  <CardContent className="pt-0 border-t border-nier-border-light">
                    <div className="divide-y divide-nier-border-light">
                      {group.requests.map(request => {
                        const statusConf = statusConfig[request.status]
                        const StatusIcon = statusConf.icon

                        return (
                          <div key={request.id} className="py-3">
                            <div className="flex items-start justify-between mb-2">
                              <div className="flex items-center gap-3">
                                <div className={cn(
                                  'flex items-center gap-1 text-nier-caption px-2 py-0.5',
                                  statusConf.color,
                                  request.status === 'processing' && 'animate-pulse'
                                )}>
                                  <StatusIcon size={12} className={request.status === 'processing' ? 'animate-spin' : ''} />
                                  {statusConf.label}
                                </div>
                                {/* Agent Badge */}
                                <div className="flex items-center gap-1 text-nier-caption px-2 py-0.5 bg-nier-bg-panel border border-nier-border-light">
                                  <Bot size={10} className="text-nier-text-light" />
                                  <span className="text-nier-text-main">{agentConfig[request.agentType].shortLabel}</span>
                                </div>
                              </div>
                              <div className="flex items-center gap-3 text-nier-caption text-nier-text-light">
                                <span className="flex items-center gap-1">
                                  <Clock size={10} />
                                  {new Date(request.createdAt).toLocaleTimeString('ja-JP')}
                                </span>
                                {request.duration && (
                                  <span>{formatDuration(request.duration)}</span>
                                )}
                                {request.tokensUsed && (
                                  <span>{request.tokensUsed.toLocaleString()}tk</span>
                                )}
                                {request.cost && (
                                  <span className="text-nier-text-main">${request.cost.toFixed(3)}</span>
                                )}
                              </div>
                            </div>

                            {/* Input */}
                            <div className="mb-2">
                              <span className="text-nier-caption text-nier-text-light mr-2">IN:</span>
                              <span className="text-nier-small text-nier-text-light">
                                {request.input}
                              </span>
                            </div>

                            {/* Output */}
                            {request.output && (
                              <div className="p-2 bg-nier-bg-main border-l-2 border-nier-border-dark">
                                <span className="text-nier-caption text-nier-text-light mr-2">OUT:</span>
                                <span className="text-nier-small text-nier-text-main whitespace-pre-wrap">
                                  {request.output.length > 150 ? `${request.output.slice(0, 150)}...` : request.output}
                                </span>
                              </div>
                            )}

                            {/* Error */}
                            {request.error && (
                              <div className="p-2 bg-nier-bg-panel border-l-2 border-nier-border-dark">
                                <span className="text-nier-caption text-nier-text-light">
                                  {request.error}
                                </span>
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </CardContent>
                )}
              </Card>
            )
          })
        )}
      </div>

      {/* Summary */}
      <Card className="mt-6">
        <CardContent className="py-3">
          <div className="flex items-center justify-between text-nier-small">
            <div className="flex items-center gap-6 text-nier-text-light">
              <span>総リクエスト: <span className="text-nier-text-main">{stats.total}</span></span>
              <span>完了率: <span className="text-nier-text-main">{stats.total > 0 ? Math.round((stats.completed / stats.total) * 100) : 0}%</span></span>
            </div>
            <div className="flex items-center gap-4">
              {requests.reduce((sum, r) => sum + (r.tokensUsed || 0), 0) > 0 && (
                <span className="text-nier-text-light">
                  総トークン: <span className="text-nier-text-main">{requests.reduce((sum, r) => sum + (r.tokensUsed || 0), 0).toLocaleString()}</span>
                </span>
              )}
              <span className="text-nier-text-light">
                総コスト: <span className="text-nier-text-main">${requests.reduce((sum, r) => sum + (r.cost || 0), 0).toFixed(3)}</span>
              </span>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
