import{Loader2,Sparkles,Check}from'lucide-react'
import{cn}from'@/lib/utils'
import{Button}from'@/components/ui/Button'
import{useBrushupStore}from'@/stores/brushupStore'
import{projectApi,extractApiError}from'@/services/apiService'

interface Props{
 projectId:string
}

export function BrushupSuggestImages({projectId}:Props){
 const{
  selectedPresets,
  customInstruction,
  suggestedImages,
  selectedSuggestedImageIds,
  suggestLoading,
  suggestError,
  setSuggestedImages,
  toggleSuggestedImage,
  setSuggestLoading,
  setSuggestError
 }=useBrushupStore()

 const handleGenerate=async()=>{
  if(selectedPresets.size===0&&!customInstruction.trim())return

  setSuggestLoading(true)
  setSuggestError(null)
  try{
   const result=await projectApi.suggestBrushupImages(projectId,{
    presets:Array.from(selectedPresets),
    customInstruction,
    count:3
   })
   setSuggestedImages(result.images)
  }catch(err){
   const apiError=extractApiError(err)
   setSuggestError(apiError.message)
  }finally{
   setSuggestLoading(false)
  }
 }

 const canGenerate=selectedPresets.size>0||customInstruction.trim().length>0

 return(
  <div className="space-y-3">
   <div className="flex items-center gap-2">
    <Button
     variant="secondary"
     onClick={handleGenerate}
     disabled={!canGenerate||suggestLoading}
    >
     {suggestLoading?(
      <Loader2 size={14} className="mr-1.5 animate-spin"/>
):(
      <Sparkles size={14} className="mr-1.5"/>
)}
     サジェスト画像を生成
    </Button>
    {!canGenerate&&(
     <span className="text-nier-caption text-nier-text-light">
      プリセットまたはカスタム指示を入力してください
     </span>
)}
   </div>

   {suggestError&&(
    <div className="text-nier-small text-nier-text-main">
     {suggestError}
    </div>
)}

   {suggestedImages.length>0&&(
    <div className="flex flex-wrap gap-2">
     {suggestedImages.map((image)=>(
      <button
       key={image.id}
       type="button"
       onClick={()=>toggleSuggestedImage(image.id)}
       className={cn(
        'relative group border-2 transition-colors',
        selectedSuggestedImageIds.has(image.id)
         ?'border-nier-accent-gold'
         :'border-nier-border-light hover:border-nier-border-dark'
)}
      >
       <div className="w-20 h-20 bg-nier-bg-selected flex items-center justify-center">
        <Sparkles size={24} className="text-nier-text-light"/>
       </div>
       {selectedSuggestedImageIds.has(image.id)&&(
        <div className="absolute top-1 right-1 w-5 h-5 bg-nier-accent-gold flex items-center justify-center">
         <Check size={12} className="text-white"/>
        </div>
)}
       <div className="absolute bottom-0 left-0 right-0 bg-black/50 px-1 py-0.5">
        <span className="text-nier-caption text-white truncate block">
         {image.prompt.slice(0,20)}...
        </span>
       </div>
      </button>
))}
    </div>
)}

   {suggestedImages.length===0&&!suggestLoading&&(
    <div className="text-nier-caption text-nier-text-light">
     生成ボタンをクリックすると、選択した方向性に基づいてAIが参考画像を生成します
    </div>
)}
  </div>
)
}
