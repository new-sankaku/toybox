import type { AgentType, AgentStatus } from '../../types/agent'
import type { AIServiceId } from './strategyMapConfig'

export interface Vec2 {
  x: number
  y: number
}

export interface PhysicsBody extends Vec2 {
  vx: number
  vy: number
}

export interface MapAgent {
  readonly id: string
  readonly type: AgentType
  readonly status: AgentStatus
  readonly parentId: string | null
  readonly currentTask: string | null
  readonly aiTarget: AIServiceId | null
  readonly bubble: string | null
  readonly bubbleType: BubbleType | null
  readonly spawnProgress: number
}

export type BubbleType = 'info' | 'question' | 'success' | 'warning'

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

export type ConnectionType =
  | 'instruction'
  | 'confirm'
  | 'delivery'
  | 'ai-request'
  | 'user-contact'

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
