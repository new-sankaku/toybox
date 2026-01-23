import{useState,useRef,useCallback}from'react'
import{Upload,X,File,Image,Music,Video,Code,FileText,Archive,AlertCircle}from'lucide-react'
import type{FileCategory}from'@/types/uploadedFile'

interface SelectedFile{
 file:File
 category:FileCategory
 preview?:string
}

interface FileUploaderProps{
 files:SelectedFile[]
 onFilesChange:(files:SelectedFile[])=>void
 disabled?:boolean
 maxFiles?:number
 maxSizeBytes?:number
}

const CATEGORY_ICONS:Record<FileCategory,typeof File>={
 code:Code,
 image:Image,
 audio:Music,
 video:Video,
 document:FileText,
 archive:Archive,
 other:File
}

function getCategoryFromFile(file:File):FileCategory{
 const ext=file.name.toLowerCase().split('.').pop()||''
 const extMap:Record<string,FileCategory>={
  txt:'document',md:'document',pdf:'document',
  js:'code',ts:'code',jsx:'code',tsx:'code',py:'code',java:'code',
  c:'code',cpp:'code',h:'code',cs:'code',html:'code',css:'code',
  json:'code',xml:'code',yaml:'code',yml:'code',
  png:'image',jpg:'image',jpeg:'image',gif:'image',
  webp:'image',svg:'image',bmp:'image',
  mp3:'audio',wav:'audio',ogg:'audio',flac:'audio',aac:'audio',m4a:'audio',
  mp4:'video',webm:'video',mov:'video',avi:'video',mkv:'video',
  zip:'archive',tar:'archive',gz:'archive',tgz:'archive','7z':'archive',rar:'archive'
 }
 return extMap[ext]||'other'
}

function formatFileSize(bytes:number):string{
 if(bytes<1024)return`${bytes} B`
 if(bytes<1024*1024)return`${(bytes/1024).toFixed(1)} KB`
 if(bytes<1024*1024*1024)return`${(bytes/(1024*1024)).toFixed(1)} MB`
 return`${(bytes/(1024*1024*1024)).toFixed(1)} GB`
}

export function FileUploader({
 files,
 onFilesChange,
 disabled=false,
 maxFiles=20,
 maxSizeBytes=4*1024*1024*1024
}:FileUploaderProps){
 const[dragActive,setDragActive]=useState(false)
 const[error,setError]=useState<string|null>(null)
 const inputRef=useRef<HTMLInputElement>(null)

 const handleFiles=useCallback((fileList:FileList|null)=>{
  if(!fileList)return
  setError(null)

  const newFiles:SelectedFile[]=[]
  const errors:string[]=[]

  for(let i=0;i<fileList.length;i++){
   const file=fileList[i]


   if(files.length+newFiles.length>=maxFiles){
    errors.push(`最大${maxFiles}ファイルまでです`)
    break
   }


   if(file.size>maxSizeBytes){
    errors.push(`${file.name}: ファイルサイズが大きすぎます (最大${formatFileSize(maxSizeBytes)})`)
    continue
   }


   if(files.some(f=>f.file.name===file.name)){
    errors.push(`${file.name}: 同名のファイルが既にあります`)
    continue
   }

   const category=getCategoryFromFile(file)
   const selectedFile:SelectedFile={file,category}


   if(category==='image'){
    selectedFile.preview=URL.createObjectURL(file)
   }

   newFiles.push(selectedFile)
  }

  if(errors.length>0){
   setError(errors.join('\n'))
  }

  if(newFiles.length>0){
   onFilesChange([...files,...newFiles])
  }
 },[files,maxFiles,maxSizeBytes,onFilesChange])

 const handleDrag=(e:React.DragEvent)=>{
  e.preventDefault()
  e.stopPropagation()
  if(disabled)return

  if(e.type==='dragenter'||e.type==='dragover'){
   setDragActive(true)
  }else if(e.type==='dragleave'){
   setDragActive(false)
  }
 }

 const handleDrop=(e:React.DragEvent)=>{
  e.preventDefault()
  e.stopPropagation()
  setDragActive(false)
  if(disabled)return

  handleFiles(e.dataTransfer.files)
 }

 const handleInputChange=(e:React.ChangeEvent<HTMLInputElement>)=>{
  handleFiles(e.target.files)
  if(inputRef.current)inputRef.current.value=''
 }

 const handleRemove=(index:number)=>{
  const newFiles=[...files]
  const removed=newFiles.splice(index,1)[0]
  if(removed.preview){
   URL.revokeObjectURL(removed.preview)
  }
  onFilesChange(newFiles)
 }

 const handleClick=()=>{
  if(!disabled)inputRef.current?.click()
 }

 const groupedFiles=files.reduce((acc,file)=>{
  if(!acc[file.category])acc[file.category]=[]
  acc[file.category].push(file)
  return acc
 },{} as Record<FileCategory,SelectedFile[]>)

 const categoryLabels:Record<FileCategory,string>={
  code:'Code',
  image:'Images',
  audio:'Audio',
  video:'Video',
  document:'Documents',
  archive:'Archives',
  other:'Other'
 }

 return(
  <div className="space-y-4">
   {/*Drop Zone*/}
   <div
    className={`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition-colors ${
     dragActive?'border-nier-accent bg-nier-accent/5':
     disabled?'border-nier-border bg-nier-dark/50 cursor-not-allowed':
     'border-nier-border hover:border-nier-accent/50'
    }`}
    onDragEnter={handleDrag}
    onDragLeave={handleDrag}
    onDragOver={handleDrag}
    onDrop={handleDrop}
    onClick={handleClick}
   >
    <input
     ref={inputRef}
     type="file"
     multiple
     onChange={handleInputChange}
     className="hidden"
     disabled={disabled}
     accept=".txt,.md,.pdf,.js,.ts,.jsx,.tsx,.py,.java,.c,.cpp,.h,.cs,.html,.css,.json,.xml,.yaml,.yml,.png,.jpg,.jpeg,.gif,.webp,.svg,.bmp,.mp3,.wav,.ogg,.flac,.aac,.m4a,.mp4,.webm,.mov,.avi,.mkv,.zip,.tar,.gz,.tgz,.7z,.rar"
    />
    <Upload size={32} className={`mx-auto mb-2 ${dragActive?'text-nier-accent':'text-nier-text-light'}`}/>
    <p className="text-nier-body text-nier-text">
     ファイルをドラッグ&ドロップ
    </p>
    <p className="text-nier-caption text-nier-text-light mt-1">
     またはクリックして選択
    </p>
    <p className="text-nier-caption text-nier-text-light mt-2">
     コード、画像、音声、動画、ドキュメント、Zip (最大{maxFiles}ファイル)
    </p>
   </div>

   {/*Error Message*/}
   {error&&(
    <div className="flex items-start gap-2 p-3 bg-red-50 border border-red-200 rounded text-red-700">
     <AlertCircle size={16} className="flex-shrink-0 mt-0.5"/>
     <pre className="text-nier-caption whitespace-pre-wrap">{error}</pre>
    </div>
)}

   {/*File List*/}
   {files.length>0&&(
    <div className="space-y-3">
     <div className="flex items-center justify-between text-nier-caption">
      <span className="text-nier-text-light">
       {files.length} ファイル選択中
      </span>
      <button
       type="button"
       onClick={()=>onFilesChange([])}
       className="text-red-500 hover:text-red-700"
       disabled={disabled}
      >
       すべてクリア
      </button>
     </div>

     {Object.entries(groupedFiles).map(([category,categoryFiles])=>{
      const Icon=CATEGORY_ICONS[category as FileCategory]
      return(
       <div key={category} className="border border-nier-border rounded p-3">
        <div className="flex items-center gap-2 mb-2">
         <Icon size={16} className="text-nier-text-light"/>
         <span className="text-nier-caption text-nier-text-light">
          {categoryLabels[category as FileCategory]} ({categoryFiles.length})
         </span>
        </div>
        <div className="space-y-1">
         {categoryFiles.map((selectedFile,idx)=>{
          const globalIndex=files.indexOf(selectedFile)
          return(
           <div
            key={idx}
            className="flex items-center gap-2 p-2 bg-nier-dark rounded"
           >
            {selectedFile.preview?(
             <img
              src={selectedFile.preview}
              alt={selectedFile.file.name}
              className="w-8 h-8 object-cover rounded"
             />
):(
             <Icon size={16} className="text-nier-text-light"/>
)}
            <span className="flex-1 text-nier-caption truncate">
             {selectedFile.file.name}
            </span>
            <span className="text-nier-caption text-nier-text-light">
             {formatFileSize(selectedFile.file.size)}
            </span>
            <button
             type="button"
             onClick={()=>handleRemove(globalIndex)}
             className="text-nier-text-light hover:text-red-500"
             disabled={disabled}
            >
             <X size={14}/>
            </button>
           </div>
)
         })}
        </div>
       </div>
)
     })}
    </div>
)}
  </div>
)
}
