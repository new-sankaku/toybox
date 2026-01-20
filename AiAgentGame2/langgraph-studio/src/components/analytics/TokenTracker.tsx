import { useMemo } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Progress } from '@/components/ui/Progress'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { cn } from '@/lib/utils'
import { Activity, TrendingUp } from 'lucide-react'

interface TokenData {
  agentId: string
  agentType: string
  agentName?: string
  tokensUsed: number
  tokensEstimated: number
  timestamp: string
}

interface TokenTrackerProps {
  currentTokens: number
  estimatedTotalTokens: number
  tokensByAgent: TokenData[]
  maxTokens?: number
}

const getDisplayName = (data: TokenData): string => {
  return data.agentName || data.agentType
}

export default function TokenTracker({
  currentTokens,
  estimatedTotalTokens,
  tokensByAgent,
  maxTokens = 1000000
}: TokenTrackerProps): JSX.Element {
  const usagePercent = (currentTokens / maxTokens) * 100
  const estimatedPercent = (estimatedTotalTokens / maxTokens) * 100

  const sortedAgents = useMemo(() => {
    return [...tokensByAgent].sort((a, b) => b.tokensUsed - a.tokensUsed)
  }, [tokensByAgent])

  const formatTokens = (tokens: number) => {
    if (tokens >= 1000000) {
      return `${(tokens / 1000000).toFixed(2)}M`
    }
    if (tokens >= 1000) {
      return `${(tokens / 1000).toFixed(1)}K`
    }
    return tokens.toString()
  }

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>Token使用量</DiamondMarker>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Overall Progress */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <span className="text-nier-small text-nier-text-light flex items-center gap-2">
              <Activity size={14} />
              現在の使用量
            </span>
            <span className="text-nier-small text-nier-text-main">
              {formatTokens(currentTokens)} / {formatTokens(maxTokens)}
            </span>
          </div>
          <div className="relative">
            <Progress value={usagePercent} />
            {/* Estimated marker */}
            <div
              className="absolute top-0 h-full w-0.5 bg-nier-accent-orange"
              style={{ left: `${Math.min(estimatedPercent, 100)}%` }}
            />
          </div>
          <div className="flex items-center justify-between mt-2 text-nier-caption text-nier-text-light">
            <span>{usagePercent.toFixed(1)}% 使用中</span>
            <span className="flex items-center gap-1 text-nier-accent-orange">
              <TrendingUp size={12} />
              推定: {formatTokens(estimatedTotalTokens)}
            </span>
          </div>
        </div>

        {/* Agent Breakdown */}
        <div>
          <div className="flex items-center gap-2 mb-3 text-nier-small text-nier-text-light">
            <span className="w-3 h-0.5 bg-nier-accent-blue" />
            エージェント別内訳
          </div>
          <div className="space-y-3">
            {sortedAgents.length === 0 ? (
              <div className="text-center text-nier-text-light text-nier-small py-4">
                データがありません
              </div>
            ) : (
              sortedAgents.map((agent) => {
                const percent = (agent.tokensUsed / currentTokens) * 100 || 0
                return (
                  <div key={agent.agentId} className="space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="text-nier-small text-nier-text-main">
                        {getDisplayName(agent)}
                      </span>
                      <span className="text-nier-caption text-nier-text-light">
                        {formatTokens(agent.tokensUsed)}
                      </span>
                    </div>
                    <div className="h-1.5 bg-nier-bg-main overflow-hidden">
                      <div
                        className="h-full bg-nier-accent-blue transition-all duration-300"
                        style={{ width: `${percent}%` }}
                      />
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Usage Stats */}
        <div className="pt-4 border-t border-nier-border-light">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="text-nier-caption text-nier-text-light block mb-1">
                平均/エージェント
              </span>
              <span className="text-nier-body text-nier-text-main">
                {tokensByAgent.length > 0
                  ? formatTokens(Math.round(currentTokens / tokensByAgent.length))
                  : '-'}
              </span>
            </div>
            <div>
              <span className="text-nier-caption text-nier-text-light block mb-1">
                残りキャパシティ
              </span>
              <span className={cn(
                'text-nier-body',
                usagePercent > 80 ? 'text-nier-accent-red' : 'text-nier-accent-green'
              )}>
                {formatTokens(maxTokens - currentTokens)}
              </span>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
