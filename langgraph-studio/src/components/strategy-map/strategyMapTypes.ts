import type { AgentType,AgentStatus } from '../../types/agent'
import type { AIServiceId } from './strategyMapConfig'

export interface Vec2 {
  x: number
  y: number
}

export type AgentTier='orchestrator'|'director'|'leader'|'worker'

export type SummonEffectType='magicCircle'|'warpGate'|'lightning'|'splitMerge'

export interface HierarchyNode {
  id: string
  agentType: AgentType
  tier: AgentTier
  parentId: string|null
  children: HierarchyNode[]
  depth: number
  x: number
  y: number
  frameId: string|null
}

export interface FrameBounds {
  x: number
  y: number
  width: number
  height: number
}

export interface AgentFrameData {
  id: string
  ownerId: string
  bounds: FrameBounds
  childIds: string[]
  overflowCount: number
}

export interface RoadSegment {
  id: string
  start: Vec2
  end: Vec2
  isIntersection: boolean
}

export interface RoadNetwork {
  segments: RoadSegment[]
  intersections: Vec2[]
}

export interface PhysicsBody extends Vec2 {
  vx: number
  vy: number
}

export interface MapAgent {
  readonly id: string
  readonly type: AgentType
  readonly status: AgentStatus
  readonly parentId: string|null
  readonly currentTask: string|null
  readonly aiTarget: AIServiceId|null
  readonly bubble: string|null
  readonly bubbleType: BubbleType|null
  readonly spawnProgress: number
}

export type BubbleType='info'|'question'|'success'|'warning'

export interface AIService {
  readonly id: AIServiceId
  readonly name: string
  readonly color: string
  x: number
  y: number
}

export interface UserNode extends Vec2 {
  readonly queue: readonly string[]
}

export type ConnectionType=
  |'instruction'
  |'confirm'
  |'delivery'
  |'ai-request'
  |'user-contact'

export interface Connection {
  readonly id: string
  readonly fromId: string
  readonly toId: string
  readonly type: ConnectionType
  readonly active: boolean
}

export interface Particle extends PhysicsBody {
  life: number
  readonly maxLife: number
  readonly color: string
  readonly size: number
}

export interface DataPacket {
  readonly id: string
  readonly fromX: number
  readonly fromY: number
  readonly toX: number
  readonly toY: number
  readonly color: string
  progress: number
}

export interface CanvasTransform {
  zoom: number
  panX: number
  panY: number
}

export interface AgentPositionState extends PhysicsBody {
  targetX: number
  targetY: number
}
