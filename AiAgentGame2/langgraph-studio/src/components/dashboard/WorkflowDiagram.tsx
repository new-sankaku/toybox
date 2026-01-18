import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import {
  ReactFlow,
  Node,
  Edge,
  Position,
  MarkerType,
  Background,
  BackgroundVariant,
  Handle,
  useReactFlow,
  ReactFlowProvider,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { useProjectStore } from '@/stores/projectStore'
import { useAgentStore } from '@/stores/agentStore'
import { agentApi } from '@/services/apiService'
import type { Agent, AgentType, AgentStatus } from '@/types/agent'

// Agent node definition
interface AgentNodeDef {
  id: string
  type: AgentType
  label: string
  phase: number  // 0-8
  hasLW?: boolean  // Leader/Worker continuous loop check
}

// Node definitions matching new workflow structure
// L/W pairs are combined into single nodes with hasLW flag
// タスク分割は独立したPhaseとして配置
const AGENT_NODES: AgentNodeDef[] = [
  // Phase 0: 企画
  { id: 'concept', type: 'concept', label: 'コンセプト', phase: 0 },
  // Phase 1: タスク分割1
  { id: 'task_split_1', type: 'task_split_1', label: 'タスク分割1', phase: 1 },
  // Phase 2: 設計 (L/W pairs combined)
  { id: 'concept_detail', type: 'concept_detail', label: 'コンセプト詳細', phase: 2, hasLW: true },
  { id: 'scenario', type: 'scenario', label: 'シナリオ', phase: 2, hasLW: true },
  { id: 'world', type: 'world', label: '世界観', phase: 2, hasLW: true },
  { id: 'game_design', type: 'game_design', label: 'ゲームデザイン', phase: 2, hasLW: true },
  { id: 'tech_spec', type: 'tech_spec', label: '技術仕様', phase: 2, hasLW: true },
  // Phase 3: タスク分割2
  { id: 'task_split_2', type: 'task_split_2', label: 'タスク分割2', phase: 3 },
  // Phase 4: アセット
  { id: 'asset_character', type: 'asset_character', label: 'キャラ', phase: 4 },
  { id: 'asset_background', type: 'asset_background', label: '背景', phase: 4 },
  { id: 'asset_ui', type: 'asset_ui', label: 'UI', phase: 4 },
  { id: 'asset_effect', type: 'asset_effect', label: 'エフェクト', phase: 4 },
  { id: 'asset_bgm', type: 'asset_bgm', label: 'BGM', phase: 4 },
  { id: 'asset_voice', type: 'asset_voice', label: 'ボイス', phase: 4 },
  { id: 'asset_sfx', type: 'asset_sfx', label: '効果音', phase: 4 },
  // Phase 5: タスク分割3
  { id: 'task_split_3', type: 'task_split_3', label: 'タスク分割3', phase: 5 },
  // Phase 6: 実装 (L/W pairs combined)
  { id: 'code', type: 'code', label: 'コード', phase: 6, hasLW: true },
  { id: 'event', type: 'event', label: 'イベント', phase: 6, hasLW: true },
  { id: 'ui_integration', type: 'ui_integration', label: 'UI統合', phase: 6, hasLW: true },
  { id: 'asset_integration', type: 'asset_integration', label: 'アセット統合', phase: 6, hasLW: true },
  // Phase 7: タスク分割4
  { id: 'task_split_4', type: 'task_split_4', label: 'タスク分割4', phase: 7 },
  // Phase 8: テスト (L/W pairs combined)
  { id: 'unit_test', type: 'unit_test', label: '単体テスト', phase: 8, hasLW: true },
  { id: 'integration_test', type: 'integration_test', label: '統合テスト', phase: 8, hasLW: true },
]

// Edge definitions - workflow dependencies (simplified without L/W internal edges)
const EDGE_DEFS: Array<{ source: string; target: string }> = [
  // Phase 0 → 1
  { source: 'concept', target: 'task_split_1' },
  // Phase 1 → 2: タスク分割1 → 設計エージェント
  { source: 'task_split_1', target: 'concept_detail' },
  { source: 'task_split_1', target: 'scenario' },
  { source: 'task_split_1', target: 'world' },
  { source: 'task_split_1', target: 'game_design' },
  { source: 'task_split_1', target: 'tech_spec' },
  // Phase 2 → 3: 設計 → タスク分割2
  { source: 'concept_detail', target: 'task_split_2' },
  { source: 'scenario', target: 'task_split_2' },
  { source: 'world', target: 'task_split_2' },
  { source: 'game_design', target: 'task_split_2' },
  { source: 'tech_spec', target: 'task_split_2' },
  // Phase 3 内: タスク分割2 → アセット
  { source: 'task_split_2', target: 'asset_character' },
  { source: 'task_split_2', target: 'asset_background' },
  { source: 'task_split_2', target: 'asset_ui' },
  { source: 'task_split_2', target: 'asset_effect' },
  { source: 'task_split_2', target: 'asset_bgm' },
  { source: 'task_split_2', target: 'asset_voice' },
  { source: 'task_split_2', target: 'asset_sfx' },
  // Phase 3 → 4: アセット → タスク分割3
  { source: 'asset_character', target: 'task_split_3' },
  { source: 'asset_background', target: 'task_split_3' },
  { source: 'asset_ui', target: 'task_split_3' },
  { source: 'asset_effect', target: 'task_split_3' },
  { source: 'asset_bgm', target: 'task_split_3' },
  { source: 'asset_voice', target: 'task_split_3' },
  { source: 'asset_sfx', target: 'task_split_3' },
  // Phase 4 内: タスク分割3 → 実装
  { source: 'task_split_3', target: 'code' },
  { source: 'task_split_3', target: 'event' },
  { source: 'task_split_3', target: 'ui_integration' },
  { source: 'task_split_3', target: 'asset_integration' },
  // Phase 4 → 5: 実装 → タスク分割4
  { source: 'code', target: 'task_split_4' },
  { source: 'event', target: 'task_split_4' },
  { source: 'ui_integration', target: 'task_split_4' },
  { source: 'asset_integration', target: 'task_split_4' },
  // Phase 5 内: タスク分割4 → テスト
  { source: 'task_split_4', target: 'unit_test' },
  { source: 'task_split_4', target: 'integration_test' },
]

// Layout configuration interface
interface LayoutConfig {
  nodeHeight: number
  nodeWidth: number
  phasePadding: number
  nodeGapY: number
  phaseGapX: number
  fontSize: number
}

// Find the longest label in AGENT_NODES
const MAX_LABEL_LENGTH = Math.max(...AGENT_NODES.map(n => n.label.length))  // 7 characters (e.g., コンセプト詳細, ゲームデザイン)

// Calculate layout config based on container size
function calculateLayoutConfig(containerWidth: number, containerHeight: number): LayoutConfig {
  // Constants for calculation
  const NUM_PHASES = 9
  const MAX_NODES_IN_PHASE = 7  // Phase 4 (アセット) has 7 nodes
  const MIN_NODE_HEIGHT = 28
  const MAX_NODE_HEIGHT = 60
  const MIN_FONT_SIZE = 9
  const MAX_FONT_SIZE = 14
  const NODE_PADDING_X = 12  // Horizontal padding inside node

  // Calculate available space
  const availableHeight = containerHeight - 40  // Reserve space for padding
  const availableWidth = containerWidth - 40

  // Calculate node height based on available vertical space
  const verticalFactor = MAX_NODES_IN_PHASE + 0.2 * (MAX_NODES_IN_PHASE - 1) + 0.6
  let nodeHeight = availableHeight / verticalFactor
  nodeHeight = Math.max(MIN_NODE_HEIGHT, Math.min(MAX_NODE_HEIGHT, nodeHeight))

  // Calculate node width based on available horizontal space
  // phaseGapX = nodeWidth * 0.6 for tighter layout
  const horizontalFactor = NUM_PHASES + 0.6 * (NUM_PHASES - 1) + 0.4
  let nodeWidth = availableWidth / horizontalFactor

  // Calculate font size that fits within node width
  // Japanese characters are roughly square, so width ≈ fontSize
  // nodeWidth = fontSize * MAX_LABEL_LENGTH + NODE_PADDING_X * 2
  const maxFontSizeForWidth = (nodeWidth - NODE_PADDING_X * 2) / MAX_LABEL_LENGTH

  // Also consider height constraint (font + some vertical space)
  const maxFontSizeForHeight = (nodeHeight - 8) / 1.5  // Leave room for padding and potential progress bar

  // Use the smaller of the two constraints
  let fontSize = Math.min(maxFontSizeForWidth, maxFontSizeForHeight)
  fontSize = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, fontSize))

  // Recalculate node width based on final font size to fit text perfectly
  nodeWidth = fontSize * MAX_LABEL_LENGTH + NODE_PADDING_X * 2

  return {
    nodeHeight: Math.round(nodeHeight),
    nodeWidth: Math.round(nodeWidth),
    phasePadding: Math.round(nodeHeight * 0.3),
    nodeGapY: Math.round(nodeHeight * 0.2),
    phaseGapX: Math.round(nodeWidth * 0.6),
    fontSize: Math.round(fontSize),
  }
}

// Default layout config for initial render (fontSize 11 * 7 chars + padding 24 = 101)
const DEFAULT_LAYOUT_CONFIG: LayoutConfig = {
  nodeHeight: 36,
  nodeWidth: 101,
  phasePadding: 11,
  nodeGapY: 7,
  phaseGapX: 61,
  fontSize: 11,
}

// Calculate vertical column layout dynamically based on status and layout config
function getColumnLayout(
  statusMap: Record<string, AgentStatus | undefined>,
  config: LayoutConfig
): {
  positions: Record<string, { x: number; y: number }>
  widths: Record<string, number>
  heights: Record<string, number>
  width: number
  height: number
} {
  const { nodeHeight, nodeWidth, phasePadding, nodeGapY, phaseGapX } = config
  const positions: Record<string, { x: number; y: number }> = {}
  const widths: Record<string, number> = {}
  const heights: Record<string, number> = {}

  // All nodes use the same dimensions now
  AGENT_NODES.forEach(node => {
    widths[node.id] = nodeWidth
    heights[node.id] = nodeHeight
  })

  // Group nodes by phase (phases 0-8)
  const phaseNodes: (typeof AGENT_NODES)[] = []
  for (let i = 0; i <= 8; i++) {
    phaseNodes[i] = AGENT_NODES.filter(n => n.phase === i)
  }

  // All phases use the same width
  const phaseWidths = phaseNodes.map(nodes => nodes.length > 0 ? nodeWidth : 0)

  // Calculate total heights for each phase (sum of node heights + gaps)
  const calcPhaseHeight = (nodes: typeof AGENT_NODES) => {
    if (nodes.length === 0) return 0
    const totalNodeHeights = nodes.length * nodeHeight
    const totalGaps = (nodes.length - 1) * nodeGapY
    return totalNodeHeights + totalGaps
  }

  const phaseHeights = phaseNodes.map(calcPhaseHeight)
  const maxHeight = Math.max(...phaseHeights)

  // X positions for each phase
  const phaseX: number[] = []
  phaseX[0] = phasePadding
  for (let i = 1; i <= 8; i++) {
    phaseX[i] = phaseX[i - 1] + (phaseWidths[i - 1] > 0 ? phaseWidths[i - 1] + phaseGapX : 0)
  }

  // Position nodes vertically within each phase (top-aligned)
  const positionPhaseNodes = (nodes: typeof AGENT_NODES, x: number) => {
    let currentY = phasePadding
    nodes.forEach((node) => {
      positions[node.id] = {
        x: x,
        y: currentY,
      }
      currentY += nodeHeight + nodeGapY
    })
  }

  // Position all phases
  for (let i = 0; i <= 8; i++) {
    if (phaseNodes[i].length > 0) {
      positionPhaseNodes(phaseNodes[i], phaseX[i])
    }
  }

  const totalWidth = phaseX[8] + phaseWidths[8] + phasePadding
  const totalHeight = maxHeight + phasePadding * 2

  return { positions, widths, heights, width: totalWidth, height: totalHeight }
}

// Calculate phase group bounds dynamically
function calculatePhaseBounds(
  phase: number,
  positions: Record<string, { x: number; y: number }>,
  widths: Record<string, number>,
  heights: Record<string, number>,
  config: LayoutConfig
): { x: number; y: number; width: number; height: number } {
  const phaseNodes = AGENT_NODES.filter(n => n.phase === phase)
  if (phaseNodes.length === 0) {
    return { x: 0, y: 0, width: 0, height: 0 }
  }

  const nodePositions = phaseNodes.map(n => positions[n.id])
  const nodeWidths = phaseNodes.map(n => widths[n.id])
  const nodeHeights = phaseNodes.map(n => heights[n.id])

  const minX = Math.min(...nodePositions.map(p => p.x))
  const maxX = Math.max(...nodePositions.map((p, i) => p.x + nodeWidths[i]))
  const minY = Math.min(...nodePositions.map(p => p.y))
  const maxY = Math.max(...nodePositions.map((p, i) => p.y + nodeHeights[i]))

  return {
    x: minX - config.phasePadding,
    y: minY - config.phasePadding,
    width: (maxX - minX) + config.phasePadding * 2,
    height: (maxY - minY) + config.phasePadding * 2 + 20,
  }
}

// Get status style
function getStatusStyle(status: AgentStatus | undefined): {
  background: string
  border: string
  color: string
} {
  switch (status) {
    case 'completed':
      return { background: '#A8A090', border: '#454138', color: '#454138' }
    case 'running':
      return { background: '#C4956C', border: '#8B6914', color: '#454138' }
    case 'waiting_approval':
      return { background: '#D4C896', border: '#8B7914', color: '#454138' }
    case 'failed':
      return { background: '#B85C5C', border: '#8B2020', color: '#E8E4D4' }
    case 'blocked':
      return { background: '#DAD5C3', border: '#B85C5C', color: '#5A5548' }
    case 'pending':
    default:
      return { background: '#E8E4D4', border: 'rgba(69, 65, 56, 0.3)', color: '#8A8578' }
  }
}

// Custom agent node component
interface AgentNodeData {
  label: string
  status?: AgentStatus
  progress?: number
  hasLW?: boolean
  nodeWidth: number
  nodeHeight: number
  fontSize: number
}

function AgentNode({ data }: { data: AgentNodeData }) {
  const style = getStatusStyle(data.status)
  const isRunning = data.status === 'running'
  const isCompleted = data.status === 'completed'
  const isWaitingApproval = data.status === 'waiting_approval'
  const progress = data.progress ?? 0
  const { nodeWidth, nodeHeight, fontSize } = data

  return (
    <div
      className={`relative rounded text-center flex flex-col justify-center ${isRunning || isWaitingApproval ? 'animate-pulse' : ''}`}
      style={{
        background: style.background,
        border: `1.5px solid ${style.border}`,
        color: style.color,
        width: nodeWidth,
        height: nodeHeight,
        boxShadow: isRunning ? `0 0 8px ${style.border}` : isWaitingApproval ? `0 0 6px ${style.border}` : 'none',
      }}
    >
      {/* Connection handles - invisible but needed for edge connections */}
      <Handle type="target" position={Position.Left} id="left" style={{ opacity: 0, width: 1, height: 1 }} />
      <Handle type="target" position={Position.Top} id="top" style={{ opacity: 0, width: 1, height: 1 }} />
      <Handle type="source" position={Position.Right} id="right" style={{ opacity: 0, width: 1, height: 1 }} />
      <Handle type="source" position={Position.Bottom} id="bottom" style={{ opacity: 0, width: 1, height: 1 }} />

      <div className="font-medium whitespace-nowrap" style={{ fontSize }}>{data.label}</div>
      {(isRunning || isCompleted) && (
        <div className="mt-1 px-2">
          <div className="h-1 bg-black/10 rounded-full overflow-hidden">
            <div
              className="h-full transition-all duration-300"
              style={{
                width: `${progress}%`,
                background: isCompleted ? '#7AAA7A' : '#8B6914',
              }}
            />
          </div>
          {isRunning && (
            <div className="mt-0.5" style={{ fontSize: fontSize * 0.8, color: '#8B6914' }}>
              {progress}%
            </div>
          )}
        </div>
      )}
      {/* L/W indicator in bottom right */}
      {data.hasLW && (
        <div
          className="absolute"
          style={{
            bottom: '2px',
            right: '4px',
            fontSize: fontSize * 0.7,
            color: style.color,
            opacity: 0.7,
          }}
        >
          L/W
        </div>
      )}
      {isCompleted && (
        <div
          className="absolute -top-1 -right-1 w-4 h-4 bg-[#7AAA7A] rounded-full flex items-center justify-center"
          style={{ fontSize: fontSize * 0.8, color: 'white', fontWeight: 'bold' }}
        >
          ✓
        </div>
      )}
      {isWaitingApproval && (
        <div
          className="absolute -top-1 -right-1 w-4 h-4 bg-[#8B7914] rounded-full flex items-center justify-center"
          style={{ fontSize: fontSize * 0.8, color: 'white', fontWeight: 'bold' }}
        >
          !
        </div>
      )}
    </div>
  )
}

// Phase group node component
function PhaseGroupNode({ data }: { data: { label: string; width: number; height: number } }) {
  return (
    <div
      style={{
        width: data.width,
        height: data.height,
        background: 'rgba(69, 65, 56, 0.04)',
        border: '1px dashed rgba(69, 65, 56, 0.2)',
        borderRadius: '4px',
        position: 'relative',
      }}
    >
      <div
        style={{
          position: 'absolute',
          bottom: '4px',
          left: '8px',
          fontSize: '11px',
          color: '#5A5548',
          fontWeight: 500,
        }}
      >
        {data.label}
      </div>
    </div>
  )
}

// Node types for React Flow
const nodeTypes = {
  agent: AgentNode,
  phaseGroup: PhaseGroupNode,
}

// Inner flow canvas with resize handling
interface FlowCanvasProps {
  nodes: Node[]
  edges: Edge[]
  onContainerResize: (width: number, height: number) => void
}

function FlowCanvas({ nodes, edges, onContainerResize }: FlowCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const { fitView } = useReactFlow()
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })

  // Observe container size changes
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const resizeObserver = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        setContainerSize({ width, height })
        onContainerResize(width, height)
      }
    })

    resizeObserver.observe(container)
    return () => resizeObserver.disconnect()
  }, [onContainerResize])

  // Fit view when nodes change or container size changes
  useEffect(() => {
    if (containerSize.width > 0 && containerSize.height > 0 && nodes.length > 0) {
      const timer = setTimeout(() => {
        fitView({ padding: 0.05, duration: 200 })
      }, 50)
      return () => clearTimeout(timer)
    }
  }, [containerSize, nodes, fitView])

  return (
    <div
      ref={containerRef}
      className="w-full"
      style={{ height: '50vh' }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.05 }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{ type: 'straight' }}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={16}
          size={0.5}
          color="rgba(69, 65, 56, 0.08)"
        />
      </ReactFlow>
    </div>
  )
}

export default function WorkflowDiagram(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { agents, setAgents } = useAgentStore()
  const [initialLoading, setInitialLoading] = useState(true)
  const [containerSize, setContainerSize] = useState({ width: 0, height: 0 })

  // Handle container resize
  const handleContainerResize = useCallback((width: number, height: number) => {
    setContainerSize({ width, height })
  }, [])

  // Calculate layout config based on container size
  const layoutConfig = useMemo(() => {
    if (containerSize.width > 0 && containerSize.height > 0) {
      return calculateLayoutConfig(containerSize.width, containerSize.height)
    }
    return DEFAULT_LAYOUT_CONFIG
  }, [containerSize])

  // Initial data fetch
  useEffect(() => {
    if (!currentProject) {
      setAgents([])
      setInitialLoading(false)
      return
    }

    const fetchAgents = async () => {
      setInitialLoading(true)
      try {
        const agentsData = await agentApi.listByProject(currentProject.id)
        const agentsConverted: Agent[] = agentsData.map(a => ({
          id: a.id,
          projectId: a.projectId,
          type: a.type,
          phase: a.phase,
          status: a.status as AgentStatus,
          progress: a.progress,
          currentTask: a.currentTask,
          tokensUsed: a.tokensUsed,
          startedAt: a.startedAt,
          completedAt: a.completedAt,
          error: a.error,
          parentAgentId: null,
          metadata: a.metadata,
          createdAt: a.startedAt || new Date().toISOString()
        }))
        setAgents(agentsConverted)
      } catch (error) {
        console.error('Failed to fetch agents:', error)
      } finally {
        setInitialLoading(false)
      }
    }

    fetchAgents()
  }, [currentProject?.id, setAgents])

  // Get agent by type (handles _leader suffix)
  const getAgentByType = useCallback((type: AgentType): Agent | undefined => {
    const projectAgents = agents.filter(a => a.projectId === currentProject?.id)
    let agent = projectAgents.find(a => a.type === type)
    if (!agent) {
      agent = projectAgents.find(a => a.type === `${type}_leader`)
    }
    if (!agent) {
      agent = projectAgents.find(a => a.type === type.replace('_leader', ''))
    }
    return agent
  }, [agents, currentProject?.id])

  // Build status map for dynamic layout
  const statusMap = useMemo(() => {
    const map: Record<string, AgentStatus | undefined> = {}
    AGENT_NODES.forEach(nodeDef => {
      const agent = getAgentByType(nodeDef.type)
      map[nodeDef.id] = agent?.status
    })
    return map
  }, [getAgentByType])

  // Calculate dynamic layout based on status and layout config
  const layout = useMemo(() => {
    return getColumnLayout(statusMap, layoutConfig)
  }, [statusMap, layoutConfig])

  // Calculate phase group bounds
  const phaseGroups = useMemo(() => {
    const groups = [
      { id: 'phase-0', label: 'P0: 企画', phase: 0 },
      { id: 'phase-1', label: 'P1: 分割1', phase: 1 },
      { id: 'phase-2', label: 'P2: 設計', phase: 2 },
      { id: 'phase-3', label: 'P3: 分割2', phase: 3 },
      { id: 'phase-4', label: 'P4: アセット', phase: 4 },
      { id: 'phase-5', label: 'P5: 分割3', phase: 5 },
      { id: 'phase-6', label: 'P6: 実装', phase: 6 },
      { id: 'phase-7', label: 'P7: 分割4', phase: 7 },
      { id: 'phase-8', label: 'P8: テスト', phase: 8 },
    ]
    return groups.map(g => ({
      ...g,
      ...calculatePhaseBounds(g.phase, layout.positions, layout.widths, layout.heights, layoutConfig),
    }))
  }, [layout, layoutConfig])

  // Build nodes
  const nodes: Node[] = useMemo(() => {
    // Phase group nodes (background)
    const groupNodes: Node[] = phaseGroups.map(group => ({
      id: group.id,
      type: 'phaseGroup',
      position: { x: group.x, y: group.y },
      data: { label: group.label, width: group.width, height: group.height },
      draggable: false,
      selectable: false,
      zIndex: -1,
    }))

    // Agent nodes
    const agentNodes: Node[] = AGENT_NODES.map(nodeDef => {
      const agent = getAgentByType(nodeDef.type)
      const pos = layout.positions[nodeDef.id]
      return {
        id: nodeDef.id,
        type: 'agent',
        position: pos,
        data: {
          label: nodeDef.label,
          status: agent?.status,
          progress: agent?.progress ?? 0,
          hasLW: nodeDef.hasLW,
          nodeWidth: layoutConfig.nodeWidth,
          nodeHeight: layoutConfig.nodeHeight,
          fontSize: layoutConfig.fontSize,
        },
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        draggable: false,
      }
    })

    return [...groupNodes, ...agentNodes]
  }, [getAgentByType, layout, phaseGroups, layoutConfig])

  // Build edges
  const edges: Edge[] = useMemo(() => {
    // Helper to get node's phase
    const getNodePhase = (nodeId: string): number => {
      const node = AGENT_NODES.find(n => n.id === nodeId)
      return node?.phase ?? 1
    }

    return EDGE_DEFS.map((edgeDef, index) => {
      const sourceAgent = getAgentByType(edgeDef.source as AgentType)
      const isCompleted = sourceAgent?.status === 'completed'
      const isRunning = sourceAgent?.status === 'running'

      const sourcePhase = getNodePhase(edgeDef.source)
      const targetPhase = getNodePhase(edgeDef.target)
      const isCrossPhase = sourcePhase !== targetPhase

      return {
        id: `e-${index}`,
        source: edgeDef.source,
        target: edgeDef.target,
        sourceHandle: isCrossPhase ? 'right' : 'bottom',
        targetHandle: isCrossPhase ? 'left' : 'top',
        type: 'straight',
        animated: isRunning,
        style: {
          stroke: isCompleted ? 'rgba(69, 65, 56, 0.5)' : isRunning ? '#C4956C' : 'rgba(69, 65, 56, 0.15)',
          strokeWidth: isRunning ? 2 : 1,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          width: 10,
          height: 10,
          color: isCompleted ? 'rgba(69, 65, 56, 0.5)' : isRunning ? '#C4956C' : 'rgba(69, 65, 56, 0.15)',
        },
      }
    })
  }, [getAgentByType])

  // Calculate stats
  const projectAgents = agents.filter(a => a.projectId === currentProject?.id)
  const completedCount = projectAgents.filter(a => a.status === 'completed').length
  const runningCount = projectAgents.filter(a => a.status === 'running').length
  const waitingApprovalCount = projectAgents.filter(a => a.status === 'waiting_approval').length
  const totalCount = AGENT_NODES.length
  const overallProgress = totalCount > 0
    ? Math.round((completedCount / totalCount) * 100 +
        (projectAgents.filter(a => a.status === 'running').reduce((sum, a) => sum + (a.progress || 0), 0) / totalCount))
    : 0

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>ワークフロー全体図</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>ワークフロー全体図</DiamondMarker>
        <div className="ml-auto flex items-center gap-4 text-nier-caption text-nier-text-light">
          <span>全体: {overallProgress}%</span>
          <span>完了: {completedCount}/{totalCount}</span>
          {runningCount > 0 && (
            <span className="text-nier-accent-orange animate-pulse">実行中: {runningCount}</span>
          )}
          {waitingApprovalCount > 0 && (
            <span className="text-[#8B7914] animate-pulse">承認待ち: {waitingApprovalCount}</span>
          )}
        </div>
      </CardHeader>
      <CardContent className="p-0">
        {initialLoading ? (
          <div className="text-nier-text-light text-center py-8 text-nier-small">
            読み込み中...
          </div>
        ) : (
          <ReactFlowProvider>
            <FlowCanvas nodes={nodes} edges={edges} onContainerResize={handleContainerResize} />
          </ReactFlowProvider>
        )}

        {/* Legend - compact */}
        <div className="flex items-center justify-center gap-4 py-2 border-t border-nier-border-light text-nier-caption text-nier-text-light">
          <div className="flex items-center gap-1">
            <div className="w-3 h-2.5 bg-[#A8A090] border border-[#454138] rounded-sm" />
            <span>完了</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-3 h-2.5 bg-nier-accent-orange border border-[#8B6914] rounded-sm" />
            <span>実行中</span>
          </div>
          {waitingApprovalCount > 0 && (
            <div className="flex items-center gap-1">
              <div className="w-3 h-2.5 bg-[#D4C896] border border-[#8B7914] rounded-sm" />
              <span>承認待ち</span>
            </div>
          )}
          <div className="flex items-center gap-1">
            <div className="w-3 h-2.5 bg-nier-bg-main border border-nier-border-light rounded-sm" />
            <span>待機</span>
          </div>
          <div className="border-l border-nier-border-light h-3 mx-1" />
          <div className="flex items-center gap-1">
            <span className="text-[9px] px-1 py-0.5 border border-nier-border-light rounded text-nier-text-light">L/W</span>
            <span>Leader/Worker継続ループ</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}
