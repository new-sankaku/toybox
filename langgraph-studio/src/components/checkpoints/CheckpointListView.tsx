import{useState,useMemo}from'react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{CheckpointCard}from'./CheckpointCard'
import type{Checkpoint}from'@/types/checkpoint'
import{cn}from'@/lib/utils'
import{Filter,Clock,CheckCircle,XCircle,RotateCcw,CircleDashed}from'lucide-react'

interface CheckpointListViewProps{
 checkpoints:Checkpoint[]
 onSelectCheckpoint:(checkpoint:Checkpoint)=>void
 selectedCheckpointId?:string
 loading?:boolean
}

type FilterStatus='all'|'incomplete'|'pending'|'approved'|'rejected'|'revision_requested'

const filterOptions:{value:FilterStatus;label:string;icon:typeof Filter}[]=[
 {value:'all',label:'全て',icon:Filter},
 {value:'incomplete',label:'未完了',icon:CircleDashed},
 {value:'pending',label:'承認待ち',icon:Clock},
 {value:'approved',label:'承認済み',icon:CheckCircle},
 {value:'rejected',label:'却下',icon:XCircle},
 {value:'revision_requested',label:'修正要求',icon:RotateCcw}
]

export default function CheckpointListView({
 checkpoints,
 onSelectCheckpoint,
 selectedCheckpointId,
 loading=false
}:CheckpointListViewProps):JSX.Element{
 const[filterStatus,setFilterStatus]=useState<FilterStatus>('incomplete')
 const[sortOrder,setSortOrder]=useState<'newest'|'oldest'>('newest')

 const filteredCheckpoints=useMemo(()=>{
  let filtered=checkpoints

  if(filterStatus==='incomplete'){
   filtered=filtered.filter(cp=>cp.status!=='approved')
  }else if(filterStatus!=='all'){
   filtered=filtered.filter(cp=>cp.status===filterStatus)
  }

  filtered=[...filtered].sort((a,b)=>{
   const dateA=new Date(a.createdAt).getTime()
   const dateB=new Date(b.createdAt).getTime()
   return sortOrder==='newest'?dateB-dateA : dateA-dateB
  })

  return filtered
 },[checkpoints,filterStatus,sortOrder])

 const statusCounts=useMemo(()=>{
  const incomplete=checkpoints.filter(cp=>cp.status!=='approved').length
  return{
   all:checkpoints.length,
   incomplete,
   pending:checkpoints.filter(cp=>cp.status==='pending').length,
   approved:checkpoints.filter(cp=>cp.status==='approved').length,
   rejected:checkpoints.filter(cp=>cp.status==='rejected').length,
   revision_requested:checkpoints.filter(cp=>cp.status==='revision_requested').length
  }
 },[checkpoints])

 return(
  <div className="p-4 animate-nier-fade-in h-full flex gap-3 overflow-hidden">
   {/*Checkpoint List-Main Content*/}
   <Card className="flex-1 flex flex-col overflow-hidden">
    <CardHeader className="flex-shrink-0">
     <DiamondMarker>承認一覧</DiamondMarker>
     <span className="text-nier-caption text-nier-text-light ml-2">
      ({filteredCheckpoints.length}件)
     </span>
    </CardHeader>
    <CardContent className="flex-1 overflow-y-auto">
     {loading&&checkpoints.length===0?(
      <div className="py-12 text-center text-nier-text-light">
       <p className="text-nier-body">読み込み中...</p>
      </div>
):filteredCheckpoints.length===0?(
      <div className="py-12 text-center text-nier-text-light">
       <p className="text-nier-body mb-2">承認がありません</p>
       <p className="text-nier-small">
        {filterStatus!=='all'
         ?`「${filterOptions.find(o=>o.value===filterStatus)?.label}」の承認はありません`
         :'エージェントの実行を開始してください'}
       </p>
      </div>
):(
      <div className="space-y-2">
       {filteredCheckpoints.map(checkpoint=>(
        <CheckpointCard
         key={checkpoint.id}
         checkpoint={checkpoint}
         onSelect={onSelectCheckpoint}
         isSelected={selectedCheckpointId===checkpoint.id}
        />
))}
      </div>
)}
    </CardContent>
   </Card>

   {/*Filter Sidebar*/}
   <div className="w-40 md:w-48 flex-shrink-0 flex flex-col gap-3 overflow-y-auto">
    {/*Status Filter*/}
    <Card>
     <CardHeader>
      <DiamondMarker>ステータス</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex flex-col gap-1">
       {filterOptions.map(option=>{
        const Icon=option.icon
        const count=statusCounts[option.value]
        return(
         <button
          key={option.value}
          className={cn(
           'flex items-center gap-2 px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
           filterStatus===option.value
            ?'bg-nier-bg-selected text-nier-text-main'
            : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
          onClick={()=>setFilterStatus(option.value)}
         >
          <Icon size={14}/>
          <span className="flex-1">{option.label}</span>
          <span className="text-nier-caption opacity-70">({count})</span>
         </button>
)
       })}
      </div>
     </CardContent>
    </Card>

    {/*Sort Order*/}
    <Card>
     <CardHeader>
      <DiamondMarker>並び順</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex flex-col gap-1">
       <button
        className={cn(
         'px-2 py-1.5 text-nier-small tracking-nier text-left',
         sortOrder==='newest'
          ?'bg-nier-bg-selected text-nier-text-main'
          : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
        onClick={()=>setSortOrder('newest')}
       >
        新しい順
       </button>
       <button
        className={cn(
         'px-2 py-1.5 text-nier-small tracking-nier text-left',
         sortOrder==='oldest'
          ?'bg-nier-bg-selected text-nier-text-main'
          : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
        onClick={()=>setSortOrder('oldest')}
       >
        古い順
       </button>
      </div>
     </CardContent>
    </Card>

    {/*Summary Stats*/}
    <Card>
     <CardHeader>
      <DiamondMarker>統計</DiamondMarker>
     </CardHeader>
     <CardContent>
      <div className="space-y-1 text-nier-small">
       <div className="flex justify-between">
        <span className="text-nier-text-light">総数</span>
        <span className="text-nier-text-main">{statusCounts.all}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">承認率</span>
        <span className="text-nier-text-main">
         {statusCounts.all>0?Math.round((statusCounts.approved/statusCounts.all)*100) : 0}%
        </span>
       </div>
       <div className="flex justify-between border-t border-nier-border-light pt-1 mt-1">
        <span className="text-nier-text-light">表示中</span>
        <span className="text-nier-text-main">{filteredCheckpoints.length}件</span>
       </div>
      </div>
     </CardContent>
    </Card>
   </div>
  </div>
)
}
