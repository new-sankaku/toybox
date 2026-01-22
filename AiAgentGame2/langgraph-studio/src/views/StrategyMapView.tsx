import { useState, useEffect, useRef, useMemo, useCallback } from 'react'
import { useAgentStore } from '../stores/agentStore'
import { useProjectStore } from '../stores/projectStore'
import StrategyMapCanvas from '../components/strategy-map/StrategyMapCanvas'
import { AI_SERVICES_CONFIG, TIMING, LAYOUT } from '../components/strategy-map/strategyMapConfig'
import type { MapAgent, AIService, UserNode, Connection, BubbleType, ConnectionType } from '../components/strategy-map/strategyMapTypes'
import type { AIServiceId } from '../components/strategy-map/strategyMapConfig'
import type { Agent, AgentStatus } from '../types/agent'

interface SpawnTracker {
  spawnTimes: Map<string, number>
  previousIds: Set<string>
}

function determineBubble(agent: Agent): { text: string | null; type: BubbleType | null } {
  switch (agent.status) {
    case 'running':
      return agent.currentTask
        ? { text: agent.currentTask, type: 'info' }
        : { text: null, type: null }
    case 'waiting_approval':
      return { text: '確認をお願いします', type: 'question' }
    case 'completed':
      return { text: 'タスク完了!', type: 'success' }
    case 'failed':
      return { text: agent.error || 'エラー発生', type: 'warning' }
    case 'blocked':
      return { text: 'ブロック中…', type: 'warning' }
    default:
      return { text: null, type: null }
  }
}

function computeAITarget(agent: Agent, index: number): AIServiceId | null {
  if (agent.status !== 'running') return null

  const serviceIds = AI_SERVICES_CONFIG.map(s => s.id)
  const typeHash = agent.type.split('').reduce((sum, char) => sum + char.charCodeAt(0), 0)
  return serviceIds[(typeHash + index) % serviceIds.length]
}

function convertAgentToMapAgent(
  agent: Agent,
  index: number,
  now: number,
  tracker: SpawnTracker
): MapAgent {
  const isNew = !tracker.previousIds.has(agent.id)
  if (isNew) {
    tracker.spawnTimes.set(agent.id, now)
  }

  const spawnTime = tracker.spawnTimes.get(agent.id) ?? now
  const elapsed = now - spawnTime
  const spawnProgress = Math.min(1, elapsed / TIMING.SPAWN_DURATION_MS)

  const bubble = determineBubble(agent)
  const aiTarget = computeAITarget(agent, index)

  return {
    id: agent.id,
    type: agent.type,
    status: agent.status,
    parentId: agent.parentAgentId,
    currentTask: agent.currentTask,
    aiTarget,
    bubble: bubble.text,
    bubbleType: bubble.type,
    spawnProgress,
  }
}

function generateConnections(agents: readonly MapAgent[]): Connection[] {
  const connections: Connection[] = []

  for (const agent of agents) {
    if (agent.parentId) {
      const parentExists = agents.some(a => a.id === agent.parentId)
      if (parentExists) {
        const connectionType = getParentConnectionType(agent.status)
        if (connectionType) {
          connections.push({
            id: `${connectionType}-${agent.id}`,
            fromId: connectionType === 'instruction' ? agent.parentId : agent.id,
            toId: connectionType === 'instruction' ? agent.id : agent.parentId,
            type: connectionType,
            active: true,
          })
        }
      }
    }

    if (agent.aiTarget && agent.status === 'running') {
      connections.push({
        id: `ai-${agent.id}`,
        fromId: agent.id,
        toId: agent.aiTarget,
        type: 'ai-request',
        active: true,
      })
    }

    if (agent.status === 'waiting_approval') {
      connections.push({
        id: `user-${agent.id}`,
        fromId: agent.id,
        toId: 'user',
        type: 'user-contact',
        active: true,
      })
    }
  }

  return connections
}

function getParentConnectionType(status: AgentStatus): ConnectionType | null {
  switch (status) {
    case 'running':
      return 'instruction'
    case 'waiting_approval':
      return 'confirm'
    case 'completed':
      return 'delivery'
    default:
      return null
  }
}

function positionAIServices(width: number): AIService[] {
  const count = AI_SERVICES_CONFIG.length
  const margin = LAYOUT.MARGIN_X
  const availableWidth = width - margin * 2

  return AI_SERVICES_CONFIG.map((config, index) => ({
    ...config,
    x: margin + (availableWidth / Math.max(count - 1, 1)) * index,
    y: 85,
  }))
}

export default function StrategyMapView() {
  const agents = useAgentStore(state => state.agents)
  const { currentProject } = useProjectStore()

  const containerRef = useRef<HTMLDivElement>(null)
  const trackerRef = useRef<SpawnTracker>({
    spawnTimes: new Map(),
    previousIds: new Set(),
  })

  const [dimensions, setDimensions] = useState({ width: 1000, height: 700 })
  const [mapAgents, setMapAgents] = useState<MapAgent[]>([])
  const [connections, setConnections] = useState<Connection[]>([])
  const [userNode, setUserNode] = useState<UserNode>({ x: 500, y: 600, queue: [] })

  const updateDimensions = useCallback(() => {
    const container = containerRef.current
    if (!container) return

    const rect = container.getBoundingClientRect()
    setDimensions({ width: rect.width, height: rect.height })
    setUserNode(prev => ({
      ...prev,
      x: rect.width / 2,
      y: rect.height * LAYOUT.USER_ZONE_Y + 20,
    }))
  }, [])

  useEffect(() => {
    updateDimensions()
    window.addEventListener('resize', updateDimensions)
    return () => window.removeEventListener('resize', updateDimensions)
  }, [updateDimensions])

  useEffect(() => {
    const projectAgents = currentProject
      ? agents.filter(a => a.projectId === currentProject.id)
      : agents

    const now = Date.now()
    const tracker = trackerRef.current

    const mapped = projectAgents.map((agent, index) =>
      convertAgentToMapAgent(agent, index, now, tracker)
    )

    tracker.previousIds = new Set(projectAgents.map(a => a.id))

    setMapAgents(mapped)
    setConnections(generateConnections(mapped))

    const waitingIds = mapped
      .filter(a => a.status === 'waiting_approval')
      .map(a => a.id)
    setUserNode(prev => ({ ...prev, queue: waitingIds }))
  }, [agents, currentProject])

  useEffect(() => {
    const intervalId = setInterval(() => {
      setMapAgents(prev =>
        prev.map(agent => {
          if (agent.spawnProgress >= 1) return agent
          const newProgress = Math.min(1, agent.spawnProgress + 0.025)
          return { ...agent, spawnProgress: newProgress }
        })
      )
    }, 16)

    return () => clearInterval(intervalId)
  }, [])

  const aiServices = useMemo(
    () => positionAIServices(dimensions.width),
    [dimensions.width]
  )

  const stats = useMemo(() => ({
    running: mapAgents.filter(a => a.status === 'running').length,
    waiting: mapAgents.filter(a => a.status === 'waiting_approval').length,
    completed: mapAgents.filter(a => a.status === 'completed').length,
    total: mapAgents.length,
  }), [mapAgents])

  return (
    <div className="h-full flex flex-col">
      <div className="nier-page-header-row mb-2">
        <h1 className="nier-page-title">戦略マップ</h1>
        <div className="flex gap-4 text-nier-small">
          <span className="text-nier-accent-orange">稼働: {stats.running}</span>
          <span className="text-nier-accent-yellow">待機: {stats.waiting}</span>
          <span className="text-nier-accent-green">完了: {stats.completed}</span>
          <span className="text-nier-text-light">計: {stats.total}</span>
        </div>
      </div>
      <div className="text-nier-caption text-nier-text-light mb-1">
        ホイール: ズーム / ドラッグ: パン
      </div>
      <div
        ref={containerRef}
        className="flex-1 border border-nier-border-light rounded overflow-hidden bg-nier-bg-main"
      >
        <StrategyMapCanvas
          agents={mapAgents}
          aiServices={aiServices}
          user={userNode}
          connections={connections}
          width={dimensions.width}
          height={dimensions.height}
        />
      </div>
    </div>
  )
}
