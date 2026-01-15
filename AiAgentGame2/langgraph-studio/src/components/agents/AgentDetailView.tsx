import { useState } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { Progress } from '@/components/ui/Progress'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { AgentLogStreaming } from './AgentLog'
import type { Agent, AgentLogEntry } from '@/types/agent'
import { cn } from '@/lib/utils'
import {
  ArrowLeft,
  Pause,
  RotateCcw,
  Clock,
  Cpu,
  Activity,
  FileText
} from 'lucide-react'

interface AgentDetailViewProps {
  agent: Agent
  logs: AgentLogEntry[]
  onBack: () => void
  onRetry?: () => void
  onPause?: () => void
}

const statusLabels: Record<string, { text: string; color: string }> = {
  pending: { text: '待機中', color: 'text-nier-text-light' },
  running: { text: '実行中', color: 'text-nier-accent-orange' },
  completed: { text: '完了', color: 'text-nier-accent-green' },
  failed: { text: 'エラー', color: 'text-nier-accent-red' },
  blocked: { text: 'ブロック', color: 'text-nier-accent-yellow' }
}

const agentTypeLabels: Record<string, string> = {
  concept: 'コンセプトエージェント',
  design: 'デザインエージェント',
  scenario: 'シナリオエージェント',
  character: 'キャラクターエージェント',
  world: 'ワールドエージェント',
  task_split: 'タスク分割エージェント',
  code_leader: 'コードリーダーエージェント',
  asset_leader: 'アセットリーダーエージェント',
  code_worker: 'コードワーカーエージェント',
  asset_worker: 'アセットワーカーエージェント',
  integrator: 'インテグレーターエージェント',
  tester: 'テスターエージェント',
  reviewer: 'レビュアーエージェント'
}

export default function AgentDetailView({
  agent,
  logs,
  onBack,
  onRetry,
  onPause
}: AgentDetailViewProps): JSX.Element {
  const [showMetadata, setShowMetadata] = useState(false)

  const status = statusLabels[agent.status]

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

  return (
    <div className="p-6 animate-nier-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <div
              className={cn(
                'w-1.5 h-6',
                agent.status === 'running' && 'bg-nier-accent-orange animate-nier-pulse',
                agent.status === 'completed' && 'bg-nier-accent-green',
                agent.status === 'failed' && 'bg-nier-accent-red',
                agent.status === 'pending' && 'bg-[#8A857A]',
                agent.status === 'blocked' && 'bg-nier-accent-yellow'
              )}
            />
            <h1 className="text-nier-h1 font-medium tracking-nier-wide">
              {agentTypeLabels[agent.type] || agent.type.toUpperCase()}
            </h1>
          </div>
          <div className="flex items-center gap-4 text-nier-small text-nier-text-light ml-4">
            <span className={status.color}>{status.text}</span>
            <span>|</span>
            <span>ID: {agent.id.slice(0, 8)}...</span>
          </div>
        </div>
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft size={16} />
          <span className="ml-1.5">戻る</span>
        </Button>
      </div>

      {/* Main Content */}
      <div className="grid grid-cols-3 gap-5">
        {/* Left Column - Status & Controls */}
        <div className="space-y-4">
          {/* Progress Card */}
          <Card>
            <CardHeader>
              <DiamondMarker>進捗</DiamondMarker>
            </CardHeader>
            <CardContent className="space-y-4">
              <Progress value={agent.progress} className="h-3" />
              <div className="flex justify-between text-nier-small">
                <span className="text-nier-text-light">完了率</span>
                <span className="text-nier-text-main">{agent.progress}%</span>
              </div>
              {agent.currentTask && (
                <div className="pt-3 border-t border-nier-border-light">
                  <span className="text-nier-caption text-nier-text-light block mb-1">
                    現在のタスク:
                  </span>
                  <span className="text-nier-small text-nier-text-main">
                    {agent.currentTask}
                  </span>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Metrics Card */}
          <Card>
            <CardHeader>
              <DiamondMarker>メトリクス</DiamondMarker>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-nier-small text-nier-text-light">
                    <Clock size={14} />
                    実行時間
                  </span>
                  <span className="text-nier-small text-nier-text-main">
                    {getRuntime()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-nier-small text-nier-text-light">
                    <Activity size={14} />
                    Token使用量
                  </span>
                  <span className="text-nier-small text-nier-text-main">
                    {agent.tokensUsed.toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2 text-nier-small text-nier-text-light">
                    <FileText size={14} />
                    ログエントリ
                  </span>
                  <span className="text-nier-small text-nier-text-main">
                    {logs.length}
                  </span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Actions Card */}
          <Card>
            <CardHeader className="bg-nier-accent-blue">
              <span className="flex items-center gap-2 text-white">
                <Cpu size={14} />
                コントロール
              </span>
            </CardHeader>
            <CardContent className="space-y-3">
              {agent.status === 'running' && onPause && (
                <Button className="w-full justify-start gap-3" onClick={onPause}>
                  <Pause size={16} />
                  一時停止
                </Button>
              )}
              {(agent.status === 'failed' || agent.status === 'blocked') && onRetry && (
                <Button
                  variant="success"
                  className="w-full justify-start gap-3"
                  onClick={onRetry}
                >
                  <RotateCcw size={16} />
                  リトライ
                </Button>
              )}
              <Button
                variant="ghost"
                className="w-full justify-start gap-3 text-nier-text-light"
                onClick={() => setShowMetadata(!showMetadata)}
              >
                <FileText size={16} />
                {showMetadata ? 'メタデータを隠す' : 'メタデータを表示'}
              </Button>
            </CardContent>
          </Card>

          {/* Metadata (conditional) */}
          {showMetadata && agent.metadata && Object.keys(agent.metadata).length > 0 && (
            <Card>
              <CardHeader>
                <DiamondMarker>メタデータ</DiamondMarker>
              </CardHeader>
              <CardContent>
                <pre className="text-nier-caption text-nier-text-light whitespace-pre-wrap bg-nier-bg-main p-3 overflow-auto max-h-[200px]">
                  {JSON.stringify(agent.metadata, null, 2)}
                </pre>
              </CardContent>
            </Card>
          )}
        </div>

        {/* Right Column - Logs (2 columns wide) */}
        <div className="col-span-2">
          <AgentLogStreaming
            logs={logs}
            isStreaming={agent.status === 'running'}
            maxHeight="600px"
          />

          {/* Error Details */}
          {agent.status === 'failed' && agent.error && (
            <Card className="mt-4 border-nier-accent-red">
              <CardHeader className="bg-nier-accent-red">
                <span className="text-white">エラー詳細</span>
              </CardHeader>
              <CardContent>
                <p className="text-nier-small text-nier-accent-red">
                  {agent.error}
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
