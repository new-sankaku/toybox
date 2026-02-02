import{create}from'zustand'
import{agentDefinitionApi,type AgentDefinition,type UIPhase}from'@/services/apiService'
import type{AssetGenerationOptions}from'@/config/projectOptions'

interface AgentDefinitionState{
 definitions:Record<string,AgentDefinition>
 uiPhases:UIPhase[]
 agentAssetMapping:Record<string,string[]>
 workflowDependencies:Record<string,string[]>
 loaded:boolean
 loading:boolean
 error:string|null
 fetchDefinitions:()=>Promise<void>
 getLabel:(type:string)=>string
 getShortLabel:(type:string)=>string
 getPhase:(type:string)=>number
 getSpeechBubble:(type:string)=>string
 getDefinition:(type:string)=>AgentDefinition|undefined
 getFilteredUIPhases:(assetGeneration?:AssetGenerationOptions)=>UIPhase[]
 getEnabledAgents:(assetGeneration?:AssetGenerationOptions)=>Set<string>
 getWorkflowDependencies:()=>Record<string,string[]>
}

export const useAgentDefinitionStore=create<AgentDefinitionState>((set,get)=>({
 definitions:{},
 uiPhases:[],
 agentAssetMapping:{},
 workflowDependencies:{},
 loaded:false,
 loading:false,
 error:null,
 fetchDefinitions:async()=>{
  if(get().loaded||get().loading)return
  set({loading:true,error:null})
  try{
   const response=await agentDefinitionApi.getAll()
   set({
    definitions:response.agents||{},
    uiPhases:response.uiPhases||[],
    agentAssetMapping:response.agentAssetMapping||{},
    workflowDependencies:response.workflowDependencies||{},
    loaded:true,
    loading:false
   })
  }catch(error){
   console.error('Failed to fetch agent definitions:',error)
   set({
    error:error instanceof Error?error.message:'Failed to fetch agent definitions',
    loading:false,
   })
  }
 },
 getLabel:(type:string)=>{
  const definitions=get().definitions
  return definitions[type]?.label||type
 },
 getShortLabel:(type:string)=>{
  const definitions=get().definitions
  return definitions[type]?.shortLabel||type
 },
 getPhase:(type:string)=>{
  const definitions=get().definitions
  return definitions[type]?.phase??-1
 },
 getSpeechBubble:(type:string)=>{
  const definitions=get().definitions
  return definitions[type]?.speechBubble||''
 },
 getDefinition:(type:string)=>{
  return get().definitions[type]
 },
 getEnabledAgents:(assetGeneration?:AssetGenerationOptions)=>{
  const{agentAssetMapping,definitions}=get()
  if(!definitions)return new Set<string>()
  const allAgents=new Set(Object.keys(definitions))
  if(!assetGeneration)return allAgents
  const disabledAgents=new Set<string>()
  for(const[setting,agents]of Object.entries(agentAssetMapping||{})){
   const key=setting as keyof AssetGenerationOptions
   if(!assetGeneration[key]){
    agents.forEach(a=>disabledAgents.add(a))
   }
  }
  return new Set([...allAgents].filter(a=>!disabledAgents.has(a)))
 },
 getFilteredUIPhases:(assetGeneration?:AssetGenerationOptions)=>{
  const{uiPhases}=get()
  if(!uiPhases||uiPhases.length===0)return[]
  const enabledAgents=get().getEnabledAgents(assetGeneration)
  return uiPhases.map(phase=>({
   ...phase,
   agents:phase.agents.filter(a=>enabledAgents.has(a))
  })).filter(phase=>phase.agents.length>0)
 },
 getWorkflowDependencies:()=>{
  return get().workflowDependencies||{}
 },
}))
export const useAgentLabel=(type:string)=>{
 return useAgentDefinitionStore((state)=>state.definitions[type]?.label||type)
}

export const useAgentShortLabel=(type:string)=>{
 return useAgentDefinitionStore((state)=>state.definitions[type]?.shortLabel||type)
}
