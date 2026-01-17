import { useState, useEffect } from 'react'
import { AgentListView, AgentDetailView } from '@/components/agents'
import { Card, CardContent } from '@/components/ui/Card'
import { useProjectStore } from '@/stores/projectStore'
import { useNavigationStore } from '@/stores/navigationStore'
import { agentApi, type ApiAgent, type ApiAgentLog } from '@/services/apiService'
import type { Agent, AgentLogEntry, AgentType } from '@/types/agent'
import { FolderOpen } from 'lucide-react'

// Convert API agent to frontend Agent type
function convertApiAgent(apiAgent: ApiAgent): Agent {
  return {
    id: apiAgent.id,
    projectId: apiAgent.projectId,
    type: apiAgent.type as AgentType,
    status: apiAgent.status,
    progress: apiAgent.progress,
    currentTask: apiAgent.currentTask,
    tokensUsed: apiAgent.tokensUsed,
    startedAt: apiAgent.startedAt,
    completedAt: apiAgent.completedAt,
    error: apiAgent.error,
    parentAgentId: apiAgent.parentAgentId,
    metadata: apiAgent.metadata,
    createdAt: apiAgent.createdAt,
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
  const [agents, setAgents] = useState<Agent[]>([])
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [selectedAgentLogs, setSelectedAgentLogs] = useState<AgentLogEntry[]>([])
  const [loading, setLoading] = useState(false)

  // Reset selection when tab is clicked (even if same tab)
  useEffect(() => {
    setSelectedAgent(null)
  }, [tabResetCounter])

  // Fetch agents from API
  useEffect(() => {
    if (!currentProject) {
      setAgents([])
      return
    }

    const fetchAgents = async () => {
      setLoading(true)
      try {
        const data = await agentApi.listByProject(currentProject.id)
        setAgents(data.map(convertApiAgent))
      } catch (error) {
        console.error('Failed to fetch agents:', error)
        setAgents([])
      } finally {
        setLoading(false)
      }
    }

    fetchAgents()
    const interval = setInterval(fetchAgents, 5000)
    return () => clearInterval(interval)
  }, [currentProject?.id])

  // Fetch selected agent's logs
  useEffect(() => {
    if (!selectedAgent) {
      setSelectedAgentLogs([])
      return
    }

    const fetchLogs = async () => {
      try {
        const data = await agentApi.getLogs(selectedAgent.id)
        // Sort logs DESC (newest first)
        const logs = data.map(convertApiLog).sort(
          (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
        )
        setSelectedAgentLogs(logs)
      } catch (error) {
        console.error('Failed to fetch agent logs:', error)
        setSelectedAgentLogs([])
      }
    }

    fetchLogs()
    const interval = setInterval(fetchLogs, 3000)
    return () => clearInterval(interval)
  }, [selectedAgent?.id])

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
    return (
      <AgentDetailView
        agent={selectedAgent}
        logs={selectedAgentLogs}
        onBack={handleBack}
        onRetry={selectedAgent.status === 'failed' ? handleRetry : undefined}
      />
    )
  }

  // Show agent list
  return (
    <AgentListView
      agents={agents}
      onSelectAgent={handleSelectAgent}
      selectedAgentId={undefined}
      loading={loading}
    />
  )
}
