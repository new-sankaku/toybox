import{useState}from'react'
import{Image,Music,Download,ZoomIn,ZoomOut,Volume2,VolumeX,Play,Pause}from'lucide-react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'

export interface Asset{
 id:string
 type:'image'|'audio'
 name:string
 url:string
 mimeType:string
 dimensions?:{width:number;height:number}
 duration?:number // seconds for audio
 size?:number // bytes
 createdAt?:string
}

interface AssetViewerProps{
 asset:Asset
 onDownload?:(asset:Asset)=>void
}

export function AssetViewer({asset,onDownload}:AssetViewerProps){
 const[zoom,setZoom]=useState(1)
 const[isPlaying,setIsPlaying]=useState(false)
 const[isMuted,setIsMuted]=useState(false)

 const handleZoomIn=()=>setZoom((z)=>Math.min(z+0.25,3))
 const handleZoomOut=()=>setZoom((z)=>Math.max(z-0.25,0.5))

 const formatSize=(bytes:number):string=>{
  if(bytes<1024)return`${bytes} B`
  if(bytes<1024*1024)return`${(bytes/1024).toFixed(1)} KB`
  return`${(bytes/(1024*1024)).toFixed(1)} MB`
 }

 const formatDuration=(seconds:number):string=>{
  const mins=Math.floor(seconds/60)
  const secs=Math.floor(seconds%60)
  return`${mins}:${secs.toString().padStart(2,'0')}`
 }

 return(
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between w-full">
     <div className="flex items-center gap-2">
      {asset.type==='image'?(
       <Image size={16} className="text-nier-accent-blue"/>
) : (
       <Music size={16} className="text-nier-accent-green"/>
)}
      <span className="text-nier-small">{asset.name}</span>
     </div>

     {/* Controls */}
     <div className="flex items-center gap-1">
      {asset.type==='image'&&(
       <>
        <Button
         variant="ghost"
         size="icon"
         className="h-7 w-7"
         onClick={handleZoomOut}
         disabled={zoom<=0.5}
        >
         <ZoomOut size={14}/>
        </Button>
        <span className="text-nier-caption w-12 text-center">
         {Math.round(zoom*100)}%
        </span>
        <Button
         variant="ghost"
         size="icon"
         className="h-7 w-7"
         onClick={handleZoomIn}
         disabled={zoom>=3}
        >
         <ZoomIn size={14}/>
        </Button>
       </>
)}

      {asset.type==='audio'&&(
       <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={()=>setIsMuted(!isMuted)}
       >
        {isMuted?<VolumeX size={14}/>:<Volume2 size={14}/>}
       </Button>
)}

      {onDownload&&(
       <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={()=>onDownload(asset)}
       >
        <Download size={14}/>
       </Button>
)}
     </div>
    </div>
   </CardHeader>

   <CardContent className="p-0">
    {/* Image Viewer */}
    {asset.type==='image'&&(
     <div className="relative overflow-auto bg-nier-bg-main" style={{maxHeight:'400px'}}>
      <div
       className="flex items-center justify-center min-h-[200px] p-4"
       style={{transform:`scale(${zoom})`,transformOrigin:'center'}}
      >
       <img
        src={asset.url}
        alt={asset.name}
        className="max-w-full h-auto"
        style={{imageRendering:zoom>1?'pixelated' : 'auto'}}
       />
      </div>
     </div>
)}

    {/* Audio Player */}
    {asset.type==='audio'&&(
     <div className="p-6 bg-nier-bg-main">
      <div className="flex items-center gap-4">
       <Button
        variant="primary"
        size="icon"
        onClick={()=>setIsPlaying(!isPlaying)}
       >
        {isPlaying?<Pause size={18}/>:<Play size={18}/>}
       </Button>

       {/* Waveform placeholder */}
       <div className="flex-1 h-12 bg-nier-bg-selected flex items-center justify-center">
        <div className="flex items-end gap-0.5 h-8">
         {Array.from({length:40}).map((_,i)=>(
          <div
           key={i}
           className={cn(
            'w-1 bg-nier-text-main transition-all',
            isPlaying&&'animate-pulse'
)}
           style={{
            height:`${20+Math.random()*80}%`
           }}
          />
))}
        </div>
       </div>

       {asset.duration&&(
        <span className="text-nier-small text-nier-text-light">
         {formatDuration(asset.duration)}
        </span>
)}
      </div>

      <audio
       src={asset.url}
       muted={isMuted}
       className="hidden"
      />
     </div>
)}

    {/* Meta Info */}
    <div className="px-4 py-2 border-t border-nier-border-light flex items-center justify-between text-nier-caption text-nier-text-light">
     <div className="flex items-center gap-4">
      {asset.dimensions&&(
       <span>{asset.dimensions.width} × {asset.dimensions.height}</span>
)}
      {asset.duration&&(
       <span>{formatDuration(asset.duration)}</span>
)}
      {asset.size&&(
       <span>{formatSize(asset.size)}</span>
)}
     </div>
     <span>{asset.mimeType}</span>
    </div>
   </CardContent>
  </Card>
)
}
