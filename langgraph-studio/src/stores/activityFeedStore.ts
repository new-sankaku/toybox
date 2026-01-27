import{create}from'zustand'

export type ActivityType='agent_started'|'agent_completed'|'agent_failed'|'agent_paused'|'agent_resumed'|'checkpoint_created'|'checkpoint_resolved'|'phase_changed'|'agent_waiting_response'|'agent_waiting_provider'|'agent_progress'

export interface ActivityEvent{
 id:string
 type:ActivityType
 agentName:string
 message:string
 timestamp:string
 agentId?:string
}

const MAX_EVENTS=100

interface ActivityFeedState{
 events:ActivityEvent[]
 addEvent:(type:ActivityType,agentName:string,message:string,agentId?:string)=>void
 clear:()=>void
}

export const useActivityFeedStore=create<ActivityFeedState>((set)=>({
 events:[],
 addEvent:(type,agentName,message,agentId)=>{
  const event:ActivityEvent={
   id:`act-${Date.now()}-${Math.random().toString(36).slice(2,7)}`,
   type,
   agentName,
   message,
   timestamp:new Date().toISOString(),
   agentId
  }
  set((state)=>({
   events:[event,...state.events].slice(0,MAX_EVENTS)
  }))
 },
 clear:()=>set({events:[]})
}))
