import{create}from'zustand'
import type{Intervention}from'@/types/intervention'

interface InterventionState{
 interventions:Intervention[]
 selectedInterventionId:string|null
 isLoading:boolean
 error:string|null
 setInterventions:(interventions:Intervention[])=>void
 addIntervention:(intervention:Intervention)=>void
 updateIntervention:(id:string,updates:Partial<Intervention>)=>void
 removeIntervention:(id:string)=>void
 selectIntervention:(id:string|null)=>void
 setLoading:(loading:boolean)=>void
 setError:(error:string|null)=>void
 reset:()=>void
 getWaitingResponseInterventions:()=>Intervention[]
 getInterventionsByProject:(projectId:string)=>Intervention[]
}

export const useInterventionStore=create<InterventionState>((set,get)=>({
 interventions:[],
 selectedInterventionId:null,
 isLoading:false,
 error:null,
 setInterventions:(interventions)=>set({interventions}),
 addIntervention:(intervention)=>
  set((state)=>{
   const exists=state.interventions.some((i)=>i.id===intervention.id)
   if(exists){
    return{
     interventions:state.interventions.map((i)=>
      i.id===intervention.id?intervention:i
)
    }
   }
   return{interventions:[...state.interventions,intervention]}
  }),
 updateIntervention:(id,updates)=>
  set((state)=>({
   interventions:state.interventions.map((i)=>
    i.id===id?{...i,...updates}:i
)
  })),
 removeIntervention:(id)=>
  set((state)=>({
   interventions:state.interventions.filter((i)=>i.id!==id),
   selectedInterventionId:state.selectedInterventionId===id?null:state.selectedInterventionId
  })),
 selectIntervention:(id)=>set({selectedInterventionId:id}),
 setLoading:(loading)=>set({isLoading:loading}),
 setError:(error)=>set({error}),
 reset:()=>set({
  interventions:[],
  selectedInterventionId:null,
  isLoading:false,
  error:null
 }),
 getWaitingResponseInterventions:()=>{
  return get().interventions.filter((i)=>i.status==='waiting_response')
 },
 getInterventionsByProject:(projectId)=>{
  return get().interventions.filter((i)=>i.projectId===projectId)
 }
}))

export const useWaitingResponseCount=()=>{
 return useInterventionStore((state)=>
  state.interventions.filter((i)=>i.status==='waiting_response').length
)
}

export const useInterventionsByProject=(projectId:string)=>{
 return useInterventionStore((state)=>
  state.interventions.filter((i)=>i.projectId===projectId)
)
}
