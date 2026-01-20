import{useProjectStore}from'@/stores/projectStore'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'

const phaseLabels:Record<number,string> = {
 1:'Phase 1 - Planning',
 2:'Phase 2 - Development',
 3:'Phase 3 - Quality'
}

export default function ProjectStatus():JSX.Element{
 const{currentProject} = useProjectStore()

 const getRuntime = () => {
  if(!currentProject)return'00:00:00'
  const created = new Date(currentProject.createdAt).getTime()
  const now = Date.now()
  const seconds = Math.floor((now - created) / 1000)
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const secs = seconds % 60
  return`${hours.toString().padStart(2,'0')}:${minutes.toString().padStart(2,'0')}:${secs.toString().padStart(2,'0')}`
 }

 if(!currentProject){
  return(
   <Card>
    <CardHeader>
     <DiamondMarker>プロジェクト</DiamondMarker>
    </CardHeader>
    <CardContent>
     <div className="text-nier-text-light text-center py-4">
      プロジェクトが選択されていません
     </div>
    </CardContent>
   </Card>
  )
 }

 return(
  <Card>
   <CardHeader>
    <DiamondMarker>プロジェクト</DiamondMarker>
   </CardHeader>
   <CardContent>
    <div className="space-y-3">
     <div className="text-nier-h2 font-medium tracking-nier">
      {currentProject.name}
     </div>
     <div className="text-nier-text-light">
      {phaseLabels[currentProject.currentPhase] || `Phase ${currentProject.currentPhase}`}
     </div>
     <div className="flex items-center gap-2 text-nier-small text-nier-text-light">
      <span>実行時間:</span>
      <span className="font-medium text-nier-text-main">
       {getRuntime()}
      </span>
     </div>
    </div>
   </CardContent>
  </Card>
 )
}
