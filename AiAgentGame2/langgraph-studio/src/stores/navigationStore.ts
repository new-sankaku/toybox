import{create}from'zustand'

export type TabId='project'|'checkpoints'|'intervention'|'system'|'agents'|'logs'|'data'|'ai'|'cost'|'config'

interface NavigationState{
 activeTab:TabId
 tabResetCounter:number
 pendingCheckpointId:string|null
 setActiveTab:(tab:TabId)=>void
 navigateToCheckpoint:(checkpointId:string)=>void
 clearPendingCheckpoint:()=>void
}

export const useNavigationStore=create<NavigationState>((set)=>({
 activeTab:'project',
 tabResetCounter:0,
 pendingCheckpointId:null,
 setActiveTab:(tab)=>set((state)=>({
  activeTab:tab,
  tabResetCounter:state.tabResetCounter+1
 })),
 navigateToCheckpoint:(checkpointId)=>set((state)=>({
  activeTab:'checkpoints',
  tabResetCounter:state.tabResetCounter+1,
  pendingCheckpointId:checkpointId
 })),
 clearPendingCheckpoint:()=>set({pendingCheckpointId:null}),
}))
