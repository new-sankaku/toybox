import{create}from'zustand'
import type{Checkpoint,CheckpointStatus}from'@/types/checkpoint'

interface CheckpointState{

 checkpoints:Checkpoint[]
 selectedCheckpointId:string|null
 isLoading:boolean
 error:string|null
 setCheckpoints:(checkpoints:Checkpoint[])=>void
 addCheckpoint:(checkpoint:Checkpoint)=>void
 updateCheckpoint:(id:string,updates:Partial<Checkpoint>)=>void
 updateCheckpointStatus:(id:string,status:CheckpointStatus,feedback?:string)=>void
 selectCheckpoint:(id:string|null)=>void
 setLoading:(loading:boolean)=>void
 setError:(error:string|null)=>void
 getSelectedCheckpoint:()=>Checkpoint|undefined
 getPendingCheckpoints:()=>Checkpoint[]
 getCheckpointsByProject:(projectId:string)=>Checkpoint[]
 getCheckpointsByType:(type:string)=>Checkpoint[]
}

export const useCheckpointStore=create<CheckpointState>((set,get)=>({

 checkpoints:[],
 selectedCheckpointId:null,
 isLoading:false,
 error:null,
 setCheckpoints:(checkpoints)=>set({checkpoints}),

 addCheckpoint:(checkpoint)=>
  set((state)=>({
   checkpoints:[...state.checkpoints,checkpoint]
  })),

 updateCheckpoint:(id,updates)=>
  set((state)=>({
   checkpoints:state.checkpoints.map((cp)=>
    cp.id===id?{...cp,...updates,updatedAt:new Date().toISOString()} : cp
)
  })),

 updateCheckpointStatus:(id,status,feedback)=>
  set((state)=>({
   checkpoints:state.checkpoints.map((cp)=>
    cp.id===id
     ?{
      ...cp,
      status,
      feedback:feedback||cp.feedback,
      updatedAt:new Date().toISOString()
     }
     : cp
)
  })),

 selectCheckpoint:(id)=>set({selectedCheckpointId:id}),

 setLoading:(loading)=>set({isLoading:loading}),

 setError:(error)=>set({error}),
 getSelectedCheckpoint:()=>{
  const state=get()
  return state.checkpoints.find((cp)=>cp.id===state.selectedCheckpointId)
 },

 getPendingCheckpoints:()=>{
  return get().checkpoints.filter((cp)=>cp.status==='pending')
 },

 getCheckpointsByProject:(projectId)=>{
  return get().checkpoints.filter((cp)=>cp.projectId===projectId)
 },

 getCheckpointsByType:(type)=>{
  return get().checkpoints.filter((cp)=>cp.type===type)
 }
}))
export const usePendingCheckpointsCount=()=>{
 return useCheckpointStore((state)=>
  state.checkpoints.filter((cp)=>cp.status==='pending').length
)
}

export const useCheckpointsByProject=(projectId:string)=>{
 return useCheckpointStore((state)=>
  state.checkpoints.filter((cp)=>cp.projectId===projectId)
)
}
