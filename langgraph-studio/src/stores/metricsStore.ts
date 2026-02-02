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

interface TokenCosts{
 input:number
 output:number
}

interface MetricsState{

 projectMetrics:ProjectMetrics|null
 agentMetrics:AgentMetrics[]
 tokenHistory:TokenUsage[]
 costEstimate:CostEstimate|null
 isLoading:boolean
 version:number
 tokenCosts:TokenCosts
 currency:string
 setProjectMetrics:(metrics:ProjectMetrics|null)=>void
 setAgentMetrics:(metrics:AgentMetrics[])=>void
 updateAgentMetrics:(agentId:string,updates:Partial<AgentMetrics>)=>void
 addTokenUsage:(usage:TokenUsage)=>void
 setCostEstimate:(estimate:CostEstimate|null)=>void
 setLoading:(loading:boolean)=>void
 setTokenCosts:(costs:TokenCosts,currency?:string)=>void
 reset:()=>void
 getTotalTokens:()=>number
 getTokensByAgent:(agentId:string)=>number
 getEstimatedCost:()=>number
}

const DEFAULT_TOKEN_COSTS:TokenCosts={
 input:0.003/1000,
 output:0.015/1000
}

export const useMetricsStore=create<MetricsState>((set,get)=>({

 projectMetrics:null,
 agentMetrics:[],
 tokenHistory:[],
 costEstimate:null,
 isLoading:false,
 version:0,
 tokenCosts:DEFAULT_TOKEN_COSTS,
 currency:'USD',
 setProjectMetrics:(metrics)=>set({projectMetrics:metrics}),

 setAgentMetrics:(metrics)=>set({agentMetrics:metrics}),

 updateAgentMetrics:(agentId,updates)=>
  set((state)=>({
   agentMetrics:state.agentMetrics.map((m)=>
    m.agentId===agentId?{...m,...updates} : m
)
  })),

 addTokenUsage:(usage)=>
  set((state)=>({
   tokenHistory:[...state.tokenHistory,usage]
  })),

 setCostEstimate:(estimate)=>set({costEstimate:estimate}),

 setLoading:(loading)=>set({isLoading:loading}),

 setTokenCosts:(costs,currency)=>set({
  tokenCosts:costs,
  ...(currency?{currency}:{})
 }),

 reset:()=>
  set((state)=>({
   projectMetrics:null,
   agentMetrics:[],
   tokenHistory:[],
   costEstimate:null,
   isLoading:false,
   version:state.version+1,
   tokenCosts:DEFAULT_TOKEN_COSTS,
   currency:'USD'
  })),
 getTotalTokens:()=>{
  const state=get()
  return state.tokenHistory.reduce((sum,t)=>sum+t.tokensUsed,0)
 },

 getTokensByAgent:(agentId)=>{
  const state=get()
  return state.tokenHistory
   .filter((t)=>t.agentId===agentId)
   .reduce((sum,t)=>sum+t.tokensUsed,0)
 },

 getEstimatedCost:()=>{
  const state=get()
  const totalTokens=state.tokenHistory.reduce((sum,t)=>sum+t.tokensUsed,0)
  const inputTokens=totalTokens*0.3
  const outputTokens=totalTokens*0.7
  return inputTokens*state.tokenCosts.input+outputTokens*state.tokenCosts.output
 }
}))

export function calculateCost(
 inputTokens:number,
 outputTokens:number,
 costs?:{input:number;output:number;currency?:string}
):CostEstimate{
 const tokenCosts=costs||useMetricsStore.getState().tokenCosts
 const currency=costs?.currency||useMetricsStore.getState().currency
 const inputCost=inputTokens*tokenCosts.input
 const outputCost=outputTokens*tokenCosts.output
 return{
  inputTokens,
  outputTokens,
  inputCost,
  outputCost,
  totalCost:inputCost+outputCost,
  currency
 }
}
