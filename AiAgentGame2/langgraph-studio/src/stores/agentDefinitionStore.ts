import{create}from'zustand'
import{agentDefinitionApi,type AgentDefinition}from'@/services/apiService'

interface AgentDefinitionState{

 definitions:Record<string,AgentDefinition>
 loaded:boolean
 loading:boolean
 error:string | null
 fetchDefinitions:()=>Promise<void>
 getLabel:(type:string)=>string
 getShortLabel:(type:string)=>string
 getPhase:(type:string)=>number
 getSpeechBubble:(type:string)=>string
 getDefinition:(type:string)=>AgentDefinition | undefined
}

export const useAgentDefinitionStore = create<AgentDefinitionState>((set,get) => ({

 definitions:{},
 loaded:false,
 loading:false,
 error:null,
 fetchDefinitions:async() => {
  if(get().loaded || get().loading)return

  set({loading:true,error:null})
  try{
   const definitions = await agentDefinitionApi.getAll()
   set({definitions,loaded:true,loading:false})
  }catch(error){
   console.error('Failed to fetch agent definitions:',error)
   set({
    error:error instanceof Error ? error.message : 'Failed to fetch agent definitions',
    loading:false,
   })
  }
 },
 getLabel:(type:string) => {
  const definitions = get().definitions
  return definitions[type]?.label || type
 },

 getShortLabel:(type:string) => {
  const definitions = get().definitions
  return definitions[type]?.shortLabel || type
 },

 getPhase:(type:string) => {
  const definitions = get().definitions
  return definitions[type]?.phase ?? -1
 },

 getSpeechBubble:(type:string) => {
  const definitions = get().definitions
  return definitions[type]?.speechBubble || ''
 },

 getDefinition:(type:string) => {
  return get().definitions[type]
 },
}))
export const useAgentLabel = (type:string) => {
 return useAgentDefinitionStore((state) => state.definitions[type]?.label || type)
}

export const useAgentShortLabel = (type:string) => {
 return useAgentDefinitionStore((state) => state.definitions[type]?.shortLabel || type)
}
