import{create}from'zustand'
import type{BrushupOptionsConfig,BrushupSuggestImage}from'@/types/brushup'
import{projectApi}from'@/services/apiService'

interface BrushupState{
 optionsConfig:BrushupOptionsConfig|null
 optionsLoading:boolean
 optionsError:string|null
 agentOptions:Record<string,string[]>
 customInstruction:string
 referenceImages:File[]
 suggestedImages:BrushupSuggestImage[]
 selectedSuggestedImageIds:Set<string>
 suggestLoading:boolean
 suggestError:string|null
 fetchOptions:()=>Promise<void>
 setAgentOptions:(agentType:string,options:string[])=>void
 toggleAgentOption:(agentType:string,optionId:string)=>void
 clearAgentOptions:(agentType:string)=>void
 setCustomInstruction:(instruction:string)=>void
 addReferenceImages:(files:File[])=>void
 removeReferenceImage:(index:number)=>void
 clearReferenceImages:()=>void
 setSuggestedImages:(images:BrushupSuggestImage[])=>void
 toggleSuggestedImage:(id:string)=>void
 setSuggestLoading:(loading:boolean)=>void
 setSuggestError:(error:string|null)=>void
 reset:()=>void
}

const initialState={
 optionsConfig:null as BrushupOptionsConfig|null,
 optionsLoading:false,
 optionsError:null as string|null,
 agentOptions:{} as Record<string,string[]>,
 customInstruction:'',
 referenceImages:[] as File[],
 suggestedImages:[] as BrushupSuggestImage[],
 selectedSuggestedImageIds:new Set<string>(),
 suggestLoading:false,
 suggestError:null as string|null
}

export const useBrushupStore=create<BrushupState>((set,get)=>({
 ...initialState,

 fetchOptions:async()=>{
  if(get().optionsConfig)return
  set({optionsLoading:true,optionsError:null})
  try{
   const config=await projectApi.getBrushupOptions()
   set({optionsConfig:config,optionsLoading:false})
  }catch(err){
   set({optionsError:'オプションの取得に失敗しました',optionsLoading:false})
  }
 },

 setAgentOptions:(agentType,options)=>set((state)=>({
  agentOptions:{...state.agentOptions,[agentType]:options}
 })),

 toggleAgentOption:(agentType,optionId)=>set((state)=>{
  const current=state.agentOptions[agentType]||[]
  const next=current.includes(optionId)
   ?current.filter(id=>id!==optionId)
   :[...current,optionId]
  return{agentOptions:{...state.agentOptions,[agentType]:next}}
 }),

 clearAgentOptions:(agentType)=>set((state)=>{
  const{[agentType]:_,...rest}=state.agentOptions
  return{agentOptions:rest}
 }),

 setCustomInstruction:(customInstruction)=>set({customInstruction}),

 addReferenceImages:(files)=>set((state)=>({
  referenceImages:[...state.referenceImages,...files]
 })),

 removeReferenceImage:(index)=>set((state)=>({
  referenceImages:state.referenceImages.filter((_,i)=>i!==index)
 })),

 clearReferenceImages:()=>set({referenceImages:[]}),

 setSuggestedImages:(suggestedImages)=>set({suggestedImages}),

 toggleSuggestedImage:(id)=>set((state)=>{
  const next=new Set(state.selectedSuggestedImageIds)
  if(next.has(id)){
   next.delete(id)
  }else{
   next.add(id)
  }
  return{selectedSuggestedImageIds:next}
 }),

 setSuggestLoading:(suggestLoading)=>set({suggestLoading}),

 setSuggestError:(suggestError)=>set({suggestError}),

 reset:()=>set((state)=>({
  ...initialState,
  optionsConfig:state.optionsConfig
 }))
}))
