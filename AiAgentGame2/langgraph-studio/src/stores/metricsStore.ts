import{create}from'zustand'
import type{ProjectMetrics}from'@/types/project'
import type{AgentMetrics}from'@/types/agent'

interface TokenUsage{
 agentId:string
 agentType:string
 tokensUsed:number
 timestamp:string
}

interface CostEstimate{
 inputTokens:number
 outputTokens:number
 inputCost:number
 outputCost:number
 totalCost:number
 currency:string
}

interface MetricsState{

 projectMetrics:ProjectMetrics | null
 agentMetrics:AgentMetrics[]
 tokenHistory:TokenUsage[]
 costEstimate:CostEstimate | null
 isLoading:boolean
 setProjectMetrics:(metrics:ProjectMetrics | null)=>void
 setAgentMetrics:(metrics:AgentMetrics[])=>void
 updateAgentMetrics:(agentId:string,updates:Partial<AgentMetrics>)=>void
 addTokenUsage:(usage:TokenUsage)=>void
 setCostEstimate:(estimate:CostEstimate | null)=>void
 setLoading:(loading:boolean)=>void
 reset:()=>void
 getTotalTokens:()=>number
 getTokensByAgent:(agentId:string)=>number
 getEstimatedCost:()=>number
}

const TOKEN_COSTS = {
 input:0.003 / 1000,  // $0.003 per 1K input tokens
 output:0.015 / 1000   // $0.015 per 1K output tokens
}

export const useMetricsStore = create<MetricsState>((set,get) => ({

 projectMetrics:null,
 agentMetrics:[],
 tokenHistory:[],
 costEstimate:null,
 isLoading:false,
 setProjectMetrics:(metrics) => set({projectMetrics:metrics}),

 setAgentMetrics:(metrics) => set({agentMetrics:metrics}),

 updateAgentMetrics:(agentId,updates) =>
  set((state) => ({
   agentMetrics:state.agentMetrics.map((m) =>
    m.agentId === agentId ? {...m,...updates} : m
   )
  })),

 addTokenUsage:(usage) =>
  set((state) => ({
   tokenHistory:[...state.tokenHistory,usage]
  })),

 setCostEstimate:(estimate) => set({costEstimate:estimate}),

 setLoading:(loading) => set({isLoading:loading}),

 reset:() =>
  set({
   projectMetrics:null,
   agentMetrics:[],
   tokenHistory:[],
   costEstimate:null,
   isLoading:false
  }),
 getTotalTokens:() => {
  const state = get()
  return state.tokenHistory.reduce((sum,t) => sum + t.tokensUsed,0)
 },

 getTokensByAgent:(agentId) => {
  const state = get()
  return state.tokenHistory
   .filter((t) => t.agentId === agentId)
   .reduce((sum,t) => sum + t.tokensUsed,0)
 },

 getEstimatedCost:() => {
  const state = get()
  const totalTokens = state.tokenHistory.reduce((sum,t) => sum + t.tokensUsed,0)
  const inputTokens = totalTokens * 0.3
  const outputTokens = totalTokens * 0.7
  return inputTokens * TOKEN_COSTS.input + outputTokens * TOKEN_COSTS.output
 }
}))
export function calculateCost(inputTokens:number,outputTokens:number):CostEstimate{
 const inputCost = inputTokens * TOKEN_COSTS.input
 const outputCost = outputTokens * TOKEN_COSTS.output
 return{
  inputTokens,
  outputTokens,
  inputCost,
  outputCost,
  totalCost:inputCost + outputCost,
  currency:'USD'
 }
}
