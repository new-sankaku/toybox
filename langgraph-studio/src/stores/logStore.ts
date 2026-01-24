import{create}from'zustand'
import type{ApiSystemLog}from'@/services/apiService'

interface LogState{
 logs:ApiSystemLog[]
 isLoading:boolean
 error:string|null
 setLogs:(logs:ApiSystemLog[])=>void
 addLog:(log:ApiSystemLog)=>void
 setLoading:(loading:boolean)=>void
 setError:(error:string|null)=>void
 reset:()=>void
 getLogsByLevel:(level:'debug'|'info'|'warn'|'error')=>ApiSystemLog[]
 getErrorCount:()=>number
}

export const useLogStore=create<LogState>((set,get)=>({
 logs:[],
 isLoading:false,
 error:null,

 setLogs:(logs)=>set({logs}),

 addLog:(log)=>
  set((state)=>({
   logs:[log,...state.logs]
  })),

 setLoading:(loading)=>set({isLoading:loading}),

 setError:(error)=>set({error}),

 reset:()=>set({
  logs:[],
  isLoading:false,
  error:null
 }),

 getLogsByLevel:(level)=>{
  return get().logs.filter((log)=>log.level===level)
 },

 getErrorCount:()=>{
  return get().logs.filter((l)=>l.level==='error').length
 }
}))

export const useLogsCount=()=>{
 return useLogStore((state)=>state.logs.length)
}

export const useErrorLogsCount=()=>{
 return useLogStore((state)=>
  state.logs.filter((l)=>l.level==='error').length
)
}
