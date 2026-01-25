import{create}from'zustand'
import type{BrushupPreset,BrushupSuggestImage}from'@/types/brushup'

interface BrushupState{
 presets:BrushupPreset[]
 presetsLoading:boolean
 presetsError:string|null
 selectedPresets:Set<string>
 customInstruction:string
 referenceImages:File[]
 suggestedImages:BrushupSuggestImage[]
 selectedSuggestedImageIds:Set<string>
 suggestLoading:boolean
 suggestError:string|null
 setPresets:(presets:BrushupPreset[])=>void
 setPresetsLoading:(loading:boolean)=>void
 setPresetsError:(error:string|null)=>void
 togglePreset:(id:string)=>void
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
 presets:[],
 presetsLoading:false,
 presetsError:null,
 selectedPresets:new Set<string>(),
 customInstruction:'',
 referenceImages:[],
 suggestedImages:[],
 selectedSuggestedImageIds:new Set<string>(),
 suggestLoading:false,
 suggestError:null
}

export const useBrushupStore=create<BrushupState>((set)=>({
 ...initialState,

 setPresets:(presets)=>set({presets}),

 setPresetsLoading:(presetsLoading)=>set({presetsLoading}),

 setPresetsError:(presetsError)=>set({presetsError}),

 togglePreset:(id)=>set((state)=>{
  const next=new Set(state.selectedPresets)
  if(next.has(id)){
   next.delete(id)
  }else{
   next.add(id)
  }
  return{selectedPresets:next}
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
  presets:state.presets
 }))
}))
