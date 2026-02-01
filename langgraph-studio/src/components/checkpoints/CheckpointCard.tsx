import{Card,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import type{Checkpoint}from'@/types/checkpoint'
import{Clock,FileText,Code}from'lucide-react'
import{useUIConfigStore}from'@/stores/uiConfigStore'

interface CheckpointCardProps{
 checkpoint:Checkpoint
 onSelect:(checkpoint:Checkpoint)=>void
 isSelected?:boolean
}

const statusConfig={
 pending:{
  color:'bg-nier-border-dark',
  pulse:false
 },
 approved:{
  color:'bg-nier-border-dark',
  pulse:false
 },
 rejected:{
  color:'bg-nier-border-dark',
  pulse:false
 },
 revision_requested:{
  color:'bg-nier-border-dark',
  pulse:false
 }
}

const typeIconMap:Record<string,typeof FileText>={
 code_review:Code,
 ui_integration_review:Code,
 unit_test_review:Code,
 integration_test_review:Code
}

export function CheckpointCard({
 checkpoint,
 onSelect,
 isSelected=false
}:CheckpointCardProps):JSX.Element{
 const{getCheckpointTypeLabel,getApprovalStatusLabel}=useUIConfigStore()
 const status=statusConfig[checkpoint.status]
 const TypeIcon=typeIconMap[checkpoint.type]||FileText
 const typeLabel=getCheckpointTypeLabel(checkpoint.type)
 const statusText=getApprovalStatusLabel(checkpoint.status)

 const getWaitingTime=()=>{
  const created=new Date(checkpoint.createdAt)
  const now=new Date()
  const diffMs=now.getTime()-created.getTime()
  const diffMins=Math.floor(diffMs/60000)

  if(diffMins<1)return'今すぐ'
  if(diffMins<60)return`${diffMins}分前`
  const hours=Math.floor(diffMins/60)
  if(hours<24)return`${hours}時間前`
  const days=Math.floor(hours/24)
  return`${days}日前`
 }

 return(
  <Card
   className={cn(
    'cursor-pointer transition-all duration-nier-normal',
    'hover:shadow-md hover:translate-x-1',
    isSelected&&'ring-2 ring-nier-accent-blue'
)}
   onClick={()=>onSelect(checkpoint)}
  >
   <CardContent className="p-3">
    {/*Header Row*/}
    <div className="flex items-start justify-between mb-2">
     <div className="flex items-center gap-2">
      {/*Category Marker*/}
      <div className={cn('w-1 h-8',status.color,status.pulse&&'animate-nier-pulse')}/>

      {/*Type Icon&Title*/}
      <div>
       <div className="flex items-center gap-1.5 mb-0.5">
        <TypeIcon size={12} className="text-nier-text-light"/>
        <span className="text-nier-caption text-nier-text-light tracking-nier">
         {typeLabel}
        </span>
       </div>
       <h3 className="text-nier-small font-medium text-nier-text-main">
        {checkpoint.title}
       </h3>
      </div>
     </div>

     {/*Status,Time,Tokens,Review Button*/}
     <div className="flex items-center gap-2">
      <span className="text-nier-caption text-nier-text-light flex items-center gap-1">
       <Clock size={10}/>
       {getWaitingTime()}
      </span>
      {checkpoint.output?.tokensUsed&&(
       <span className="text-nier-caption text-nier-text-light">
        {checkpoint.output.tokensUsed.toLocaleString()}tk
       </span>
)}
      <div className="px-1.5 py-0.5 text-nier-caption tracking-nier bg-nier-bg-selected text-nier-text-light border border-nier-border-light">
       {statusText}
      </div>
      <Button
       variant="ghost"
       size="sm"
       className="text-nier-text-light py-0 px-1.5 text-nier-caption"
       onClick={(e)=>{
        e.stopPropagation()
        onSelect(checkpoint)
       }}
      >
       レビュー
      </Button>
     </div>
    </div>

    {/*Summary*/}
    {checkpoint.output?.summary&&(
     <p className="text-nier-caption text-nier-text-light line-clamp-2 pl-3">
      {checkpoint.output.summary}
     </p>
)}
   </CardContent>
  </Card>
)
}
