import{create}from'zustand'

export type TabId='project'|'checkpoints'|'intervention'|'system'|'agents'|'logs'|'data'|'cost'|'global-config'

interface NavigationState{
 activeTab:TabId
 tabResetCounter:number
 pendingCheckpointId:string|null
 pendingInterventionAgentId:string|null
 setActiveTab:(tab:TabId)=>void
 navigateToCheckpoint:(checkpointId:string)=>void
 clearPendingCheckpoint:()=>void
 navigateToIntervention:(agentId:string)=>void
 clearPendingIntervention:()=>void
}

export const useNavigationStore=create<NavigationState>((set)=>({
 activeTab:'project',
 tabResetCounter:0,
 pendingCheckpointId:null,
 pendingInterventionAgentId:null,
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
 navigateToIntervention:(agentId)=>set((state)=>({
  activeTab:'intervention',
  tabResetCounter:state.tabResetCounter+1,
  pendingInterventionAgentId:agentId
 })),
 clearPendingIntervention:()=>set({pendingInterventionAgentId:null}),
}))
