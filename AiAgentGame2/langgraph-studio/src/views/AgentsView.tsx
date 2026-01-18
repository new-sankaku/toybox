import { useState, useEffect } from 'react'
import { AgentListView, AgentDetailView } from '@/components/agents'
import { Card, CardContent } from '@/components/ui/Card'
import { useProjectStore } from '@/stores/projectStore'
import { useNavigationStore } from '@/stores/navigationStore'
import { useAgentStore } from '@/stores/agentStore'
import { agentApi, type ApiAgent, type ApiAgentLog } from '@/services/apiService'
import type { Agent, AgentLogEntry, AgentType, AgentStatus } from '@/types/agent'
import { FolderOpen } from 'lucide-react'

// Convert API agent to frontend Agent type
function convertApiAgent(apiAgent: ApiAgent): Agent {
  return {
    id: apiAgent.id,
    projectId: apiAgent.projectId,
    type: apiAgent.type as AgentType,
    status: apiAgent.status as AgentStatus,
    progress: apiAgent.progress,
    currentTask: apiAgent.currentTask,
    tokensUsed: apiAgent.tokensUsed,
    startedAt: apiAgent.startedAt,
    completedAt: apiAgent.completedAt,
    error: apiAgent.error,
    parentAgentId: apiAgent.parentAgentId,
    metadata: apiAgent.metadata,
    createdAt: apiAgent.createdAt,
    phase: apiAgent.phase
  }
}

// Convert API log to frontend AgentLogEntry type
function convertApiLog(apiLog: ApiAgentLog): AgentLogEntry {
  return {
    id: apiLog.id,
    timestamp: apiLog.timestamp,
    level: apiLog.level,
    message: apiLog.message,
    progress: apiLog.progress || undefined,
    metadata: apiLog.metadata,
  }
}

export default function AgentsView(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { tabResetCounter } = useNavigationStore()
  const { agents, setAgents, agentLogs, isLoading } = useAgentStore()
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const [initialLogsFetched, setInitialLogsFetched] = useState<Record<string, boolean>>({})

  // Reset selection when tab is clicked (even if same tab)
  useEffect(() => {
    setSelectedAgent(null)
  }, [tabResetCounter])

  // Initial fetch agents from API (no polling)
  useEffect(() => {
    if (!currentProject) {
      setAgents([])
      setInitialLoading(false)
      return
    }

    const fetchAgents = async () => {
      setInitialLoading(true)
      try {
        const data = await agentApi.listByProject(currentProject.id)
        setAgents(data.map(convertApiAgent))
      } catch (error) {
        console.error('Failed to fetch agents:', error)
      } finally {
        setInitialLoading(false)
      }
    }

    fetchAgents()
  }, [currentProject?.id, setAgents])

  // Fetch selected agent's logs (initial fetch only, then rely on WebSocket)
  useEffect(() => {
    if (!selectedAgent) return
    if (initialLogsFetched[selectedAgent.id]) return

    const fetchLogs = async () => {
      try {
        const data = await agentApi.getLogs(selectedAgent.id)
        const logs = data.map(convertApiLog)
        // Add to store (store will handle deduplication if needed)
        const { addLogEntry } = useAgentStore.getState()
        logs.forEach(log => addLogEntry(selectedAgent.id, log))
        setInitialLogsFetched(prev => ({ ...prev, [selectedAgent.id]: true }))
      } catch (error) {
        console.error('Failed to fetch agent logs:', error)
      }
    }

    fetchLogs()
  }, [selectedAgent?.id, initialLogsFetched])

  // Get logs from store for selected agent
  const selectedAgentLogs = selectedAgent
    ? (agentLogs[selectedAgent.id] || [])
        .slice()
        .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    : []

  // Filter agents for current project
  const projectAgents = currentProject
    ? agents.filter(a => a.projectId === currentProject.id)
    : []

  // Project not selected
  if (!currentProject) {
    return (
      <div className="p-4 animate-nier-fade-in">
        <div className="nier-page-header-row">
          <div className="nier-page-header-left">
            <h1 className="nier-page-title">AGENTS</h1>
            <span className="nier-page-subtitle">- エージェント管理</span>
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

  const handleSelectAgent = (agent: Agent) => {
    setSelectedAgent(agent)
  }

  const handleBack = () => {
    setSelectedAgent(null)
  }

  const handleRetry = () => {
    console.log('Retry agent:', selectedAgent?.id)
  }

  // Show detail view if agent is selected
  if (selectedAgent) {
    // Get latest agent data from store
    const currentAgentData = projectAgents.find(a => a.id === selectedAgent.id) || selectedAgent
    return (
      <AgentDetailView
        agent={currentAgentData}
        logs={selectedAgentLogs}
        onBack={handleBack}
        onRetry={currentAgentData.status === 'failed' ? handleRetry : undefined}
      />
    )
  }

  // Show agent list
  return (
    <AgentListView
      agents={projectAgents}
      onSelectAgent={handleSelectAgent}
      selectedAgentId={undefined}
      loading={initialLoading || isLoading}
    />
  )
}
