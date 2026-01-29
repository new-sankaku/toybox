import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import type{Project,ProjectStatus}from'@/types/project'
import{cn}from'@/lib/utils'
import{Plus,Trash2,RefreshCw,Pencil,Loader2}from'lucide-react'

const statusLabels:Record<ProjectStatus,string>={
 draft:'下書き',
 running:'実行中',
 paused:'一時停止',
 completed:'完了',
 failed:'エラー'
}

const statusColors:Record<ProjectStatus,string>={
 draft:'text-nier-text-light',
 running:'text-nier-accent-orange',
 paused:'text-nier-accent-yellow',
 completed:'text-nier-accent-green',
 failed:'text-nier-accent-red'
}

interface ProjectListProps{
 projects:Project[]
 currentProject:Project|null
 isLoading:boolean
 onSelectProject:(project:Project)=>void
 onEditProject:(project:Project)=>void
 onDeleteProject:(projectId:string)=>void
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
 onRefresh,
 onNewProject
}:ProjectListProps){
 return(
  <Card className="flex flex-col overflow-hidden">
   <CardHeader>
    <div className="flex items-center justify-between w-full">
     <DiamondMarker>プロジェクト一覧</DiamondMarker>
     <div className="flex items-center gap-1">
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
      {projects.map((project)=>(
       <div
        key={project.id}
        onClick={()=>onSelectProject(project)}
        className={cn(
         'p-3 border cursor-pointer transition-colors',
         currentProject?.id===project.id
          ?'border-nier-border-light bg-nier-bg-selected'
          :'border-nier-border-light hover:bg-nier-bg-hover'
        )}
       >
        <div className="flex items-start justify-between">
         <div className="flex-1 min-w-0">
          <div className="text-nier-small font-medium truncate">
           {project.name}
          </div>
          <div className="text-nier-caption text-nier-text-light truncate mt-0.5">
           {project.description}
          </div>
         </div>
         <div className="flex items-center gap-2 ml-2">
          <span className={cn('text-nier-caption',statusColors[project.status])}>
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
        </div>
        <div className="text-nier-caption text-nier-text-light mt-1">
         Phase {project.currentPhase}
        </div>
       </div>
      ))}
     </div>
    )}
   </CardContent>
  </Card>
 )
}
