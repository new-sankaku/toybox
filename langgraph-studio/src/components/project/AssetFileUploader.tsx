import{useState,useRef,useCallback}from'react'
import{Upload,X,File,Image,Music,Video,FileText,Volume2,Mic}from'lucide-react'
import type{FileCategory}from'@/types/uploadedFile'

interface SelectedFile{
 file:File
 category:FileCategory
 preview?:string
}

interface AssetFileUploaderProps{
 files:SelectedFile[]
 onFilesChange:(files:SelectedFile[])=>void
 disabled?:boolean
 maxFilesPerCategory?:number
}

interface AssetCategoryConfig{
 key:FileCategory
 label:string
 icon:typeof File
 accept:string
 extensions:string[]
}

const ASSET_CATEGORIES:AssetCategoryConfig[]=[
 {
  key:'document',
  label:'企画書・資料',
  icon:FileText,
  accept:'.txt,.md,.pdf,.doc,.docx',
  extensions:['txt','md','pdf','doc','docx']
 },
 {
  key:'image',
  label:'画像素材',
  icon:Image,
  accept:'.png,.jpg,.jpeg,.gif,.webp,.svg,.bmp',
  extensions:['png','jpg','jpeg','gif','webp','svg','bmp']
 },
 {
  key:'bgm',
  label:'BGM',
  icon:Music,
  accept:'.mp3,.wav,.ogg,.flac,.aac,.m4a',
  extensions:['mp3','wav','ogg','flac','aac','m4a']
 },
 {
  key:'sfx',
  label:'効果音',
  icon:Volume2,
  accept:'.mp3,.wav,.ogg,.flac,.aac,.m4a',
  extensions:['mp3','wav','ogg','flac','aac','m4a']
 },
 {
  key:'voice',
  label:'ボイス素材',
  icon:Mic,
  accept:'.mp3,.wav,.ogg,.flac,.aac,.m4a',
  extensions:['mp3','wav','ogg','flac','aac','m4a']
 },
 {
  key:'video',
  label:'動画素材',
  icon:Video,
  accept:'.mp4,.webm,.mov,.avi,.mkv',
  extensions:['mp4','webm','mov','avi','mkv']
 }
]

function formatFileSize(bytes:number):string{
 if(bytes<1024)return`${bytes} B`
 if(bytes<1024*1024)return`${(bytes/1024).toFixed(1)} KB`
 return`${(bytes/(1024*1024)).toFixed(1)} MB`
}

interface CategoryDropZoneProps{
 config:AssetCategoryConfig
 files:SelectedFile[]
 onAdd:(files:SelectedFile[])=>void
 onRemove:(file:SelectedFile)=>void
 disabled:boolean
 maxFiles:number
}

function CategoryDropZone({config,files,onAdd,onRemove,disabled,maxFiles}:CategoryDropZoneProps){
 const[dragActive,setDragActive]=useState(false)
 const inputRef=useRef<HTMLInputElement>(null)
 const Icon=config.icon
 const categoryFiles=files.filter(f=>f.category===config.key)

 const handleFiles=useCallback((fileList:FileList|null)=>{
  if(!fileList)return
  const newFiles:SelectedFile[]=[]
  for(let i=0;i<fileList.length&&categoryFiles.length+newFiles.length<maxFiles;i++){
   const file=fileList[i]
   const ext=file.name.toLowerCase().split('.').pop()||''
   if(!config.extensions.includes(ext))continue
   if(categoryFiles.some(f=>f.file.name===file.name))continue
   const sf:SelectedFile={file,category:config.key}
   if(config.key==='image')sf.preview=URL.createObjectURL(file)
   newFiles.push(sf)
  }
  if(newFiles.length>0)onAdd(newFiles)
 },[categoryFiles,config,maxFiles,onAdd])

 const handleDrag=(e:React.DragEvent)=>{
  e.preventDefault()
  e.stopPropagation()
  if(disabled)return
  if(e.type==='dragenter'||e.type==='dragover')setDragActive(true)
  else if(e.type==='dragleave')setDragActive(false)
 }

 const handleDrop=(e:React.DragEvent)=>{
  e.preventDefault()
  e.stopPropagation()
  setDragActive(false)
  if(disabled)return
  handleFiles(e.dataTransfer.files)
 }

 return(
  <div className="border border-nier-border-light p-3">
   <div className="flex items-center gap-2 mb-2">
    <Icon size={16} className="text-nier-text-light"/>
    <span className="text-nier-small font-medium">{config.label}</span>
    {categoryFiles.length>0&&(
     <span className="text-nier-caption text-nier-text-light">({categoryFiles.length})</span>
)}
   </div>
   <div
    className={`border border-dashed p-3 text-center cursor-pointer transition-colors ${
     dragActive?'border-nier-accent-gold bg-nier-bg-selected':
     disabled?'border-nier-border-light bg-nier-bg-panel cursor-not-allowed':
     'border-nier-border-light hover:border-nier-accent-gold'
    }`}
    onDragEnter={handleDrag}
    onDragLeave={handleDrag}
    onDragOver={handleDrag}
    onDrop={handleDrop}
    onClick={()=>!disabled&&inputRef.current?.click()}
   >
    <input
     ref={inputRef}
     type="file"
     multiple
     onChange={(e)=>{handleFiles(e.target.files);if(inputRef.current)inputRef.current.value=''}}
     className="hidden"
     disabled={disabled}
     accept={config.accept}
    />
    <Upload size={20} className="mx-auto mb-1 text-nier-text-light"/>
    <p className="text-nier-caption text-nier-text-light">
     ドロップまたはクリック
    </p>
   </div>
   {categoryFiles.length>0&&(
    <div className="mt-2 space-y-1 max-h-[120px] overflow-y-auto">
     {categoryFiles.map((sf,idx)=>(
      <div key={idx} className="flex items-center gap-2 p-1.5 bg-nier-bg-panel text-nier-caption">
       {sf.preview?(
        <img src={sf.preview} alt="" className="w-6 h-6 object-cover"/>
):(
        <Icon size={14} className="text-nier-text-light"/>
)}
       <span className="flex-1 truncate">{sf.file.name}</span>
       <span className="text-nier-text-light">{formatFileSize(sf.file.size)}</span>
       <button
        type="button"
        onClick={(e)=>{e.stopPropagation();onRemove(sf)}}
        className="text-nier-text-light hover:text-nier-text-main"
        disabled={disabled}
       >
        <X size={14}/>
       </button>
      </div>
))}
    </div>
)}
  </div>
)
}

export function AssetFileUploader({
 files,
 onFilesChange,
 disabled=false,
 maxFilesPerCategory=10
}:AssetFileUploaderProps){
 const handleAdd=(newFiles:SelectedFile[])=>{
  onFilesChange([...files,...newFiles])
 }

 const handleRemove=(file:SelectedFile)=>{
  if(file.preview)URL.revokeObjectURL(file.preview)
  onFilesChange(files.filter(f=>f!==file))
 }

 const totalFiles=files.length

 return(
  <div className="space-y-3">
   <div className="grid grid-cols-2 gap-3">
    {ASSET_CATEGORIES.map(config=>(
     <CategoryDropZone
      key={config.key}
      config={config}
      files={files}
      onAdd={handleAdd}
      onRemove={handleRemove}
      disabled={disabled}
      maxFiles={maxFilesPerCategory}
     />
))}
   </div>
   {totalFiles>0&&(
    <div className="flex items-center justify-between text-nier-caption">
     <span className="text-nier-text-light">{totalFiles}ファイル選択中</span>
     <button
      type="button"
      onClick={()=>{
       files.forEach(f=>{if(f.preview)URL.revokeObjectURL(f.preview)})
       onFilesChange([])
      }}
      className="text-nier-text-light hover:text-nier-text-main"
      disabled={disabled}
     >
      すべてクリア
     </button>
    </div>
)}
  </div>
)
}
