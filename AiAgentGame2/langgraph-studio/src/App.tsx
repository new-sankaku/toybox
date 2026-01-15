import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppLayout from './components/layout/AppLayout'
import DashboardView from './components/dashboard/DashboardView'
import { ProjectView, CheckpointsView, AgentsView, LogsView, DataView, CostView, ConfigView } from './views'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 1000 * 60 * 5, // 5 minutes
      retry: 1
    }
  }
})

// Tab definitions
export type TabId = 'project' | 'checkpoints' | 'system' | 'agents' | 'logs' | 'data' | 'cost' | 'config'

function App(): JSX.Element {
  const [activeTab, setActiveTab] = useState<TabId>('system')

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
