import type { AgentType,AgentStatus } from '../../../../types/agent'
import type { BubbleType,ConnectionType } from '../../strategyMapTypes'

export interface PhaserMapAgent {
 readonly id: string
 readonly type: AgentType
 readonly status: AgentStatus
 readonly parentId: string|null
 readonly currentTask: string|null
 readonly bubble: string|null
 readonly bubbleType: BubbleType|null
 readonly spawnProgress: number
}

export interface PhaserUserNode {
 readonly x: number
 readonly y: number
 readonly queue: readonly string[]
}

export interface PhaserConnection {
 readonly id: string
 readonly fromId: string
 readonly toId: string
 readonly type: ConnectionType
 readonly active: boolean
}

export interface PhysicsBody {
 x: number
 y: number
 vx: number
 vy: number
 targetX: number
 targetY: number
}

export interface ParticleConfig {
 x: number
 y: number
 color: number
 count: number
 spread: number
 life: number
 gravity: number
}

export interface PacketData {
 id: string
 fromX: number
 fromY: number
 toX: number
 toY: number
 color: number
 progress: number
}

export type EventType=
 |'agents-updated'
 |'user-updated'
 |'connections-updated'
 |'resize'

export interface EventPayload {
 'agents-updated': PhaserMapAgent[]
 'user-updated': PhaserUserNode
 'connections-updated': PhaserConnection[]
 'resize': { width: number;height: number }
}
