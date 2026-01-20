import { useState, useMemo, useEffect } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { useProjectStore } from '@/stores/projectStore'
import { useAgentDefinitionStore } from '@/stores/agentDefinitionStore'
import { logsApi, type ApiSystemLog } from '@/services/apiService'
import { cn } from '@/lib/utils'
import { Search, AlertCircle, Info, AlertTriangle, Bug, FolderOpen } from 'lucide-react'

interface SystemLog {
  id: string
  timestamp: string
  level: 'debug' | 'info' | 'warn' | 'error'
  source: string
  message: string
  details?: string
}

// Convert API log to frontend SystemLog type
function convertApiLog(apiLog: ApiSystemLog): SystemLog {
  return {
    id: apiLog.id,
    timestamp: apiLog.timestamp,
    level: apiLog.level,
    source: apiLog.source,
    message: apiLog.message,
    details: apiLog.details || undefined,
  }
}

// Agent sources for filtering (lowercase to match backend)
const agentSources = ['concept', 'design', 'scenario', 'character', 'world', 'System'] as const
type AgentSource = typeof agentSources[number]

type LogLevel = 'all' | 'debug' | 'info' | 'warn' | 'error'

const levelConfig = {
  debug: { icon: Bug, color: 'text-nier-text-light', bg: 'bg-nier-bg-panel' },
  info: { icon: Info, color: 'text-nier-text-light', bg: 'bg-nier-bg-panel' },
  warn: { icon: AlertTriangle, color: 'text-nier-text-light', bg: 'bg-nier-bg-panel' },
  error: { icon: AlertCircle, color: 'text-nier-text-light', bg: 'bg-nier-bg-panel' }
}

export default function LogsView(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { getLabel } = useAgentDefinitionStore()
  const [logs, setLogs] = useState<SystemLog[]>([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [filterLevel, setFilterLevel] = useState<LogLevel>('all')
  const [filterAgent, setFilterAgent] = useState<AgentSource | 'all'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedLog, setSelectedLog] = useState<SystemLog | null>(null)

  // Helper to get agent display name
  const getAgentDisplayName = (source: AgentSource | 'all'): string => {
    if (source === 'all') return '全て'
    if (source === 'System') return 'System'
    return getLabel(source)
  }

  // Initial fetch logs from API (no polling - will be updated via WebSocket when implemented)
  useEffect(() => {
    if (!currentProject) {
      setLogs([])
      setInitialLoading(false)
      return
    }

    const fetchLogs = async () => {
      setInitialLoading(true)
      try {
        const data = await logsApi.getByProject(currentProject.id)
        setLogs(data.map(convertApiLog))
      } catch (error) {
        console.error('Failed to fetch logs:', error)
        setLogs([])
      } finally {
        setInitialLoading(false)
      }
    }

    fetchLogs()
    // Note: WebSocket event for system logs should be implemented in the future
    // Currently only initial fetch, no polling
  }, [currentProject?.id])

  // Project not selected
  if (!currentProject) {
    return (
      <div className="p-4 animate-nier-fade-in">
        <div className="nier-page-header-row">
          <div className="nier-page-header-left">
            <h1 className="nier-page-title">LOGS</h1>
            <span className="nier-page-subtitle">- システムログ</span>
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

  const filteredLogs = useMemo(() => {
    let filtered = logs

    if (filterLevel !== 'all') {
      filtered = filtered.filter(log => log.level === filterLevel)
    }

    if (filterAgent !== 'all') {
      filtered = filtered.filter(log => log.source === filterAgent)
    }

    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(log =>
        log.message.toLowerCase().includes(query) ||
        log.source.toLowerCase().includes(query)
      )
    }

    return filtered.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
  }, [logs, filterLevel, filterAgent, searchQuery])

  const levelCounts = useMemo(() => ({
    all: logs.length,
    debug: logs.filter(l => l.level === 'debug').length,
    info: logs.filter(l => l.level === 'info').length,
    warn: logs.filter(l => l.level === 'warn').length,
    error: logs.filter(l => l.level === 'error').length
  }), [logs])

  const agentCounts = useMemo(() => {
    const counts: Record<string, number> = { all: logs.filter(l => agentSources.includes(l.source as AgentSource)).length }
    agentSources.forEach(agent => {
      counts[agent] = logs.filter(l => l.source === agent).length
    })
    return counts
  }, [logs])

  const formatTime = (timestamp: string) => {
    return new Date(timestamp).toLocaleTimeString('ja-JP', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    })
  }

  return (
    <div className="p-4 animate-nier-fade-in">
      {/* Header */}
      <div className="nier-page-header-row">
        <div className="nier-page-header-left">
          <h1 className="nier-page-title">LOGS</h1>
          <span className="nier-page-subtitle">- システムログ</span>
        </div>
        <div className="nier-page-header-right" />
      </div>

      {/* Filters */}
      <Card className="mb-3">
        <CardContent className="py-3">
          <div className="space-y-3">
            {/* Level Filter Row */}
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-1 flex-wrap">
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
                  className="bg-transparent border-b border-nier-border-light px-2 py-1 text-nier-small w-48 focus:outline-none focus:border-nier-border-dark"
                  placeholder="検索..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
            </div>

            {/* Agent Filter Row */}
            <div className="flex items-center gap-2 flex-wrap border-t border-nier-border-light pt-3">
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
                      ? 'bg-nier-bg-selected text-nier-text-main'
                      : 'text-nier-text-light hover:bg-nier-bg-panel'
                  )}
                  onClick={() => setFilterAgent(agent)}
                >
                  {getAgentDisplayName(agent)} {agentCounts[agent] > 0 && `(${agentCounts[agent]})`}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid grid-cols-3 gap-3">
        {/* Log List */}
        <div className="col-span-2">
          <Card>
            <CardHeader>
              <DiamondMarker>ログ一覧</DiamondMarker>
              <span className="text-nier-caption text-nier-text-light ml-auto">
                {filteredLogs.length}件
              </span>
            </CardHeader>
            <CardContent className="p-0 nier-scroll-list">
              {initialLoading && logs.length === 0 ? (
                <div className="p-8 text-center text-nier-text-light">
                  読み込み中...
                </div>
              ) : filteredLogs.length === 0 ? (
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
                          <span className="text-nier-caption text-nier-text-light whitespace-nowrap">
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
                  <span className="text-nier-text-main">{levelCounts.error}</span>
                </div>
                <div className="flex justify-between text-nier-small">
                  <span className="text-nier-text-light">警告</span>
                  <span className="text-nier-text-main">{levelCounts.warn}</span>
                </div>
                <div className="flex justify-between text-nier-small">
                  <span className="text-nier-text-light">情報</span>
                  <span className="text-nier-text-main">{levelCounts.info}</span>
                </div>
                <div className="flex justify-between text-nier-small">
                  <span className="text-nier-text-light">デバッグ</span>
                  <span className="text-nier-text-main">{levelCounts.debug}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
