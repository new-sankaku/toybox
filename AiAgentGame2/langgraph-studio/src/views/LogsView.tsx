import { useState, useMemo } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { Button } from '@/components/ui/Button'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { cn } from '@/lib/utils'
import { Download, Trash2, Search, AlertCircle, Info, AlertTriangle, Bug } from 'lucide-react'

interface SystemLog {
  id: string
  timestamp: string
  level: 'debug' | 'info' | 'warn' | 'error'
  source: string
  message: string
  details?: string
}

// Agent sources for filtering
const agentSources = ['Concept', 'Design', 'Scenario', 'Character', 'World', 'TaskSplit', 'CodeLeader', 'AssetLeader'] as const
type AgentSource = typeof agentSources[number]

// Mock system logs
const mockSystemLogs: SystemLog[] = [
  { id: '1', timestamp: new Date(Date.now() - 1000 * 60 * 50).toISOString(), level: 'info', source: 'System', message: 'LangGraph Studio 起動' },
  { id: '2', timestamp: new Date(Date.now() - 1000 * 60 * 49).toISOString(), level: 'info', source: 'Backend', message: 'Python バックエンド起動中...' },
  { id: '3', timestamp: new Date(Date.now() - 1000 * 60 * 48).toISOString(), level: 'info', source: 'Backend', message: 'FastAPI サーバー起動 (port: 8000)' },
  { id: '4', timestamp: new Date(Date.now() - 1000 * 60 * 47).toISOString(), level: 'info', source: 'WebSocket', message: '接続確立' },
  { id: '5', timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString(), level: 'info', source: 'Project', message: 'プロジェクト "Project Aurora" 読み込み完了' },
  { id: '6', timestamp: new Date(Date.now() - 1000 * 60 * 44).toISOString(), level: 'info', source: 'Concept', message: 'コンセプトエージェント開始' },
  { id: '7', timestamp: new Date(Date.now() - 1000 * 60 * 42).toISOString(), level: 'debug', source: 'Concept', message: 'ユーザー入力解析中...', details: 'tokens: 500' },
  { id: '8', timestamp: new Date(Date.now() - 1000 * 60 * 40).toISOString(), level: 'debug', source: 'Concept', message: 'API呼び出し: claude-3-opus', details: 'tokens: 1500, latency: 2.3s' },
  { id: '9', timestamp: new Date(Date.now() - 1000 * 60 * 35).toISOString(), level: 'info', source: 'Concept', message: 'コンセプトエージェント完了 (tokens: 2450)' },
  { id: '10', timestamp: new Date(Date.now() - 1000 * 60 * 34).toISOString(), level: 'info', source: 'Checkpoint', message: 'チェックポイント作成: concept_review' },
  { id: '11', timestamp: new Date(Date.now() - 1000 * 60 * 30).toISOString(), level: 'info', source: 'Design', message: 'デザインエージェント開始' },
  { id: '12', timestamp: new Date(Date.now() - 1000 * 60 * 28).toISOString(), level: 'debug', source: 'Design', message: 'コンセプト分析中...' },
  { id: '13', timestamp: new Date(Date.now() - 1000 * 60 * 25).toISOString(), level: 'warn', source: 'System', message: 'レート制限警告: 残り呼び出し数 50/100' },
  { id: '14', timestamp: new Date(Date.now() - 1000 * 60 * 22).toISOString(), level: 'debug', source: 'Design', message: 'API呼び出し: claude-3-opus', details: 'tokens: 2200, latency: 3.1s' },
  { id: '15', timestamp: new Date(Date.now() - 1000 * 60 * 18).toISOString(), level: 'info', source: 'Design', message: 'ゲームメカニクス設計完了' },
  { id: '16', timestamp: new Date(Date.now() - 1000 * 60 * 15).toISOString(), level: 'info', source: 'Design', message: 'デザインエージェント完了 (tokens: 3200)' },
  { id: '17', timestamp: new Date(Date.now() - 1000 * 60 * 14).toISOString(), level: 'info', source: 'Checkpoint', message: 'チェックポイント作成: design_review' },
  { id: '18', timestamp: new Date(Date.now() - 1000 * 60 * 10).toISOString(), level: 'info', source: 'Scenario', message: 'シナリオエージェント開始' },
  { id: '19', timestamp: new Date(Date.now() - 1000 * 60 * 8).toISOString(), level: 'debug', source: 'Scenario', message: 'Act 1 生成中...' },
  { id: '20', timestamp: new Date(Date.now() - 1000 * 60 * 5).toISOString(), level: 'debug', source: 'Scenario', message: 'API呼び出し: claude-3-opus', details: 'tokens: 1800, latency: 2.8s' },
  { id: '21', timestamp: new Date(Date.now() - 1000 * 60 * 3).toISOString(), level: 'info', source: 'Scenario', message: 'Act 1 完了: 目覚めと旅立ち' },
  { id: '22', timestamp: new Date(Date.now() - 1000 * 60 * 2).toISOString(), level: 'info', source: 'Scenario', message: 'シナリオエージェント進行中 (65%)' },
  { id: '23', timestamp: new Date().toISOString(), level: 'debug', source: 'System', message: '現在のメモリ使用量: 245MB' }
]

type LogLevel = 'all' | 'debug' | 'info' | 'warn' | 'error'

const levelConfig = {
  debug: { icon: Bug, color: 'text-nier-text-light', bg: 'bg-nier-bg-panel' },
  info: { icon: Info, color: 'text-nier-accent-blue', bg: 'bg-nier-accent-blue/10' },
  warn: { icon: AlertTriangle, color: 'text-nier-accent-yellow', bg: 'bg-nier-accent-yellow/10' },
  error: { icon: AlertCircle, color: 'text-nier-accent-red', bg: 'bg-nier-accent-red/10' }
}

export default function LogsView(): JSX.Element {
  const [filterLevel, setFilterLevel] = useState<LogLevel>('all')
  const [filterAgent, setFilterAgent] = useState<AgentSource | 'all'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedLog, setSelectedLog] = useState<SystemLog | null>(null)

  const filteredLogs = useMemo(() => {
    let logs = mockSystemLogs

    if (filterLevel !== 'all') {
      logs = logs.filter(log => log.level === filterLevel)
    }

    if (filterAgent !== 'all') {
      logs = logs.filter(log => log.source === filterAgent)
    }

    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      logs = logs.filter(log =>
        log.message.toLowerCase().includes(query) ||
        log.source.toLowerCase().includes(query)
      )
    }

    return logs.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
  }, [filterLevel, filterAgent, searchQuery])

  const levelCounts = useMemo(() => ({
    all: mockSystemLogs.length,
    debug: mockSystemLogs.filter(l => l.level === 'debug').length,
    info: mockSystemLogs.filter(l => l.level === 'info').length,
    warn: mockSystemLogs.filter(l => l.level === 'warn').length,
    error: mockSystemLogs.filter(l => l.level === 'error').length
  }), [])

  const agentCounts = useMemo(() => {
    const counts: Record<string, number> = { all: mockSystemLogs.filter(l => agentSources.includes(l.source as AgentSource)).length }
    agentSources.forEach(agent => {
      counts[agent] = mockSystemLogs.filter(l => l.source === agent).length
    })
    return counts
  }, [])

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('ja-JP', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  }

  return (
    <div className="p-6 animate-nier-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="w-1.5 h-6 bg-nier-accent-blue" />
          <h1 className="text-nier-h1 font-medium tracking-nier-wide">
            SYSTEM LOGS
          </h1>
          <span className="text-nier-text-light">
            - Real-time Monitor
          </span>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm">
            <Download size={14} />
            <span className="ml-1.5">エクスポート</span>
          </Button>
          <Button variant="ghost" size="sm">
            <Trash2 size={14} />
            <span className="ml-1.5">クリア</span>
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card className="mb-6">
        <CardContent className="py-3">
          <div className="space-y-3">
            {/* Level Filter Row */}
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1">
                {(['all', 'error', 'warn', 'info', 'debug'] as LogLevel[]).map(level => (
                  <button
                    key={level}
                    className={cn(
                      'flex items-center gap-2 px-3 py-1.5 text-nier-small tracking-nier transition-colors',
                      filterLevel === level
                        ? 'bg-nier-bg-selected text-nier-text-main'
                        : 'text-nier-text-light hover:bg-nier-bg-panel'
                    )}
                    onClick={() => setFilterLevel(level)}
                  >
                    {level !== 'all' && (() => {
                      const Icon = levelConfig[level].icon
                      return <Icon size={14} className={levelConfig[level].color} />
                    })()}
                    <span>{level === 'all' ? '全て' : level.toUpperCase()}</span>
                    <span className="text-nier-caption">({levelCounts[level]})</span>
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <Search size={14} className="text-nier-text-light" />
                <input
                  type="text"
                  className="bg-transparent border-b border-nier-border-light px-2 py-1 text-nier-small w-48 focus:outline-none focus:border-nier-accent-blue"
                  placeholder="検索..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
            </div>

            {/* Agent Filter Row */}
            <div className="flex items-center gap-2 border-t border-nier-border-light pt-3">
              <span className="text-nier-caption text-nier-text-light mr-2">エージェント:</span>
              <button
                className={cn(
                  'px-3 py-1 text-nier-small tracking-nier transition-colors',
                  filterAgent === 'all'
                    ? 'bg-nier-bg-selected text-nier-text-main'
                    : 'text-nier-text-light hover:bg-nier-bg-panel'
                )}
                onClick={() => setFilterAgent('all')}
              >
                全て ({agentCounts.all})
              </button>
              {agentSources.map(agent => (
                <button
                  key={agent}
                  className={cn(
                    'px-3 py-1 text-nier-small tracking-nier transition-colors',
                    filterAgent === agent
                      ? 'bg-nier-accent-blue/20 text-nier-accent-blue'
                      : 'text-nier-text-light hover:bg-nier-bg-panel'
                  )}
                  onClick={() => setFilterAgent(agent)}
                >
                  {agent} {agentCounts[agent] > 0 && `(${agentCounts[agent]})`}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-3 gap-5">
        {/* Log List */}
        <div className="col-span-2">
          <Card>
            <CardHeader>
              <DiamondMarker>ログ一覧</DiamondMarker>
              <span className="text-nier-caption text-nier-text-light ml-auto">
                {filteredLogs.length}件
              </span>
            </CardHeader>
            <CardContent className="p-0 max-h-[600px] overflow-auto">
              {filteredLogs.length === 0 ? (
                <div className="p-8 text-center text-nier-text-light">
                  ログがありません
                </div>
              ) : (
                <div className="divide-y divide-nier-border-light">
                  {filteredLogs.map(log => {
                    const config = levelConfig[log.level]
                    const Icon = config.icon
                    return (
                      <div
                        key={log.id}
                        className={cn(
                          'px-4 py-2 cursor-pointer transition-colors hover:bg-nier-bg-panel',
                          selectedLog?.id === log.id && 'bg-nier-bg-selected'
                        )}
                        onClick={() => setSelectedLog(log)}
                      >
                        <div className="flex items-start gap-3">
                          <span className="text-nier-caption text-nier-text-light whitespace-nowrap">
                            {formatTime(log.timestamp)}
                          </span>
                          <span className={cn('flex items-center gap-1', config.color)}>
                            <Icon size={12} />
                          </span>
                          <span className="text-nier-caption text-nier-accent-blue whitespace-nowrap">
                            [{log.source}]
                          </span>
                          <span className="text-nier-small text-nier-text-main truncate">
                            {log.message}
                          </span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Log Details */}
        <div>
          <Card>
            <CardHeader>
              <DiamondMarker>詳細</DiamondMarker>
            </CardHeader>
            <CardContent>
              {selectedLog ? (
                <div className="space-y-4">
                  <div>
                    <span className="text-nier-caption text-nier-text-light block">タイムスタンプ</span>
                    <span className="text-nier-small">{new Date(selectedLog.timestamp).toLocaleString('ja-JP')}</span>
                  </div>
                  <div>
                    <span className="text-nier-caption text-nier-text-light block">レベル</span>
                    <span className={cn('text-nier-small', levelConfig[selectedLog.level].color)}>
                      {selectedLog.level.toUpperCase()}
                    </span>
                  </div>
                  <div>
                    <span className="text-nier-caption text-nier-text-light block">ソース</span>
                    <span className="text-nier-small">{selectedLog.source}</span>
                  </div>
                  <div>
                    <span className="text-nier-caption text-nier-text-light block">メッセージ</span>
                    <span className="text-nier-small">{selectedLog.message}</span>
                  </div>
                  {selectedLog.details && (
                    <div>
                      <span className="text-nier-caption text-nier-text-light block">詳細</span>
                      <pre className="text-nier-caption bg-nier-bg-main p-2 mt-1 overflow-auto">
                        {selectedLog.details}
                      </pre>
                    </div>
                  )}
                </div>
              ) : (
                <div className="text-center text-nier-text-light py-8">
                  ログを選択してください
                </div>
              )}
            </CardContent>
          </Card>

          {/* Stats */}
          <Card className="mt-4">
            <CardHeader>
              <DiamondMarker>統計</DiamondMarker>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                <div className="flex justify-between text-nier-small">
                  <span className="text-nier-text-light">エラー</span>
                  <span className="text-nier-accent-red">{levelCounts.error}</span>
                </div>
                <div className="flex justify-between text-nier-small">
                  <span className="text-nier-text-light">警告</span>
                  <span className="text-nier-accent-yellow">{levelCounts.warn}</span>
                </div>
                <div className="flex justify-between text-nier-small">
                  <span className="text-nier-text-light">情報</span>
                  <span className="text-nier-accent-blue">{levelCounts.info}</span>
                </div>
                <div className="flex justify-between text-nier-small">
                  <span className="text-nier-text-light">デバッグ</span>
                  <span>{levelCounts.debug}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
