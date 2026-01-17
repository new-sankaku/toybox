import { useEffect } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppLayout from './components/layout/AppLayout'
import DashboardView from './components/dashboard/DashboardView'
import { ProjectView, CheckpointsView, AgentsView, LogsView, DataView, AIView, CostView, ConfigView } from './views'
import { useNavigationStore } from './stores/navigationStore'
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

  // Initialize WebSocket connection
  useEffect(() => {
    const backendUrl = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'
    websocketService.connect(backendUrl)

    return () => {
      websocketService.disconnect()
    }
  }, [])

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
