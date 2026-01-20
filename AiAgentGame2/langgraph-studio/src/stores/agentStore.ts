import { create } from 'zustand'
import type { Agent, AgentStatus, AgentLogEntry } from '@/types/agent'

interface AgentState {
  // State
  agents: Agent[]
  selectedAgentId: string | null
  agentLogs: Record<string, AgentLogEntry[]>
  isLoading: boolean
  error: string | null

  // Actions
  setAgents: (agents: Agent[]) => void
  addAgent: (agent: Agent) => void
  updateAgent: (id: string, updates: Partial<Agent>) => void
  updateAgentStatus: (id: string, status: AgentStatus) => void
  selectAgent: (id: string | null) => void
  addLogEntry: (agentId: string, entry: AgentLogEntry) => void
  clearLogs: (agentId: string) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void

  // Selectors
  getSelectedAgent: () => Agent | undefined
  getAgentsByProject: (projectId: string) => Agent[]
  getActiveAgents: () => Agent[]
  getAgentLogs: (agentId: string) => AgentLogEntry[]
}

export const useAgentStore = create<AgentState>((set, get) => ({
  // Initial state
  agents: [],
  selectedAgentId: null,
  agentLogs: {},
  isLoading: false,
  error: null,

  // Actions
  setAgents: (agents) => set({ agents }),

  addAgent: (agent) =>
    set((state) => {
      // 重複チェック: 同じIDのエージェントが既に存在する場合は追加しない
      if (state.agents.some((a) => a.id === agent.id)) {
        return state
      }
      return { agents: [...state.agents, agent] }
    }),

  updateAgent: (id, updates) =>
    set((state) => ({
      agents: state.agents.map((agent) =>
        agent.id === id ? { ...agent, ...updates } : agent
      )
    })),

  updateAgentStatus: (id, status) =>
    set((state) => ({
      agents: state.agents.map((agent) =>
        agent.id === id
          ? {
              ...agent,
              status,
              startedAt: status === 'running' && !agent.startedAt
                ? new Date().toISOString()
                : agent.startedAt,
              completedAt: status === 'completed' || status === 'failed'
                ? new Date().toISOString()
                : agent.completedAt
            }
          : agent
      )
    })),

  selectAgent: (id) => set({ selectedAgentId: id }),

  addLogEntry: (agentId, entry) =>
    set((state) => ({
      agentLogs: {
        ...state.agentLogs,
        [agentId]: [...(state.agentLogs[agentId] || []), entry]
      }
    })),

  clearLogs: (agentId) =>
    set((state) => ({
      agentLogs: {
        ...state.agentLogs,
        [agentId]: []
      }
    })),

  setLoading: (loading) => set({ isLoading: loading }),

  setError: (error) => set({ error }),

  // Selectors
  getSelectedAgent: () => {
    const state = get()
    return state.agents.find((agent) => agent.id === state.selectedAgentId)
  },

  getAgentsByProject: (projectId) => {
    return get().agents.filter((agent) => agent.projectId === projectId)
  },

  getActiveAgents: () => {
    return get().agents.filter(
      (agent) => agent.status === 'running' || agent.status === 'pending'
    )
  },

  getAgentLogs: (agentId) => {
    return get().agentLogs[agentId] || []
  }
}))

// Helper hooks
export const useActiveAgentsCount = () => {
  return useAgentStore((state) =>
    state.agents.filter((a) => a.status === 'running' || a.status === 'pending').length
  )
}

export const useAgentsByProject = (projectId: string) => {
  return useAgentStore((state) =>
    state.agents.filter((a) => a.projectId === projectId)
  )
}
