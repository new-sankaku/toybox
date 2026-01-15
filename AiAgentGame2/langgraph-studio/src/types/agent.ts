export type AgentStatus = 'pending' | 'running' | 'completed' | 'failed' | 'blocked'

export type AgentType =
  // Phase 1 agents
  | 'concept'
  | 'design'
  | 'scenario'
  | 'character'
  | 'world'
  | 'task_split'
  // Phase 2 agents
  | 'code_leader'
  | 'asset_leader'
  | 'code_worker'
  | 'asset_worker'
  // Phase 3 agents
  | 'integrator'
  | 'tester'
  | 'reviewer'

export interface Agent {
  id: string
  projectId: string
  type: AgentType
  status: AgentStatus
  progress: number
  currentTask: string | null
  tokensUsed: number
  startedAt: string | null
  completedAt: string | null
  error: string | null
  parentAgentId: string | null
  metadata: Record<string, unknown>
  createdAt: string
}

export interface AgentMetrics {
  agentId: string
  agentType: AgentType
  status: AgentStatus
  progress: number
  currentTask: string | null
  tokensUsed: number
  tokensEstimated: number
  runtimeSeconds: number
  estimatedRemainingSeconds: number
  completedTasks: number
  totalTasks: number
  activeSubAgents: number
  subAgentMetrics: AgentMetrics[]
}

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

export interface LogEntry {
  id: string
  agentId: string
  level: LogLevel
  message: string
  metadata?: Record<string, unknown>
  timestamp: string
}

export interface AgentLogEntry {
  id: string
  timestamp: string
  level: LogLevel
  message: string
  progress?: number
  metadata?: Record<string, unknown>
}

export interface AgentOutput {
  id: string
  agentId: string
  outputType: OutputType
  content: Record<string, unknown> | null
  filePath: string | null
  tokensUsed: number
  generationTimeMs: number
  createdAt: string
}

export type OutputType =
  // Phase 1
  | 'concept_doc'
  | 'design_doc'
  | 'scenario_doc'
  | 'character_specs'
  | 'world_design'
  | 'task_breakdown'
  // Phase 2
  | 'code'
  | 'asset_image'
  | 'asset_audio'
  // Phase 3
  | 'build_result'
  | 'test_result'
  | 'review_result'
