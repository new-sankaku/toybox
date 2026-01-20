import { useEffect, useRef } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppLayout from './components/layout/AppLayout'
import DashboardView from './components/dashboard/DashboardView'
import { ProjectView, CheckpointsView, AgentsView, LogsView, DataView, AIView, CostView, ConfigView } from './views'
import { useNavigationStore } from './stores/navigationStore'
import { useProjectStore } from './stores/projectStore'
import { useAgentDefinitionStore } from './stores/agentDefinitionStore'
import { websocketService } from './services/websocketService'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1
    }
  }
})

// Re-export TabId for backward compatibility
export type { TabId } from './stores/navigationStore'

function App(): JSX.Element {
  const { activeTab, setActiveTab } = useNavigationStore()
  const { currentProject } = useProjectStore()
  const { fetchDefinitions } = useAgentDefinitionStore()
  const previousProjectIdRef = useRef<string | null>(null)

  // Initialize WebSocket connection and fetch agent definitions
  useEffect(() => {
    const backendUrl = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'
    websocketService.connect(backendUrl)

    // Fetch agent definitions at startup
    fetchDefinitions()

    return () => {
      websocketService.disconnect()
    }
  }, [fetchDefinitions])

  // Subscribe to project updates when project changes
  useEffect(() => {
    const projectId = currentProject?.id ?? null

    // Unsubscribe from previous project
    if (previousProjectIdRef.current && previousProjectIdRef.current !== projectId) {
      websocketService.unsubscribeFromProject(previousProjectIdRef.current)
    }

    // Subscribe to new project (service handles connection timing internally)
    if (projectId) {
      console.log('[App] Requesting WebSocket subscription for project:', projectId)
      websocketService.subscribeToProject(projectId)
    }

    previousProjectIdRef.current = projectId
  }, [currentProject?.id])

  const renderContent = () => {
    switch (activeTab) {
      case 'project':
        return <ProjectView />
      case 'checkpoints':
        return <CheckpointsView />
      case 'system':
        return <DashboardView />
      case 'agents':
        return <AgentsView />
      case 'logs':
        return <LogsView />
      case 'data':
        return <DataView />
      case 'ai':
        return <AIView />
      case 'cost':
        return <CostView />
      case 'config':
        return <ConfigView />
      default:
        return <DashboardView />
    }
  }

  return (
    <QueryClientProvider client={queryClient}>
      <AppLayout activeTab={activeTab} onTabChange={setActiveTab}>
        {renderContent()}
      </AppLayout>
    </QueryClientProvider>
  )
}

export default App
