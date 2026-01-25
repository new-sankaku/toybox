import{useEffect}from'react'
import{Check,Loader2}from'lucide-react'
import{cn}from'@/lib/utils'
import{useBrushupStore}from'@/stores/brushupStore'
import{configApi,extractApiError}from'@/services/apiService'

export function BrushupPresetSelector(){
 const{
  presets,
  presetsLoading,
  presetsError,
  selectedPresets,
  setPresets,
  setPresetsLoading,
  setPresetsError,
  togglePreset
 }=useBrushupStore()

 useEffect(()=>{
  if(presets.length===0&&!presetsLoading){
   loadPresets()
  }
 },[])

 const loadPresets=async()=>{
  setPresetsLoading(true)
  setPresetsError(null)
  try{
   const data=await configApi.getBrushupPresets()
   setPresets(data.presets)
  }catch(err){
   const apiError=extractApiError(err)
   setPresetsError(apiError.message)
  }finally{
   setPresetsLoading(false)
  }
 }

 if(presetsLoading){
  return(
   <div className="flex items-center justify-center py-4 text-nier-text-light">
    <Loader2 size={16} className="animate-spin mr-2"/>
    読み込み中...
   </div>
)
 }

 if(presetsError){
  return(
   <div className="text-nier-text-main text-nier-small py-2">
    {presetsError}
   </div>
)
 }

 return(
  <div className="grid grid-cols-2 gap-2">
   {presets.map((preset)=>(
    <button
     key={preset.id}
     type="button"
     onClick={()=>togglePreset(preset.id)}
     className={cn(
      'flex items-start gap-2 p-2 border text-left transition-colors',
      selectedPresets.has(preset.id)
       ?'border-nier-accent-gold bg-nier-bg-selected'
       :'border-nier-border-light hover:bg-nier-bg-hover'
)}
    >
     <span className={cn(
      'w-4 h-4 flex-shrink-0 border flex items-center justify-center mt-0.5',
      selectedPresets.has(preset.id)?'bg-nier-bg-selected border-nier-border-dark':'border-nier-border-light'
)}>
      {selectedPresets.has(preset.id)&&<Check size={12}/>}
     </span>
     <div className="flex-1 min-w-0">
      <div className="text-nier-small font-medium">{preset.label}</div>
      <div className="text-nier-caption text-nier-text-light">{preset.description}</div>
     </div>
    </button>
))}
  </div>
)
}
