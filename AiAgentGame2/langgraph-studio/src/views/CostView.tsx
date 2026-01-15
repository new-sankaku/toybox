import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { TokenTracker, CostEstimator } from '@/components/analytics'
import { Progress } from '@/components/ui/Progress'
import { formatNumber } from '@/lib/utils'
import { TrendingUp, TrendingDown, DollarSign, Cpu } from 'lucide-react'

// Mock token data by agent
const mockTokenByAgent = [
  { agentId: 'agent-concept', agentType: 'concept', agentName: 'Concept', tokensUsed: 2450, tokensEstimated: 2500, timestamp: new Date().toISOString() },
  { agentId: 'agent-design', agentType: 'design', agentName: 'Design', tokensUsed: 3200, tokensEstimated: 3500, timestamp: new Date().toISOString() },
  { agentId: 'agent-scenario', agentType: 'scenario', agentName: 'Scenario', tokensUsed: 2100, tokensEstimated: 4000, timestamp: new Date().toISOString() },
  { agentId: 'agent-character', agentType: 'character', agentName: 'Character', tokensUsed: 0, tokensEstimated: 3000, timestamp: new Date().toISOString() },
  { agentId: 'agent-world', agentType: 'world', agentName: 'World', tokensUsed: 0, tokensEstimated: 3500, timestamp: new Date().toISOString() },
  { agentId: 'agent-task_split', agentType: 'task_split', agentName: 'TaskSplit', tokensUsed: 0, tokensEstimated: 2000, timestamp: new Date().toISOString() }
]

// Pricing (Claude 3.5 Sonnet)
const PRICING = {
  inputPer1K: 0.003,
  outputPer1K: 0.015,
  inputRatio: 0.3,
  outputRatio: 0.7
}

export default function CostView(): JSX.Element {
  const currentTokens = mockTokenByAgent.reduce((sum, t) => sum + t.tokensUsed, 0)
  const estimatedTotalTokens = mockTokenByAgent.reduce((sum, t) => sum + t.tokensEstimated, 0)

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
    <div className="p-6 animate-nier-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-6 bg-nier-accent-gold" />
          <h1 className="text-nier-h1 font-medium tracking-nier-wide">
            COST
          </h1>
          <span className="text-nier-text-light">
            - トークン & コスト管理
          </span>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <Card>
          <CardContent className="py-4">
            <div className="flex items-center gap-3">
              <Cpu className="text-nier-accent-blue" size={24} />
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
              <TrendingUp className="text-nier-accent-orange" size={24} />
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
              <DollarSign className="text-nier-accent-green" size={24} />
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
              <TrendingDown className="text-nier-accent-yellow" size={24} />
              <div>
                <div className="text-nier-caption text-nier-text-light">予算残り</div>
                <div className="text-nier-h2 font-medium">${(budgetLimit - currentCost).toFixed(2)}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-2 gap-5">
        {/* Token Tracker */}
        <TokenTracker
          currentTokens={currentTokens}
          estimatedTotalTokens={estimatedTotalTokens}
          tokensByAgent={mockTokenByAgent}
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
          <CardContent>
            <table className="w-full">
              <thead className="bg-nier-bg-header text-nier-text-header">
                <tr>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">エージェント</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">消費トークン</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">予想トークン</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">進捗</th>
                  <th className="px-4 py-2 text-left text-nier-small tracking-nier">推定コスト</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-nier-border-light">
                {mockTokenByAgent.map(agent => {
                  const progress = agent.tokensEstimated > 0
                    ? Math.round((agent.tokensUsed / agent.tokensEstimated) * 100)
                    : 0
                  const agentCost = (agent.tokensUsed * PRICING.inputRatio / 1000) * PRICING.inputPer1K
                    + (agent.tokensUsed * PRICING.outputRatio / 1000) * PRICING.outputPer1K
                  return (
                    <tr key={agent.agentId} className="hover:bg-nier-bg-panel transition-colors">
                      <td className="px-4 py-3">
                        <span className="text-nier-small font-medium">{agent.agentName}</span>
                      </td>
                      <td className="px-4 py-3 text-nier-small">
                        {formatNumber(agent.tokensUsed)}
                      </td>
                      <td className="px-4 py-3 text-nier-small text-nier-text-light">
                        {formatNumber(agent.tokensEstimated)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <Progress value={progress} className="w-24 h-1.5" />
                          <span className="text-nier-caption text-nier-text-light w-10">
                            {progress}%
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-nier-small text-nier-accent-green">
                        ${agentCost.toFixed(4)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
              <tfoot className="bg-nier-bg-header text-nier-text-header">
                <tr>
                  <td className="px-4 py-2 text-nier-small font-medium text-nier-text-header">合計</td>
                  <td className="px-4 py-2 text-nier-small font-medium text-nier-text-header">{formatNumber(currentTokens)}</td>
                  <td className="px-4 py-2 text-nier-small font-medium text-nier-text-header">{formatNumber(estimatedTotalTokens)}</td>
                  <td className="px-4 py-2">
                    <div className="flex items-center gap-2">
                      <Progress
                        value={Math.round((currentTokens / estimatedTotalTokens) * 100)}
                        className="w-24 h-1.5"
                      />
                      <span className="text-nier-caption text-nier-text-header w-10">
                        {Math.round((currentTokens / estimatedTotalTokens) * 100)}%
                      </span>
                    </div>
                  </td>
                  <td className="px-4 py-2 text-nier-small font-medium text-nier-accent-green">
                    ${currentCost.toFixed(4)}
                  </td>
                </tr>
              </tfoot>
            </table>
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
                  <span className="text-nier-accent-green">${currentCost.toFixed(4)}</span>
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
                <span className="text-nier-accent-orange">${estimatedCost.toFixed(4)}</span>
              </div>
              <div className="border-t border-nier-border-light pt-2 mt-2">
                <div className="flex justify-between text-nier-body font-medium">
                  <span>残り予算</span>
                  <span className="text-nier-accent-green">${(budgetLimit - currentCost).toFixed(2)}</span>
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
