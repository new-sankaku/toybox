import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Loader2,FileText,Image,Music,File}from'lucide-react'

interface UploadedFile{
 id:string
 filename:string
 originalFilename:string
 mimeType:string
 category:string
 sizeBytes:number
 url:string
 uploadedAt:string
}

interface ProjectFilesProps{
 files:UploadedFile[]
 isLoading:boolean
 error:string|null
}

export function ProjectFiles({files,isLoading,error}:ProjectFilesProps){
 return(
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between w-full">
     <DiamondMarker>アップロードファイル</DiamondMarker>
     <span className="text-nier-caption text-nier-text-light">{files.length}件</span>
    </div>
   </CardHeader>
   <CardContent>
    {isLoading?(
     <div className="text-center py-4 text-nier-text-light">
      <Loader2 size={20} className="mx-auto mb-2 animate-spin"/>
      読み込み中...
     </div>
    ):error?(
     <div className="text-center py-4 text-nier-text-light">
      {error}
     </div>
    ):files.length===0?(
     <div className="text-center py-4 text-nier-text-light">
      アップロードファイルはありません
     </div>
    ):(
     <div className="grid grid-cols-2 gap-2 max-h-[200px] overflow-y-auto">
      {files.map((file)=>{
       const isImage=file.mimeType.startsWith('image/')
       const isAudio=file.mimeType.startsWith('audio/')
       const isPdf=file.mimeType==='application/pdf'
       const FileIcon=isImage?Image:isAudio?Music:isPdf?FileText:File
       const sizeKB=Math.round(file.sizeBytes/1024)

       return(
        <div
         key={file.id}
         className="flex items-center gap-2 p-2 border border-nier-border-light hover:bg-nier-bg-hover"
        >
         {isImage&&file.url?(
          <img
           src={file.url}
           alt={file.originalFilename}
           className="w-10 h-10 object-cover rounded"
          />
         ):(
          <div className="w-10 h-10 flex items-center justify-center bg-nier-bg-selected rounded">
           <FileIcon size={20} className="text-nier-text-light"/>
          </div>
         )}
         <div className="flex-1 min-w-0">
          <div className="text-nier-small truncate">{file.originalFilename}</div>
          <div className="text-nier-caption text-nier-text-light">
           {file.category}/{sizeKB}KB
          </div>
         </div>
        </div>
       )
      })}
     </div>
    )}
   </CardContent>
  </Card>
 )
}
