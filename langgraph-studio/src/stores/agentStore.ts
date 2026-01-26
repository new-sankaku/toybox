import{create}from'zustand'
import type{Agent,AgentStatus,AgentLogEntry}from'@/types/agent'

const MAX_LOG_ENTRIES_PER_AGENT=1000

interface AgentState{
 agents:Agent[]
 selectedAgentId:string|null
 agentLogs:Record<string,AgentLogEntry[]>
 exitedAgentIds:Set<string>
 isLoading:boolean
 error:string|null
 version:number
 setAgents:(agents:Agent[])=>void
 addAgent:(agent:Agent)=>void
 updateAgent:(id:string,updates:Partial<Agent>)=>void
 updateAgentStatus:(id:string,status:AgentStatus)=>void
 selectAgent:(id:string|null)=>void
 addLogEntry:(agentId:string,entry:AgentLogEntry)=>void
 clearLogs:(agentId:string)=>void
 setLoading:(loading:boolean)=>void
 setError:(error:string|null)=>void
 addExitedAgentId:(agentId:string)=>void
 clearExitedAgentIds:()=>void
 reset:()=>void
 getSelectedAgent:()=>Agent|undefined
 getAgentsByProject:(projectId:string)=>Agent[]
 getActiveAgents:()=>Agent[]
 getAgentLogs:(agentId:string)=>AgentLogEntry[]
}

export const useAgentStore=create<AgentState>((set,get)=>({
 agents:[],
 selectedAgentId:null,
 agentLogs:{},
 exitedAgentIds:new Set<string>(),
 isLoading:false,
 error:null,
 version:0,

 setAgents:(agents)=>set({agents}),

 addAgent:(agent)=>
  set((state)=>{
   if(state.agents.some((a)=>a.id===agent.id)){
    return state
   }
   return{agents:[...state.agents,agent]}
  }),

 updateAgent:(id,updates)=>
  set((state)=>({
   agents:state.agents.map((agent)=>
    agent.id===id?{...agent,...updates} : agent
)
  })),

 updateAgentStatus:(id,status)=>
  set((state)=>({
   agents:state.agents.map((agent)=>
    agent.id===id
     ?{
      ...agent,
      status,
      startedAt:status==='running'&&!agent.startedAt
       ?new Date().toISOString()
       : agent.startedAt,
      completedAt:status==='completed'||status==='failed'
       ?new Date().toISOString()
       : agent.completedAt
     }
     : agent
)
  })),

 selectAgent:(id)=>set({selectedAgentId:id}),

 addLogEntry:(agentId,entry)=>
  set((state)=>{
   const currentLogs=state.agentLogs[agentId]||[]
   const newLogs=[...currentLogs,entry]
   const trimmedLogs=newLogs.length>MAX_LOG_ENTRIES_PER_AGENT
    ?newLogs.slice(-MAX_LOG_ENTRIES_PER_AGENT)
    :newLogs
   return{
    agentLogs:{
     ...state.agentLogs,
     [agentId]:trimmedLogs
    }
   }
  }),

 clearLogs:(agentId)=>
  set((state)=>({
   agentLogs:{
    ...state.agentLogs,
    [agentId]:[]
   }
  })),

 setLoading:(loading)=>set({isLoading:loading}),

 setError:(error)=>set({error}),

 addExitedAgentId:(agentId)=>
  set((state)=>({
   exitedAgentIds:new Set([...state.exitedAgentIds,agentId])
  })),

 clearExitedAgentIds:()=>set({exitedAgentIds:new Set<string>()}),

 reset:()=>set((state)=>({
  agents:[],
  selectedAgentId:null,
  agentLogs:{},
  exitedAgentIds:new Set<string>(),
  isLoading:false,
  error:null,
  version:state.version+1
 })),

 getSelectedAgent:()=>{
  const state=get()
  return state.agents.find((agent)=>agent.id===state.selectedAgentId)
 },

 getAgentsByProject:(projectId)=>{
  return get().agents.filter((agent)=>agent.projectId===projectId)
 },

 getActiveAgents:()=>{
  return get().agents.filter(
   (agent)=>agent.status==='running'||agent.status==='pending'
)
 },

 getAgentLogs:(agentId)=>{
  return get().agentLogs[agentId]||[]
 }
}))

export const useActiveAgentsCount=()=>{
 return useAgentStore((state)=>
  state.agents.filter((a)=>a.status==='running'||a.status==='pending').length
)
}

export const useAgentsByProject=(projectId:string)=>{
 return useAgentStore((state)=>
  state.agents.filter((a)=>a.projectId===projectId)
)
}
