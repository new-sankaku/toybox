import { useState, useEffect } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { TokenTracker, CostEstimator } from '@/components/analytics'
import { Progress } from '@/components/ui/Progress'
import { useProjectStore } from '@/stores/projectStore'
import { metricsApi, agentApi, type ApiAgent, type ApiProjectMetrics } from '@/services/apiService'
import { formatNumber } from '@/lib/utils'
import { TrendingUp, TrendingDown, DollarSign, Cpu, FolderOpen } from 'lucide-react'

// Pricing (Claude 3.5 Sonnet)
const PRICING = {
  inputPer1K: 0.003,
  outputPer1K: 0.015,
  inputRatio: 0.3,
  outputRatio: 0.7
}

interface TokenByAgent {
  agentId: string
  agentType: string
  agentName: string
  tokensUsed: number
  tokensEstimated: number
  timestamp: string
}

interface TokenByGroup {
  groupKey: string
  groupName: string
  agents: TokenByAgent[]
  totalTokensUsed: number
  totalTokensEstimated: number
}

// Convert API agent to TokenByAgent type
function convertToTokenByAgent(agent: ApiAgent): TokenByAgent {
  return {
    agentId: agent.id,
    agentType: agent.type,
    agentName: (agent.metadata?.displayName as string) || agent.type,
    tokensUsed: agent.tokensUsed,
    tokensEstimated: 5000, // Estimated per agent
    timestamp: agent.createdAt,
  }
}

// Group agents by leader/worker pairs
function groupAgentsByRole(agents: TokenByAgent[]): TokenByGroup[] {
  const groupMap = new Map<string, TokenByAgent[]>()

  // Define grouping rules
  const getGroupKey = (type: string): string => {
    // Remove _leader, _worker suffix to get base type
    if (type.endsWith('_leader')) return type.replace('_leader', '')
    if (type.endsWith('_worker')) return type.replace('_worker', '')
    // Standalone agents
    return type
  }

  // Group agents
  agents.forEach(agent => {
    const groupKey = getGroupKey(agent.agentType)
    if (!groupMap.has(groupKey)) {
      groupMap.set(groupKey, [])
    }
    groupMap.get(groupKey)!.push(agent)
  })

  // Group display names
  const groupNames: Record<string, string> = {
    concept: 'コンセプト',
    concept_leader: 'コンセプト',
    design: 'デザイン',
    design_leader: 'デザイン',
    scenario: 'シナリオ',
    scenario_leader: 'シナリオ',
    character: 'キャラクター',
    character_leader: 'キャラクター',
    world: 'ワールド',
    world_leader: 'ワールド',
    task_split: 'タスク分割',
    task_split_leader: 'タスク分割',
    code: 'コード',
    code_leader: 'コード',
    code_worker: 'コード',
    asset: 'アセット',
    asset_leader: 'アセット',
    asset_worker: 'アセット',
    integrator: '統合',
    integrator_leader: '統合',
    tester: 'テスト',
    tester_leader: 'テスト',
    reviewer: 'レビュー',
    reviewer_leader: 'レビュー'
  }

  // Convert to array
  return Array.from(groupMap.entries()).map(([groupKey, groupAgents]) => ({
    groupKey,
    groupName: groupNames[groupKey] || groupKey,
    agents: groupAgents,
    totalTokensUsed: groupAgents.reduce((sum, a) => sum + a.tokensUsed, 0),
    totalTokensEstimated: groupAgents.reduce((sum, a) => sum + a.tokensEstimated, 0)
  }))
}

export default function CostView(): JSX.Element {
  const { currentProject } = useProjectStore()
  const [agents, setAgents] = useState<ApiAgent[]>([])
  const [metrics, setMetrics] = useState<ApiProjectMetrics | null>(null)
  const [loading, setLoading] = useState(false)

  // Fetch data from API
  useEffect(() => {
    if (!currentProject) {
      setAgents([])
      setMetrics(null)
      return
    }

    const fetchData = async () => {
      setLoading(true)
      try {
        const [agentsData, metricsData] = await Promise.all([
          agentApi.listByProject(currentProject.id),
          metricsApi.getByProject(currentProject.id)
        ])
        setAgents(agentsData)
        setMetrics(metricsData)
      } catch (error) {
        console.error('Failed to fetch cost data:', error)
        setAgents([])
        setMetrics(null)
      } finally {
        setLoading(false)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

  // Project not selected
  if (!currentProject) {
    return (
      <div className="p-4 animate-nier-fade-in">
        <div className="nier-page-header-row">
          <div className="nier-page-header-left">
            <h1 className="nier-page-title">COST</h1>
            <span className="nier-page-subtitle">- コスト管理</span>
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

  // Convert agents to TokenByAgent format
  const tokensByAgent: TokenByAgent[] = agents.map(convertToTokenByAgent)

  // Group by leader/worker pairs
  const groupedAgents = groupAgentsByRole(tokensByAgent)

  const currentTokens = tokensByAgent.reduce((sum, t) => sum + t.tokensUsed, 0)
  const estimatedTotalTokens = tokensByAgent.reduce((sum, t) => sum + t.tokensEstimated, 0)

  const inputTokens = Math.round(currentTokens * PRICING.inputRatio)
  const outputTokens = Math.round(currentTokens * PRICING.outputRatio)
  const inputCost = (inputTokens / 1000) * PRICING.inputPer1K
  const outputCost = (outputTokens / 1000) * PRICING.outputPer1K
  const currentCost = inputCost + outputCost

  const estimatedInputTokens = Math.round(estimatedTotalTokens * PRICING.inputRatio)
  const estimatedOutputTokens = Math.round(estimatedTotalTokens * PRICING.outputRatio)
  const estimatedCost = (estimatedInputTokens / 1000) * PRICING.inputPer1K + (estimatedOutputTokens / 1000) * PRICING.outputPer1K

  const budgetLimit = 10.0 // $10 budget

  return (
    <div className="p-4 animate-nier-fade-in">
      {/* Header */}
      <div className="nier-page-header-row">
        <div className="nier-page-header-left">
          <h1 className="nier-page-title">COST</h1>
          <span className="nier-page-subtitle">- コスト管理</span>
        </div>
        <div className="nier-page-header-right" />
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-3 mb-3">
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <Cpu className="text-nier-text-light" size={24} />
              <div>
                <div className="text-nier-caption text-nier-text-light">消費トークン</div>
                <div className="text-nier-h2 font-medium">{formatNumber(currentTokens)}</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <TrendingUp className="text-nier-text-light" size={24} />
              <div>
                <div className="text-nier-caption text-nier-text-light">完了時予想</div>
                <div className="text-nier-h2 font-medium">{formatNumber(estimatedTotalTokens)}</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <DollarSign className="text-nier-text-light" size={24} />
              <div>
                <div className="text-nier-caption text-nier-text-light">現在コスト</div>
                <div className="text-nier-h2 font-medium">${currentCost.toFixed(3)}</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <TrendingDown className="text-nier-text-light" size={24} />
              <div>
                <div className="text-nier-caption text-nier-text-light">予算残り</div>
                <div className="text-nier-h2 font-medium">${(budgetLimit - currentCost).toFixed(2)}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-3">
        {/* Token Tracker */}
        <TokenTracker
          currentTokens={currentTokens}
          estimatedTotalTokens={estimatedTotalTokens}
          tokensByAgent={tokensByAgent}
          maxTokens={100000}
        />

        {/* Cost Estimator */}
        <CostEstimator
          currentCost={currentCost}
          estimatedTotalCost={estimatedCost}
          budgetLimit={budgetLimit}
          breakdown={{
            inputTokens,
            outputTokens,
            inputCost,
            outputCost
          }}
        />

        {/* Agent Token Breakdown */}
        <Card className="col-span-2">
          <CardHeader>
            <DiamondMarker>エージェント別トークン消費</DiamondMarker>
          </CardHeader>
          <CardContent className="nier-scroll-list-short">
            {loading && groupedAgents.length === 0 ? (
              <div className="text-center py-8 text-nier-text-light">
                読み込み中...
              </div>
            ) : groupedAgents.length === 0 ? (
              <div className="text-center py-8 text-nier-text-light">
                データがありません
              </div>
            ) : (
              <table className="w-full">
                <thead className="bg-nier-bg-header text-nier-text-header">
                  <tr>
                    <th className="px-4 py-2 text-left text-nier-small tracking-nier">グループ</th>
                    <th className="px-4 py-2 text-left text-nier-small tracking-nier">内訳</th>
                    <th className="px-4 py-2 text-left text-nier-small tracking-nier">消費トークン</th>
                    <th className="px-4 py-2 text-left text-nier-small tracking-nier">予想トークン</th>
                    <th className="px-4 py-2 text-left text-nier-small tracking-nier">進捗</th>
                    <th className="px-4 py-2 text-left text-nier-small tracking-nier">推定コスト</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-nier-border-light">
                  {groupedAgents.map(group => {
                    const progress = group.totalTokensEstimated > 0
                      ? Math.round((group.totalTokensUsed / group.totalTokensEstimated) * 100)
                      : 0
                    const groupCost = (group.totalTokensUsed * PRICING.inputRatio / 1000) * PRICING.inputPer1K
                      + (group.totalTokensUsed * PRICING.outputRatio / 1000) * PRICING.outputPer1K
                    // Build breakdown string
                    const breakdown = group.agents.length > 1
                      ? group.agents.map(a => {
                          const role = a.agentType.includes('leader') ? 'L' : a.agentType.includes('worker') ? 'W' : ''
                          return `${role ? role + ':' : ''}${formatNumber(a.tokensUsed)}`
                        }).join(' / ')
                      : '-'
                    return (
                      <tr key={group.groupKey} className="hover:bg-nier-bg-panel transition-colors">
                        <td className="px-4 py-3">
                          <span className="text-nier-small font-medium">{group.groupName}</span>
                          {group.agents.length > 1 && (
                            <span className="text-nier-caption text-nier-text-light ml-2">
                              ({group.agents.length}エージェント)
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-nier-caption text-nier-text-light">
                          {breakdown}
                        </td>
                        <td className="px-4 py-3 text-nier-small">
                          {formatNumber(group.totalTokensUsed)}
                        </td>
                        <td className="px-4 py-3 text-nier-small text-nier-text-light">
                          {formatNumber(group.totalTokensEstimated)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <Progress value={progress} className="w-24 h-1.5" />
                            <span className="text-nier-caption text-nier-text-light w-10">
                              {progress}%
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-nier-small text-nier-text-main">
                          ${groupCost.toFixed(4)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot className="bg-nier-bg-header text-nier-text-header">
                  <tr>
                    <td className="px-4 py-2 text-nier-small font-medium text-nier-text-header">合計</td>
                    <td className="px-4 py-2 text-nier-small text-nier-text-header">-</td>
                    <td className="px-4 py-2 text-nier-small font-medium text-nier-text-header">{formatNumber(currentTokens)}</td>
                    <td className="px-4 py-2 text-nier-small font-medium text-nier-text-header">{formatNumber(estimatedTotalTokens)}</td>
                    <td className="px-4 py-2">
                      <div className="flex items-center gap-2">
                        <Progress
                          value={estimatedTotalTokens > 0 ? Math.round((currentTokens / estimatedTotalTokens) * 100) : 0}
                          className="w-24 h-1.5"
                        />
                        <span className="text-nier-caption text-nier-text-header w-10">
                          {estimatedTotalTokens > 0 ? Math.round((currentTokens / estimatedTotalTokens) * 100) : 0}%
                        </span>
                      </div>
                    </td>
                    <td className="px-4 py-2 text-nier-small font-medium text-nier-text-header">
                      ${currentCost.toFixed(4)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            )}
          </CardContent>
        </Card>

        {/* Cost Projection */}
        <Card>
          <CardHeader>
            <DiamondMarker>コスト内訳</DiamondMarker>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between text-nier-small">
                <span className="text-nier-text-light">入力トークン ({formatNumber(inputTokens)})</span>
                <span>${inputCost.toFixed(4)}</span>
              </div>
              <div className="flex justify-between text-nier-small">
                <span className="text-nier-text-light">出力トークン ({formatNumber(outputTokens)})</span>
                <span>${outputCost.toFixed(4)}</span>
              </div>
              <div className="border-t border-nier-border-light pt-2 mt-2">
                <div className="flex justify-between text-nier-body font-medium">
                  <span>現在のコスト</span>
                  <span className="text-nier-text-main">${currentCost.toFixed(4)}</span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Budget Status */}
        <Card>
          <CardHeader>
            <DiamondMarker>予算ステータス</DiamondMarker>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              <div className="flex justify-between text-nier-small">
                <span className="text-nier-text-light">設定予算</span>
                <span>${budgetLimit.toFixed(2)}</span>
              </div>
              <div className="flex justify-between text-nier-small">
                <span className="text-nier-text-light">現在の消費</span>
                <span>${currentCost.toFixed(4)}</span>
              </div>
              <div className="flex justify-between text-nier-small">
                <span className="text-nier-text-light">完了時予想コスト</span>
                <span className="text-nier-text-main">${estimatedCost.toFixed(4)}</span>
              </div>
              <div className="border-t border-nier-border-light pt-2 mt-2">
                <div className="flex justify-between text-nier-body font-medium">
                  <span>残り予算</span>
                  <span className="text-nier-text-main">${(budgetLimit - currentCost).toFixed(2)}</span>
                </div>
              </div>
              <Progress
                value={(currentCost / budgetLimit) * 100}
                className="h-2 mt-2"
              />
              <div className="text-nier-caption text-nier-text-light text-center">
                予算の {((currentCost / budgetLimit) * 100).toFixed(1)}% を使用
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
