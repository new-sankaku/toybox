import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import type{Project}from'@/types/project'
import{Play,Pause,Square,RotateCcw,RefreshCw,Loader2}from'lucide-react'

interface ProjectControlsProps{
 project:Project
 isLoading:boolean
 onStart:()=>void
 onResume:()=>void
 onPause:()=>void
 onStop:()=>void
 onBrushup:()=>void
 onInitialize:()=>void
}

export function ProjectControls({
 project,
 isLoading,
 onStart,
 onResume,
 onPause,
 onStop,
 onBrushup,
 onInitialize
}:ProjectControlsProps){
 const canInitialize=project.status!=='draft'||project.currentPhase>1
 const canBrushup=project.status==='completed'

 return(
  <Card>
   <CardHeader>
    <DiamondMarker>実行コントロール</DiamondMarker>
   </CardHeader>
   <CardContent>
    <div className="flex gap-3">
     {project.status==='draft'&&(
      <Button variant="primary" size="lg" onClick={onStart} disabled={isLoading}>
       {isLoading?<Loader2 size={16} className="mr-2 animate-spin"/>:<Play size={16} className="mr-2"/>}
       開始
      </Button>
)}
     {project.status==='paused'&&(
      <Button onClick={onResume} disabled={isLoading}>
       {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:<Play size={14} className="mr-1.5"/>}
       再開
      </Button>
)}
     {project.status==='running'&&(
      <Button onClick={onPause} disabled={isLoading}>
       {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:<Pause size={14} className="mr-1.5"/>}
       一時停止
      </Button>
)}
     {(project.status==='running'||project.status==='paused')&&(
      <Button variant="secondary" onClick={onStop} disabled={isLoading}>
       <Square size={14} className="mr-1.5"/>
       停止
      </Button>
)}
     {canBrushup&&(
      <Button onClick={onBrushup}>
       <RefreshCw size={14} className="mr-1.5"/>
       ブラッシュアップ
      </Button>
)}
     {canInitialize&&(
      <Button variant="danger" onClick={onInitialize}>
       <RotateCcw size={14} className="mr-1.5"/>
       初期化
      </Button>
)}
    </div>
   </CardContent>
  </Card>
)
}
