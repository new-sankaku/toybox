import{useState,useMemo}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import type{Project,ProjectStatus}from'@/types/project'
import{cn}from'@/lib/utils'
import{Plus,Trash2,RefreshCw,Pencil,Loader2,Square,CheckSquare}from'lucide-react'

const statusLabels:Record<ProjectStatus,string>={
 draft:'下書き',
 running:'実行中',
 paused:'一時停止',
 completed:'完了',
 failed:'エラー'
}

const formatDate=(dateString:string):string=>{
 const date=new Date(dateString)
 const y=date.getFullYear()
 const m=String(date.getMonth()+1).padStart(2,'0')
 const d=String(date.getDate()).padStart(2,'0')
 return`${y}/${m}/${d}`
}

interface ProjectListProps{
 projects:Project[]
 currentProject:Project|null
 isLoading:boolean
 onSelectProject:(project:Project)=>void
 onEditProject:(project:Project)=>void
 onDeleteProject:(projectId:string)=>void
 onBulkDelete:(projectIds:string[])=>void
 onRefresh:()=>void
 onNewProject:()=>void
}

export function ProjectList({
 projects,
 currentProject,
 isLoading,
 onSelectProject,
 onEditProject,
 onDeleteProject,
 onBulkDelete,
 onRefresh,
 onNewProject
}:ProjectListProps){
 const[selectedIds,setSelectedIds]=useState<Set<string>>(new Set())
 const[isSelectMode,setIsSelectMode]=useState(false)

 const sortedProjects=useMemo(()=>{
  return[...projects].sort((a,b)=>{
   const dateA=new Date(a.createdAt).getTime()
   const dateB=new Date(b.createdAt).getTime()
   return dateB-dateA
  })
 },[projects])

 const handleToggleSelect=(projectId:string,e:React.MouseEvent)=>{
  e.stopPropagation()
  setSelectedIds(prev=>{
   const next=new Set(prev)
   if(next.has(projectId)){
    next.delete(projectId)
   }else{
    next.add(projectId)
   }
   return next
  })
 }

 const handleSelectAll=()=>{
  if(selectedIds.size===sortedProjects.length){
   setSelectedIds(new Set())
  }else{
   setSelectedIds(new Set(sortedProjects.map(p=>p.id)))
  }
 }

 const handleBulkDelete=()=>{
  if(selectedIds.size>0){
   onBulkDelete(Array.from(selectedIds))
   setSelectedIds(new Set())
   setIsSelectMode(false)
  }
 }

 const handleCancelSelectMode=()=>{
  setSelectedIds(new Set())
  setIsSelectMode(false)
 }

 return(
  <Card className="flex flex-col overflow-hidden">
   <CardHeader>
    <div className="flex items-center justify-between w-full">
     <DiamondMarker>プロジェクト一覧</DiamondMarker>
     <div className="flex items-center gap-1 nier-surface-header">
      {isSelectMode?(
       <>
        <button
         onClick={handleSelectAll}
         className="p-1.5 hover:bg-nier-bg-selected transition-colors"
         title={selectedIds.size===sortedProjects.length?'全選択解除':'全選択'}
        >
         {selectedIds.size===sortedProjects.length?<CheckSquare size={16}/>:<Square size={16}/>}
        </button>
        <button
         onClick={handleBulkDelete}
         className={cn('p-1.5 transition-colors',selectedIds.size>0?'hover:bg-nier-bg-selected text-nier-accent-orange':'opacity-50 cursor-not-allowed')}
         title={`選択削除 (${selectedIds.size}件)`}
         disabled={selectedIds.size===0}
        >
         <Trash2 size={16}/>
        </button>
        <button
         onClick={handleCancelSelectMode}
         className="px-2 py-1 text-nier-caption hover:bg-nier-bg-selected transition-colors"
        >
         キャンセル
        </button>
       </>
):(
       <>
        <button
         onClick={()=>setIsSelectMode(true)}
         className="p-1.5 hover:bg-nier-bg-selected transition-colors"
         title="選択モード"
         disabled={projects.length===0}
        >
         <Square size={16}/>
        </button>
        <button
         onClick={onRefresh}
         className="p-1.5 hover:bg-nier-bg-selected transition-colors"
         title="更新"
         disabled={isLoading}
        >
         <RefreshCw size={16} className={isLoading?'animate-spin':''}/>
        </button>
        <button
         onClick={onNewProject}
         className="p-1.5 hover:bg-nier-bg-selected transition-colors"
         title="新規作成"
        >
         <Plus size={16}/>
        </button>
       </>
)}
     </div>
    </div>
   </CardHeader>
   <CardContent className="flex-1 overflow-y-auto">
    {isLoading&&projects.length===0?(
     <div className="text-center text-nier-text-light py-8">
      <Loader2 size={24} className="mx-auto mb-2 animate-spin"/>
      読み込み中...
     </div>
):projects.length===0?(
     <div className="text-center text-nier-text-light py-8">
      プロジェクトがありません
     </div>
):(
     <div className="space-y-2">
      {sortedProjects.map((project)=>(
       <div
        key={project.id}
        onClick={()=>isSelectMode?handleToggleSelect(project.id,{stopPropagation:()=>{}} as React.MouseEvent):onSelectProject(project)}
        className={cn(
         'p-3 border cursor-pointer transition-colors',
         currentProject?.id===project.id&&!isSelectMode
          ?'border-nier-border-light bg-nier-bg-selected'
          :selectedIds.has(project.id)
          ?'border-nier-accent-orange bg-nier-bg-selected'
          :'border-nier-border-light hover:bg-nier-bg-hover'
)}
       >
        <div className="flex items-start gap-2">
         {isSelectMode&&(
          <button
           onClick={(e)=>handleToggleSelect(project.id,e)}
           className="flex-shrink-0 mt-0.5"
          >
           {selectedIds.has(project.id)?<CheckSquare size={16} className="text-nier-accent-orange"/>:<Square size={16} className="text-nier-text-light"/>}
          </button>
)}
         <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between">
           <div className="flex-1 min-w-0">
            <div className="text-nier-small font-medium truncate">
             {project.name}
            </div>
            <div className="text-nier-caption text-nier-text-light truncate mt-0.5">
             {project.description}
            </div>
           </div>
           {!isSelectMode&&(
            <div className="flex items-center gap-2 ml-2">
             <span className="text-nier-caption text-nier-text-light">
              {statusLabels[project.status]}
             </span>
             <button
              onClick={(e)=>{
               e.stopPropagation()
               onEditProject(project)
              }}
              className="p-1 hover:bg-nier-bg-main transition-colors text-nier-text-light hover:text-nier-accent-gold"
              title="編集"
             >
              <Pencil size={12}/>
             </button>
             <button
              onClick={(e)=>{
               e.stopPropagation()
               onDeleteProject(project.id)
              }}
              className="p-1 hover:bg-nier-bg-main transition-colors text-nier-text-light hover:text-nier-text-main"
              title="削除"
             >
              <Trash2 size={12}/>
             </button>
            </div>
)}
          </div>
          <div className="flex items-center gap-2 text-nier-caption text-nier-text-light mt-1">
           <span>{formatDate(project.createdAt)}</span>
           <span>Phase {project.currentPhase}</span>
          </div>
         </div>
        </div>
       </div>
))}
     </div>
)}
   </CardContent>
  </Card>
)
}
