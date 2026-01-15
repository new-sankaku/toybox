import { io, Socket } from 'socket.io-client'
import { useConnectionStore } from '@/stores/connectionStore'
import { useAgentStore } from '@/stores/agentStore'
import { useCheckpointStore } from '@/stores/checkpointStore'
import type { Agent, AgentLogEntry } from '@/types/agent'
import type { Checkpoint } from '@/types/checkpoint'

// WebSocket Events from server
interface ServerToClientEvents {
  // Connection events
  connect: () => void
  disconnect: () => void
  error: (error: Error) => void

  // Agent events
  'agent:started': (data: { agent: Agent }) => void
  'agent:progress': (data: { agentId: string; progress: number; message: string }) => void
  'agent:log': (data: { agentId: string; entry: AgentLogEntry }) => void
  'agent:completed': (data: { agent: Agent }) => void
  'agent:failed': (data: { agentId: string; error: string }) => void

  // Checkpoint events
  'checkpoint:created': (data: { checkpoint: Checkpoint }) => void
  'checkpoint:resolved': (data: { checkpoint: Checkpoint }) => void

  // Project events
  'project:updated': (data: { projectId: string; updates: Record<string, unknown> }) => void
  'phase:changed': (data: { projectId: string; phase: string }) => void
}

// WebSocket Events to server
interface ClientToServerEvents {
  'subscribe:project': (projectId: string) => void
  'unsubscribe:project': (projectId: string) => void
  'checkpoint:resolve': (data: { checkpointId: string; resolution: string; feedback?: string }) => void
}

type TypedSocket = Socket<ServerToClientEvents, ClientToServerEvents>

class WebSocketService {
  private socket: TypedSocket | null = null
  private maxReconnectAttempts = 5
  private reconnectDelay = 1000 // Start with 1 second

  connect(backendUrl: string): void {
    if (this.socket?.connected) {
      console.log('WebSocket already connected')
      return
    }

    const connectionStore = useConnectionStore.getState()
    connectionStore.setStatus('connecting')

    this.socket = io(backendUrl, {
      transports: ['websocket', 'polling'],
      reconnection: true,
      reconnectionAttempts: this.maxReconnectAttempts,
      reconnectionDelay: this.reconnectDelay,
      reconnectionDelayMax: 5000,
      timeout: 10000
    })

    this.setupEventHandlers()
  }

  private setupEventHandlers(): void {
    if (!this.socket) return

    const connectionStore = useConnectionStore.getState()
    const agentStore = useAgentStore.getState()
    const checkpointStore = useCheckpointStore.getState()

    // Connection events
    this.socket.on('connect', () => {
      console.log('WebSocket connected')
      connectionStore.setStatus('connected')
      connectionStore.setError(null)
      connectionStore.resetReconnect()
    })

    this.socket.on('disconnect', () => {
      console.log('WebSocket disconnected')
      connectionStore.setStatus('disconnected')
    })

    this.socket.on('error' as keyof ServerToClientEvents, ((error: Error) => {
      console.error('WebSocket error:', error)
      connectionStore.setError(error.message)
    }) as () => void)

    // Agent events
    this.socket.on('agent:started', ({ agent }) => {
      console.log('Agent started:', agent.id)
      agentStore.addAgent(agent)
      agentStore.updateAgentStatus(agent.id, 'running')
    })

    this.socket.on('agent:progress', ({ agentId, progress, message }) => {
      agentStore.updateAgent(agentId, { progress })
      agentStore.addLogEntry(agentId, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'info',
        message,
        progress
      })
    })

    this.socket.on('agent:log', ({ agentId, entry }) => {
      agentStore.addLogEntry(agentId, entry)
    })

    this.socket.on('agent:completed', ({ agent }) => {
      console.log('Agent completed:', agent.id)
      agentStore.updateAgent(agent.id, agent)
      agentStore.updateAgentStatus(agent.id, 'completed')
    })

    this.socket.on('agent:failed', ({ agentId, error }) => {
      console.error('Agent failed:', agentId, error)
      agentStore.updateAgentStatus(agentId, 'failed')
      agentStore.addLogEntry(agentId, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'error',
        message: error
      })
    })

    // Checkpoint events
    this.socket.on('checkpoint:created', ({ checkpoint }) => {
      console.log('Checkpoint created:', checkpoint.id)
      checkpointStore.addCheckpoint(checkpoint)
    })

    this.socket.on('checkpoint:resolved', ({ checkpoint }) => {
      console.log('Checkpoint resolved:', checkpoint.id)
      checkpointStore.updateCheckpoint(checkpoint.id, checkpoint)
    })
  }

  subscribeToProject(projectId: string): void {
    if (!this.socket?.connected) {
      console.warn('Cannot subscribe: WebSocket not connected')
      return
    }
    this.socket.emit('subscribe:project', projectId)
  }

  unsubscribeFromProject(projectId: string): void {
    if (!this.socket?.connected) return
    this.socket.emit('unsubscribe:project', projectId)
  }

  resolveCheckpoint(checkpointId: string, resolution: string, feedback?: string): void {
    if (!this.socket?.connected) {
      console.warn('Cannot resolve checkpoint: WebSocket not connected')
      return
    }
    this.socket.emit('checkpoint:resolve', { checkpointId, resolution, feedback })
  }

  disconnect(): void {
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
    }
    useConnectionStore.getState().setStatus('disconnected')
  }

  isConnected(): boolean {
    return this.socket?.connected ?? false
  }
}

// Singleton instance
export const websocketService = new WebSocketService()
