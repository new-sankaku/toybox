import{useCallback,useState}from'react'
import{Upload,X,Image as ImageIcon}from'lucide-react'
import{cn}from'@/lib/utils'
import{useBrushupStore}from'@/stores/brushupStore'

export function BrushupReferenceImages(){
 const{
  referenceImages,
  addReferenceImages,
  removeReferenceImage
 }=useBrushupStore()
 const[isDragging,setIsDragging]=useState(false)

 const handleDrop=useCallback((e:React.DragEvent)=>{
  e.preventDefault()
  setIsDragging(false)
  const files=Array.from(e.dataTransfer.files).filter(f=>f.type.startsWith('image/'))
  if(files.length>0){
   addReferenceImages(files)
  }
 },[addReferenceImages])

 const handleDragOver=useCallback((e:React.DragEvent)=>{
  e.preventDefault()
  setIsDragging(true)
 },[])

 const handleDragLeave=useCallback((e:React.DragEvent)=>{
  e.preventDefault()
  setIsDragging(false)
 },[])

 const handleFileSelect=useCallback((e:React.ChangeEvent<HTMLInputElement>)=>{
  const files=Array.from(e.target.files||[]).filter(f=>f.type.startsWith('image/'))
  if(files.length>0){
   addReferenceImages(files)
  }
  e.target.value=''
 },[addReferenceImages])

 return(
  <div className="space-y-2">
   <div
    onDrop={handleDrop}
    onDragOver={handleDragOver}
    onDragLeave={handleDragLeave}
    className={cn(
     'border-2 border-dashed p-4 text-center transition-colors',
     isDragging?'border-nier-accent-gold bg-nier-bg-selected':'border-nier-border-light'
)}
   >
    <input
     type="file"
     accept="image/*"
     multiple
     onChange={handleFileSelect}
     className="hidden"
     id="brushup-reference-upload"
    />
    <label
     htmlFor="brushup-reference-upload"
     className="cursor-pointer flex flex-col items-center gap-2"
    >
     <Upload size={24} className="text-nier-text-light"/>
     <span className="text-nier-small text-nier-text-light">
      クリックまたはドラッグ＆ドロップで画像をアップロード
     </span>
    </label>
   </div>

   {referenceImages.length>0&&(
    <div className="flex flex-wrap gap-2">
     {referenceImages.map((file,index)=>(
      <div key={index} className="relative group">
       <img
        src={URL.createObjectURL(file)}
        alt={file.name}
        className="w-16 h-16 object-cover border border-nier-border-light"
       />
       <button
        type="button"
        onClick={()=>removeReferenceImage(index)}
        className="absolute -top-1 -right-1 w-5 h-5 bg-nier-bg-panel border border-nier-border-light flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
       >
        <X size={12}/>
       </button>
      </div>
))}
    </div>
)}

   {referenceImages.length===0&&(
    <div className="flex items-center gap-2 text-nier-caption text-nier-text-light">
     <ImageIcon size={14}/>
     <span>参考画像をアップロードしてください（任意）</span>
    </div>
)}
  </div>
)
}
