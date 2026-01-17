import { useState, useEffect, useRef } from 'react'
import { useProjectStore } from '@/stores/projectStore'
import { useNavigationStore } from '@/stores/navigationStore'
import { logsApi, checkpointApi, metricsApi, agentApi, assetApi, aiRequestApi, type ApiSystemLog, type ApiCheckpoint, type ApiProjectMetrics, type ApiAgent, type ApiAsset } from '@/services/apiService'
import { cn } from '@/lib/utils'
import { formatNumber } from '@/lib/utils'
import { Progress } from '@/components/ui/Progress'
import { ChevronRight, ChevronLeft } from 'lucide-react'

// Format seconds to readable time
function formatTime(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}分${Math.round(seconds % 60)}秒`
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}時間${mins}分`
}

// Format token count with k/m suffix
function formatTokenCount(count: number): string {
  if (count >= 1000000) return `${(count / 1000000).toFixed(1)}m`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}k`
  return count.toString()
}

// Calculate cost from tokens (assuming $0.003 per 1k input, $0.015 per 1k output, rough average $0.01 per 1k)
function formatCost(tokens: number): string {
  const cost = tokens * 0.00001 // $0.01 per 1k tokens
  if (cost < 0.01) return `$${cost.toFixed(4)}`
  if (cost < 1) return `$${cost.toFixed(2)}`
  return `$${cost.toFixed(2)}`
}

export default function ActivitySidebar(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { setActiveTab } = useNavigationStore()
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [metrics, setMetrics] = useState<ApiProjectMetrics | null>(null)
  const [agents, setAgents] = useState<ApiAgent[]>([])
  const [checkpoints, setCheckpoints] = useState<ApiCheckpoint[]>([])
  const [assets, setAssets] = useState<ApiAsset[]>([])
  const [logs, setLogs] = useState<ApiSystemLog[]>([])
  const [aiGenerating, setAiGenerating] = useState(0)

  // Fetch data from API
  useEffect(() => {
    if (!currentProject) {
      setMetrics(null)
      setAgents([])
      setCheckpoints([])
      setAssets([])
      setLogs([])
      setAiGenerating(0)
      return
    }

    const fetchData = async () => {
      try {
        const [metricsData, agentsData, checkpointsData, assetsData, logsData, aiStats] = await Promise.all([
          metricsApi.getByProject(currentProject.id),
          agentApi.listByProject(currentProject.id),
          checkpointApi.listByProject(currentProject.id),
          assetApi.listByProject(currentProject.id),
          logsApi.getByProject(currentProject.id),
          aiRequestApi.getStats(currentProject.id)
        ])

        setMetrics(metricsData)
        setAgents(agentsData)
        setCheckpoints(checkpointsData)
        setAssets(assetsData)
        setLogs(logsData)
        setAiGenerating(aiStats.processing + aiStats.pending)
      } catch (error) {
        console.error('Failed to fetch sidebar data:', error)
      }
    }

    fetchData()
    const interval = setInterval(fetchData, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

  // Calculate stats
  const runningAgents = agents.filter(a => a.status === 'running').length
  const completedAgents = agents.filter(a => a.status === 'completed').length
  const failedAgents = agents.filter(a => a.status === 'failed').length
  const totalAgents = agents.length

  const pendingCheckpoints = checkpoints.filter(cp => cp.status === 'pending').length
  const totalCheckpoints = checkpoints.length

  const errorLogs = logs.filter(l => l.level === 'error').length

  const totalAssets = assets.length
  const pendingAssets = assets.filter(a => a.approvalStatus === 'pending').length

  // 生成中 = AIリクエストAPIから取得（処理中 + 待機中）
  const generatingCount = aiGenerating

  // ハイライト管理
  const [highlights, setHighlights] = useState<Record<string, boolean>>({})
  const prevValues = useRef<Record<string, number>>({})

  useEffect(() => {
    const currentValues: Record<string, number> = {
      token: metrics?.totalTokensUsed || 0,
      agent: completedAgents,
      checkpoints: pendingCheckpoints,
      assets: pendingAssets,
      logs: logs.length,
      generating: generatingCount
    }

    const newHighlights: Record<string, boolean> = {}

    Object.keys(currentValues).forEach(key => {
      if (prevValues.current[key] !== undefined && prevValues.current[key] !== currentValues[key]) {
        newHighlights[key] = true
      }
    })

    if (Object.keys(newHighlights).length > 0) {
      setHighlights(prev => ({ ...prev, ...newHighlights }))

      // 1秒後にハイライト解除
      setTimeout(() => {
        setHighlights(prev => {
          const updated = { ...prev }
          Object.keys(newHighlights).forEach(key => {
            updated[key] = false
          })
          return updated
        })
      }, 1000)
    }

    prevValues.current = currentValues
  }, [metrics?.totalTokensUsed, completedAgents, pendingCheckpoints, pendingAssets, logs.length, generatingCount])

  if (!currentProject) {
    return (
      <div className={cn(
        'bg-nier-bg-panel border-l border-nier-border-light flex flex-col transition-all duration-200',
        isCollapsed ? 'w-10' : 'w-64'
      )}>
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-2 hover:bg-nier-bg-hover transition-colors border-b border-nier-border-light"
        >
          {isCollapsed ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        </button>

        {!isCollapsed && (
          <div className="flex-1 flex items-center justify-center text-nier-text-light text-nier-caption p-4 text-center">
            プロジェクト未選択
          </div>
        )}
      </div>
    )
  }

  return (
    <div className={cn(
      'bg-nier-bg-panel border-l border-nier-border-light flex flex-col transition-all duration-200',
      isCollapsed ? 'w-10' : 'w-64'
    )}>
      {/* Header */}
      <div className="flex items-center justify-between border-b border-nier-border-light">
        <button
          onClick={() => setIsCollapsed(!isCollapsed)}
          className="p-2 hover:bg-nier-bg-hover transition-colors"
        >
          {isCollapsed ? <ChevronLeft size={16} /> : <ChevronRight size={16} />}
        </button>
        {!isCollapsed && (
          <div className="pr-3 text-nier-caption text-nier-text-light">
            SUMMARY
          </div>
        )}
      </div>

      {!isCollapsed && (
        <>
          {/* Project Status - Compact */}
          <div className="px-2 py-1.5 border-b border-nier-border-light">
            <div className="flex items-center justify-between">
              <div className="text-nier-caption truncate flex-1">{currentProject.name}</div>
              <span className="text-[10px] px-1 py-0.5 border ml-1 bg-nier-bg-selected border-nier-border-light text-nier-text-light">
                {currentProject.status === 'running' ? '実行中' :
                 currentProject.status === 'paused' ? '一時停止' :
                 currentProject.status === 'completed' ? '完了' :
                 currentProject.status === 'failed' ? 'エラー' : '下書き'}
              </span>
            </div>
            {metrics && (
              <div className="mt-1">
                <div className="flex items-center justify-between text-[10px] text-nier-text-light mb-0.5">
                  <span>Phase {currentProject.currentPhase} - {metrics.phaseName}</span>
                  <span>{metrics.progressPercent}%</span>
                </div>
                <Progress value={metrics.progressPercent} className="h-1" />
              </div>
            )}
          </div>

          {/* Summary List */}
          <div className="px-2 py-1.5 text-[10px] space-y-0.5">
            <div className={cn('flex justify-between transition-colors duration-300', highlights.token && 'bg-nier-accent-yellow/30')}>
              <span className="text-nier-text-light">Token</span>
              <span className="text-nier-text-main">{metrics ? formatTokenCount(metrics.totalTokensUsed) : 0}</span>
            </div>
            <div className={cn('flex justify-between transition-colors duration-300', highlights.token && 'bg-nier-accent-yellow/30')}>
              <span className="text-nier-text-light">料金</span>
              <span className="text-nier-text-main">{metrics ? formatCost(metrics.totalTokensUsed) : '$0'}</span>
            </div>
            <div className={cn('flex justify-between transition-colors duration-300', highlights.agent && 'bg-nier-accent-yellow/30')}>
              <span className="text-nier-text-light">Agent</span>
              <span className="text-nier-text-main">{completedAgents}/{totalAgents}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-nier-text-light">経過時間</span>
              <span className="text-nier-text-main">{metrics ? formatTime(metrics.elapsedTimeSeconds) : '-'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-nier-text-light">残り時間</span>
              <span className="text-nier-text-main">{metrics?.estimatedRemainingSeconds ? formatTime(metrics.estimatedRemainingSeconds) : '-'}</span>
            </div>
            <button onClick={() => setActiveTab('checkpoints')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300', highlights.checkpoints && 'bg-nier-accent-yellow/30')}>
              <span className="text-nier-text-light">CheckPoints未承認</span>
              <span className="text-nier-text-main">{pendingCheckpoints}件</span>
            </button>
            <button onClick={() => setActiveTab('data')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300', highlights.assets && 'bg-nier-accent-yellow/30')}>
              <span className="text-nier-text-light">Asset未承認</span>
              <span className="text-nier-text-main">{pendingAssets}件</span>
            </button>
            <button onClick={() => setActiveTab('logs')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300', highlights.logs && 'bg-nier-accent-yellow/30')}>
              <span className="text-nier-text-light">Log</span>
              <span className="text-nier-text-main">{logs.length}件</span>
            </button>
            <button onClick={() => setActiveTab('agents')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300', highlights.generating && 'bg-nier-accent-yellow/30')}>
              <span className="text-nier-text-light">AI生成中</span>
              <span className="text-nier-text-main">{generatingCount}件</span>
            </button>
          </div>
        </>
      )}
    </div>
  )
}
