import{useRef,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{cn}from'@/lib/utils'
import type{AgentLogEntry,LogLevel}from'@/types/agent'
import{AlertCircle,Info,AlertTriangle,Bug}from'lucide-react'

interface AgentLogProps{
 logs:AgentLogEntry[]
 autoScroll?:boolean
}

const levelConfig:Record<LogLevel,{icon:typeof Info;color:string;label:string}>={
 debug:{
  icon:Bug,
  color:'text-nier-text-light',
  label:'DEBUG'
 },
 info:{
  icon:Info,
  color:'text-nier-accent-blue',
  label:'INFO'
 },
 warn:{
  icon:AlertTriangle,
  color:'text-nier-accent-orange',
  label:'WARN'
 },
 error:{
  icon:AlertCircle,
  color:'text-nier-accent-red',
  label:'ERROR'
 }
}

export function AgentLog({
 logs,
 autoScroll=true
}:AgentLogProps):JSX.Element{
 const scrollRef=useRef<HTMLDivElement>(null)

 useEffect(()=>{
  if(autoScroll&&scrollRef.current){
   scrollRef.current.scrollTop=scrollRef.current.scrollHeight
  }
 },[logs,autoScroll])

 const formatTime=(timestamp:string)=>{
  const date=new Date(timestamp)
  return date.toLocaleTimeString('ja-JP',{
   hour:'2-digit',
   minute:'2-digit',
   second:'2-digit',
   fractionalSecondDigits:3
  })
 }

 return(
  <Card>
   <CardHeader className="flex flex-row items-center justify-between">
    <DiamondMarker>実行ログ</DiamondMarker>
    <span className="text-nier-caption text-nier-text-light">
     {logs.length}件のエントリ
    </span>
   </CardHeader>
   <CardContent>
    <div
     ref={scrollRef}
     className="font-mono text-nier-small bg-nier-bg-main nier-log-panel"
    >
     {logs.length===0?(
      <div className="p-4 text-center text-nier-text-light">
       ログがありません
      </div>
) : (
      <div className="divide-y divide-nier-border-light">
       {logs.map((entry)=>{
        const config=levelConfig[entry.level]
        const Icon=config.icon

        return(
         <div
          key={entry.id}
          className={cn(
           'p-2 hover:bg-nier-bg-panel transition-colors',
           entry.level==='error'&&'bg-nier-accent-red/5'
)}
         >
          <div className="flex items-start gap-3">

           <span className="text-nier-caption text-nier-text-light whitespace-nowrap">
            {formatTime(entry.timestamp)}
           </span>


           <span
            className={cn(
             'flex items-center gap-1 text-nier-caption whitespace-nowrap',
             config.color
)}
           >
            <Icon size={12}/>
            <span>{config.label}</span>
           </span>


           <span className="text-nier-text-main break-all">
            {entry.message}
           </span>


           {entry.progress!==undefined&&(
            <span className="text-nier-caption text-nier-accent-orange ml-auto whitespace-nowrap">
             {entry.progress}%
            </span>
)}
          </div>


          {entry.metadata&&Object.keys(entry.metadata).length>0&&(
           <div className="mt-1 ml-20 text-nier-caption text-nier-text-light">
            <pre className="whitespace-pre-wrap">
             {JSON.stringify(entry.metadata,null,2)}
            </pre>
           </div>
)}
         </div>
)
       })}
      </div>
)}
    </div>
   </CardContent>
  </Card>
)
}

export function AgentLogStreaming({
 logs,
 isStreaming=false
}:AgentLogProps&{isStreaming?:boolean}):JSX.Element{
 return(
  <div className="relative">
   <AgentLog logs={logs} autoScroll={isStreaming}/>
   {isStreaming&&(
    <div className="absolute bottom-4 right-4">
     <div className="flex items-center gap-2 bg-nier-bg-panel px-2 py-1 text-nier-caption">
      <div className="w-2 h-2 bg-nier-accent-green rounded-full animate-pulse"/>
      <span className="text-nier-accent-green">LIVE</span>
     </div>
    </div>
)}
  </div>
)
}
