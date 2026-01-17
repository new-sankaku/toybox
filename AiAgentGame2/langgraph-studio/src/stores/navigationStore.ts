import { create } from 'zustand'

export type TabId = 'project' | 'checkpoints' | 'system' | 'agents' | 'logs' | 'data' | 'ai' | 'cost' | 'config'

interface NavigationState {
  activeTab: TabId
  // Counter that increments when a tab is clicked (even if same tab)
  // Used to reset view state when user clicks on the current tab
  tabResetCounter: number
  // For navigating to a specific checkpoint from dashboard
  pendingCheckpointId: string | null
  setActiveTab: (tab: TabId) => void
  navigateToCheckpoint: (checkpointId: string) => void
  clearPendingCheckpoint: () => void
}

export const useNavigationStore = create<NavigationState>((set) => ({
  activeTab: 'project',
  tabResetCounter: 0,
  pendingCheckpointId: null,
  setActiveTab: (tab) => set((state) => ({
    activeTab: tab,
    // Always increment counter to trigger reset, even if same tab
    tabResetCounter: state.tabResetCounter + 1
  })),
  navigateToCheckpoint: (checkpointId) => set((state) => ({
    activeTab: 'checkpoints',
    tabResetCounter: state.tabResetCounter + 1,
    pendingCheckpointId: checkpointId
  })),
  clearPendingCheckpoint: () => set({ pendingCheckpointId: null }),
}))
