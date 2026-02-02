import type{Project,ProjectStatus}from'@/types/project'
import{cn}from'@/lib/utils'

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

interface ProjectDetailProps{
 project:Project
}

export function ProjectDetail({project}:ProjectDetailProps){
 return(
  <div className="space-y-4">
   <div>
    <span className="text-nier-caption text-nier-text-light block">名前</span>
    <span className="text-nier-h2 font-medium">{project.name}</span>
   </div>
   <div>
    <span className="text-nier-caption text-nier-text-light block">ステータス</span>
    <span className={cn('text-nier-body',statusColors[project.status])}>
     {statusLabels[project.status]}
    </span>
   </div>
   <div>
    <span className="text-nier-caption text-nier-text-light block">現在のフェーズ</span>
    <span className="text-nier-body">Phase {project.currentPhase}</span>
   </div>
   {project.concept&&(
    <>
     <div>
      <span className="text-nier-caption text-nier-text-light block">ゲームアイデア</span>
      <span className="text-nier-body">{project.concept.description}</span>
     </div>
     <div className="grid grid-cols-3 gap-4">
      <div>
       <span className="text-nier-caption text-nier-text-light block">プラットフォーム</span>
       <span className="text-nier-body">{project.concept.platform}</span>
      </div>
      <div>
       <span className="text-nier-caption text-nier-text-light block">スコープ</span>
       <span className="text-nier-body">{project.concept.scope}</span>
      </div>
      {project.concept.genre&&(
       <div>
        <span className="text-nier-caption text-nier-text-light block">ジャンル</span>
        <span className="text-nier-body">{project.concept.genre}</span>
       </div>
)}
     </div>
    </>
)}
   <div>
    <span className="text-nier-caption text-nier-text-light block">作成日時</span>
    <span className="text-nier-body">
     {new Date(project.createdAt).toLocaleString('ja-JP')}
    </span>
   </div>
  </div>
)
}
