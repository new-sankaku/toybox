import { io, Socket } from 'socket.io-client'
import { useConnectionStore } from '@/stores/connectionStore'
import { useProjectStore } from '@/stores/projectStore'
import { useAgentStore } from '@/stores/agentStore'
import { useCheckpointStore } from '@/stores/checkpointStore'
import { useMetricsStore } from '@/stores/metricsStore'
import type { Agent, AgentLogEntry } from '@/types/agent'
import type { Checkpoint } from '@/types/checkpoint'
import type { Project, ProjectMetrics, PhaseNumber } from '@/types/project'

// WebSocket Events from server
interface ServerToClientEvents {
  // Connection events
  connect: () => void
  disconnect: () => void
  error: (error: Error) => void
  'connection:state_sync': (data: {
    status?: string
    sid?: string
    project?: Project
    agents?: Agent[]
    checkpoints?: Checkpoint[]
    metrics?: ProjectMetrics
  }) => void

  // Agent events
  'agent:started': (data: { agent: Agent; agentId: string; projectId: string }) => void
  'agent:progress': (data: { agentId: string; projectId: string; progress: number; currentTask: string; tokensUsed: number; message: string }) => void
  'agent:log': (data: { agentId: string; entry: AgentLogEntry }) => void
  'agent:completed': (data: { agent: Agent; agentId: string; projectId: string }) => void
  'agent:failed': (data: { agentId: string; error: string }) => void

  // Checkpoint events
  'checkpoint:created': (data: { checkpoint: Checkpoint; checkpointId: string; projectId: string; agentId: string }) => void
  'checkpoint:resolved': (data: { checkpoint: Checkpoint }) => void

  // Project events
  'project:updated': (data: { projectId: string; updates: Partial<Project> }) => void
  'phase:changed': (data: { projectId: string; phase: PhaseNumber; phaseName: string }) => void

  // Metrics events
  'metrics:update': (data: { projectId: string; metrics: ProjectMetrics }) => void
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
  private reconnectDelay = 1000
  private pendingProjectId: string | null = null  // Project to subscribe to when connected
  private currentProjectId: string | null = null  // Currently subscribed project

  connect(backendUrl: string): void {
    if (this.socket?.connected) {
      console.log('[WS] Already connected')
      return
    }

    const connectionStore = useConnectionStore.getState()
    connectionStore.setStatus('connecting')

    console.log('[WS] Connecting to:', backendUrl)

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

    // Connection events
    this.socket.on('connect', () => {
      console.log('[WS] Connected! Socket ID:', this.socket?.id)
      const connectionStore = useConnectionStore.getState()
      connectionStore.setStatus('connected')
      connectionStore.setError(null)
      connectionStore.resetReconnect()

      // Auto-subscribe to pending project on connect/reconnect
      if (this.pendingProjectId) {
        console.log('[WS] Auto-subscribing to pending project:', this.pendingProjectId)
        this.doSubscribe(this.pendingProjectId)
      }
    })

    this.socket.on('disconnect', (reason) => {
      console.log('[WS] Disconnected. Reason:', reason)
      useConnectionStore.getState().setStatus('disconnected')
      this.currentProjectId = null
    })

    this.socket.on('error' as keyof ServerToClientEvents, ((error: Error) => {
      console.error('[WS] Error:', error)
      useConnectionStore.getState().setError(error.message)
    }) as () => void)

    // State sync event - received when subscribing to a project
    this.socket.on('connection:state_sync', (data) => {
      console.log('[WS] State sync received:', {
        hasAgents: data.agents?.length || 0,
        hasCheckpoints: data.checkpoints?.length || 0,
        hasMetrics: !!data.metrics,
        status: data.status
      })

      if (data.agents && data.agents.length > 0) {
        console.log('[WS] Setting agents from state sync:', data.agents.length)
        useAgentStore.getState().setAgents(data.agents)
      }
      if (data.checkpoints && data.checkpoints.length > 0) {
        const checkpointStore = useCheckpointStore.getState()
        data.checkpoints.forEach(cp => checkpointStore.addCheckpoint(cp))
      }
      if (data.metrics) {
        useMetricsStore.getState().setProjectMetrics(data.metrics)
      }
    })

    // Agent events
    this.socket.on('agent:started', (data) => {
      console.log('[WS] Agent started:', data.agentId)
      const agentStore = useAgentStore.getState()
      if (data.agent) {
        agentStore.addAgent(data.agent)
        agentStore.updateAgentStatus(data.agent.id, 'running')
      }
    })

    this.socket.on('agent:progress', (data) => {
      console.log('[WS] Agent progress:', data.agentId, data.progress + '%')
      const agentStore = useAgentStore.getState()
      agentStore.updateAgent(data.agentId, {
        progress: data.progress,
        currentTask: data.currentTask,
        tokensUsed: data.tokensUsed
      })
    })

    this.socket.on('agent:log', ({ agentId, entry }) => {
      useAgentStore.getState().addLogEntry(agentId, entry)
    })

    this.socket.on('agent:completed', (data) => {
      console.log('[WS] Agent completed:', data.agentId)
      const agentStore = useAgentStore.getState()
      if (data.agent) {
        agentStore.updateAgent(data.agent.id, data.agent)
      }
      agentStore.updateAgentStatus(data.agentId, 'completed')
    })

    this.socket.on('agent:failed', ({ agentId, error }) => {
      console.error('[WS] Agent failed:', agentId, error)
      const agentStore = useAgentStore.getState()
      agentStore.updateAgentStatus(agentId, 'failed')
      agentStore.addLogEntry(agentId, {
        id: crypto.randomUUID(),
        timestamp: new Date().toISOString(),
        level: 'error',
        message: error
      })
    })

    // Checkpoint events
    this.socket.on('checkpoint:created', (data) => {
      console.log('[WS] Checkpoint created:', data.checkpointId)
      if (data.checkpoint) {
        useCheckpointStore.getState().addCheckpoint(data.checkpoint)
      }
    })

    this.socket.on('checkpoint:resolved', ({ checkpoint }) => {
      console.log('[WS] Checkpoint resolved:', checkpoint.id)
      useCheckpointStore.getState().updateCheckpoint(checkpoint.id, checkpoint)
    })

    // Project events
    this.socket.on('project:updated', ({ projectId, updates }) => {
      console.log('[WS] Project updated:', projectId)
      useProjectStore.getState().updateProject(projectId, updates)
    })

    this.socket.on('phase:changed', ({ projectId, phase, phaseName }) => {
      console.log('[WS] Phase changed:', projectId, phase, phaseName)
      useProjectStore.getState().updateProject(projectId, { currentPhase: phase })
    })

    // Metrics events
    this.socket.on('metrics:update', ({ projectId, metrics }) => {
      console.log('[WS] Metrics updated:', projectId, 'Progress:', metrics.progressPercent + '%')
      useMetricsStore.getState().setProjectMetrics(metrics)
    })
  }

  private doSubscribe(projectId: string): void {
    if (!this.socket) {
      console.warn('[WS] Cannot subscribe: No socket')
      return
    }
    console.log('[WS] Emitting subscribe:project for:', projectId)
    this.socket.emit('subscribe:project', projectId)
    this.currentProjectId = projectId
  }

  subscribeToProject(projectId: string): void {
    console.log('[WS] subscribeToProject called:', projectId, 'Connected:', this.socket?.connected)

    // Store as pending for reconnection
    this.pendingProjectId = projectId

    if (!this.socket?.connected) {
      console.warn('[WS] Not connected yet, will subscribe when connected')
      return
    }

    // Already subscribed to this project
    if (this.currentProjectId === projectId) {
      console.log('[WS] Already subscribed to this project')
      return
    }

    // Unsubscribe from previous project if any
    if (this.currentProjectId && this.currentProjectId !== projectId) {
      this.doUnsubscribe(this.currentProjectId)
    }

    this.doSubscribe(projectId)
  }

  private doUnsubscribe(projectId: string): void {
    if (!this.socket?.connected) return
    console.log('[WS] Emitting unsubscribe:project for:', projectId)
    this.socket.emit('unsubscribe:project', projectId)
  }

  unsubscribeFromProject(projectId: string): void {
    console.log('[WS] unsubscribeFromProject called:', projectId)

    if (this.pendingProjectId === projectId) {
      this.pendingProjectId = null
    }
    if (this.currentProjectId === projectId) {
      this.doUnsubscribe(projectId)
      this.currentProjectId = null
    }
  }

  resolveCheckpoint(checkpointId: string, resolution: string, feedback?: string): void {
    if (!this.socket?.connected) {
      console.warn('[WS] Cannot resolve checkpoint: Not connected')
      return
    }
    console.log('[WS] Resolving checkpoint:', checkpointId, resolution)
    this.socket.emit('checkpoint:resolve', { checkpointId, resolution, feedback })
  }

  disconnect(): void {
    console.log('[WS] Disconnecting...')
    if (this.socket) {
      this.socket.disconnect()
      this.socket = null
    }
    this.pendingProjectId = null
    this.currentProjectId = null
    useConnectionStore.getState().setStatus('disconnected')
  }

  isConnected(): boolean {
    return this.socket?.connected ?? false
  }

  // Debug helper
  getStatus(): { connected: boolean; currentProject: string | null; pendingProject: string | null } {
    return {
      connected: this.socket?.connected ?? false,
      currentProject: this.currentProjectId,
      pendingProject: this.pendingProjectId
    }
  }
}

// Singleton instance
export const websocketService = new WebSocketService()
