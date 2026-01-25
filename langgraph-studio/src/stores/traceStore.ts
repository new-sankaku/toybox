import{create}from'zustand'

export interface AgentTrace{
 id:string
 projectId:string
 agentId:string
 agentType:string
 status:'running'|'completed'|'error'
 inputContext:Record<string,unknown>|null
 promptSent:string|null
 llmResponse:string|null
 outputData:Record<string,unknown>|null
 tokensInput:number
 tokensOutput:number
 durationMs:number
 errorMessage:string|null
 modelUsed:string|null
 startedAt:string|null
 completedAt:string|null
}

interface TraceState{
 traces:AgentTrace[]
 selectedTraceId:string|null
 isLoading:boolean
 error:string|null
 expandedTraceIds:Set<string>
 setTraces:(traces:AgentTrace[])=>void
 addTrace:(trace:AgentTrace)=>void
 updateTrace:(traceId:string,data:Partial<AgentTrace>)=>void
 setSelectedTraceId:(id:string|null)=>void
 setLoading:(loading:boolean)=>void
 setError:(error:string|null)=>void
 toggleExpanded:(traceId:string)=>void
 expandAll:()=>void
 collapseAll:()=>void
 reset:()=>void
}

export const useTraceStore=create<TraceState>((set)=>({
 traces:[],
 selectedTraceId:null,
 isLoading:false,
 error:null,
 expandedTraceIds:new Set(),

 setTraces:(traces)=>set({traces}),

 addTrace:(trace)=>set((state)=>({
  traces:[trace,...state.traces]
 })),

 updateTrace:(traceId,data)=>set((state)=>({
  traces:state.traces.map((t)=>
   t.id===traceId?{...t,...data}:t
  )
 })),

 setSelectedTraceId:(id)=>set({selectedTraceId:id}),

 setLoading:(loading)=>set({isLoading:loading}),

 setError:(error)=>set({error}),

 toggleExpanded:(traceId)=>set((state)=>{
  const newSet=new Set(state.expandedTraceIds)
  if(newSet.has(traceId)){
   newSet.delete(traceId)
  }else{
   newSet.add(traceId)
  }
  return{expandedTraceIds:newSet}
 }),

 expandAll:()=>set((state)=>({
  expandedTraceIds:new Set(state.traces.map((t)=>t.id))
 })),

 collapseAll:()=>set({expandedTraceIds:new Set()}),

 reset:()=>set({
  traces:[],
  selectedTraceId:null,
  isLoading:false,
  error:null,
  expandedTraceIds:new Set()
 })
}))
