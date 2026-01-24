import{create}from'zustand'
import type{ApiAIRequestStats}from'@/services/apiService'

interface AIStatsState{
 stats:ApiAIRequestStats|null
 isLoading:boolean
 error:string|null
 setStats:(stats:ApiAIRequestStats)=>void
 setLoading:(loading:boolean)=>void
 setError:(error:string|null)=>void
 reset:()=>void
 getGeneratingCount:()=>number
}

export const useAIStatsStore=create<AIStatsState>((set,get)=>({
 stats:null,
 isLoading:false,
 error:null,

 setStats:(stats)=>set({stats}),

 setLoading:(loading)=>set({isLoading:loading}),

 setError:(error)=>set({error}),

 reset:()=>set({
  stats:null,
  isLoading:false,
  error:null
 }),

 getGeneratingCount:()=>{
  const stats=get().stats
  if(!stats)return 0
  return stats.processing+stats.pending
 }
}))

export const useGeneratingCount=()=>{
 return useAIStatsStore((state)=>{
  if(!state.stats)return 0
  return state.stats.processing+state.stats.pending
 })
}
