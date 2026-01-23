import{create}from'zustand'

export type ConnectionStatus='connected'|'connecting'|'reconnecting'|'disconnected'

interface ConnectionState{

 status:ConnectionStatus
 reconnectAttempts:number
 lastConnectedAt:Date|null
 backendPort:number|null
 hasPendingSync:boolean
 error:string|null
 setStatus:(status:ConnectionStatus)=>void
 setBackendPort:(port:number|null)=>void
 setError:(error:string|null)=>void
 incrementReconnect:()=>void
 resetReconnect:()=>void
 setSyncRequired:(required:boolean)=>void
 reset:()=>void
}

const initialState={
 status:'disconnected'as ConnectionStatus,
 reconnectAttempts:0,
 lastConnectedAt:null,
 backendPort:null,
 hasPendingSync:false,
 error:null
}

export const useConnectionStore=create<ConnectionState>((set)=>({
 ...initialState,

 setStatus:(status)=>
  set((state)=>({
   status,
   lastConnectedAt:status==='connected'?new Date() : state.lastConnectedAt
  })),

 setBackendPort:(port)=>set({backendPort:port}),

 setError:(error)=>set({error}),

 incrementReconnect:()=>
  set((state)=>({
   reconnectAttempts:state.reconnectAttempts+1
  })),

 resetReconnect:()=>set({reconnectAttempts:0}),

 setSyncRequired:(required)=>set({hasPendingSync:required}),

 reset:()=>set(initialState)
}))
