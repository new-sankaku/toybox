import{useState,useEffect}from'react'
import{CheckpointListView}from'@/components/checkpoints'
import CheckpointReviewView from'@/components/checkpoints/CheckpointReviewView'
import{Card,CardContent}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{useCheckpointStore}from'@/stores/checkpointStore'
import{checkpointApi,type ApiCheckpoint}from'@/services/apiService'
import type{Checkpoint,CheckpointType,CheckpointStatus}from'@/types/checkpoint'
import{FolderOpen}from'lucide-react'

function convertApiCheckpoint(apiCheckpoint:ApiCheckpoint):Checkpoint{
 return{
  id:apiCheckpoint.id,
  projectId:apiCheckpoint.projectId,
  agentId:apiCheckpoint.agentId,
  type:apiCheckpoint.type as CheckpointType,
  title:apiCheckpoint.title,
  description:apiCheckpoint.description || null,
  output:{
   documentType:apiCheckpoint.output?.format || 'markdown',
   content:apiCheckpoint.output?.content
    ? (typeof apiCheckpoint.output.content === 'string'
     ? {text:apiCheckpoint.output.content}
     : apiCheckpoint.output.content as Record<string,unknown>)
    : undefined,
   summary:typeof apiCheckpoint.output?.content === 'string'
    ? apiCheckpoint.output.content
    : undefined,
  },
  status:apiCheckpoint.status as CheckpointStatus,
  feedback:apiCheckpoint.feedback,
  resolvedAt:apiCheckpoint.resolvedAt,
  createdAt:apiCheckpoint.createdAt,
  updatedAt:apiCheckpoint.updatedAt,
 }
}

export default function CheckpointsView():JSX.Element{
 const{currentProject} = useProjectStore()
 const{tabResetCounter,pendingCheckpointId,clearPendingCheckpoint} = useNavigationStore()
 const{checkpoints,setCheckpoints,isLoading} = useCheckpointStore()
 const[selectedCheckpoint,setSelectedCheckpoint] = useState<Checkpoint | null>(null)
 const[initialLoading,setInitialLoading] = useState(true)

 useEffect(() => {
  if(!pendingCheckpointId){
   setSelectedCheckpoint(null)
  }
 },[tabResetCounter,pendingCheckpointId])

 const projectCheckpoints = currentProject
  ? checkpoints.filter(cp => cp.projectId === currentProject.id)
  : []

 useEffect(() => {
  if(pendingCheckpointId && projectCheckpoints.length > 0){
   const checkpoint = projectCheckpoints.find(cp => cp.id === pendingCheckpointId)
   if(checkpoint){
    setSelectedCheckpoint(checkpoint)
    clearPendingCheckpoint()
   }
  }
 },[pendingCheckpointId,projectCheckpoints,clearPendingCheckpoint])

 useEffect(() => {
  if(!currentProject){
   setCheckpoints([])
   setInitialLoading(false)
   return
  }

  const fetchCheckpoints = async() => {
   setInitialLoading(true)
   try{
    const data = await checkpointApi.listByProject(currentProject.id)
    setCheckpoints(data.map(convertApiCheckpoint))
   }catch(error){
    console.error('Failed to fetch checkpoints:',error)
   }finally{
    setInitialLoading(false)
   }
  }

  fetchCheckpoints()
 },[currentProject?.id,setCheckpoints])

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <div className="nier-page-header-row">
     <div className="nier-page-header-left">
      <h1 className="nier-page-title">CHECKPOINTS</h1>
      <span className="nier-page-subtitle">- レビュー待ち</span>
     </div>
     <div className="nier-page-header-right" />
    </div>
    <Card>
     <CardContent>
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={48} className="mx-auto mb-4 opacity-50" />
       <p className="text-nier-body">プロジェクトを選択してください</p>
      </div>
     </CardContent>
    </Card>
   </div>
  )
 }

 const handleSelectCheckpoint = (checkpoint:Checkpoint) => {
  setSelectedCheckpoint(checkpoint)
 }

 const selectNextPending = (updatedCheckpoints:Checkpoint[],currentId:string) => {
  const pendingCheckpoints = updatedCheckpoints.filter(
   cp => cp.status === 'pending' && cp.id !== currentId
  )
  if(pendingCheckpoints.length > 0){
   const nextPending = pendingCheckpoints.reduce((oldest,current) =>
    new Date(oldest.createdAt) < new Date(current.createdAt) ? oldest : current
   )
   setSelectedCheckpoint(nextPending)
  }else{
   setSelectedCheckpoint(null)
  }
 }

 const handleApprove = async() => {
  if(!selectedCheckpoint)return
  const currentId = selectedCheckpoint.id
  try{
   await checkpointApi.resolve(selectedCheckpoint.id,'approved')
   const data = await checkpointApi.listByProject(currentProject.id)
   const updatedCheckpoints = data.map(convertApiCheckpoint)
   setCheckpoints(updatedCheckpoints)
   selectNextPending(updatedCheckpoints,currentId)
  }catch(error){
   console.error('Failed to approve checkpoint:',error)
  }
 }

 const handleReject = async(reason:string) => {
  if(!selectedCheckpoint)return
  const currentId = selectedCheckpoint.id
  try{
   await checkpointApi.resolve(selectedCheckpoint.id,'rejected',reason)
   const data = await checkpointApi.listByProject(currentProject.id)
   const updatedCheckpoints = data.map(convertApiCheckpoint)
   setCheckpoints(updatedCheckpoints)
   selectNextPending(updatedCheckpoints,currentId)
  }catch(error){
   console.error('Failed to reject checkpoint:',error)
  }
 }

 const handleRequestChanges = async(feedback:string) => {
  if(!selectedCheckpoint)return
  const currentId = selectedCheckpoint.id
  try{
   await checkpointApi.resolve(selectedCheckpoint.id,'revision_requested',feedback)
   const data = await checkpointApi.listByProject(currentProject.id)
   const updatedCheckpoints = data.map(convertApiCheckpoint)
   setCheckpoints(updatedCheckpoints)
   selectNextPending(updatedCheckpoints,currentId)
  }catch(error){
   console.error('Failed to request changes:',error)
  }
 }

 const handleClose = () => {
  setSelectedCheckpoint(null)
 }

 if(selectedCheckpoint){
  const currentCheckpointData = projectCheckpoints.find(cp => cp.id === selectedCheckpoint.id) || selectedCheckpoint
  return(
   <CheckpointReviewView
    checkpoint={currentCheckpointData}
    onApprove={handleApprove}
    onReject={handleReject}
    onRequestChanges={handleRequestChanges}
    onClose={handleClose}
   />
  )
 }

 return(
  <CheckpointListView
   checkpoints={projectCheckpoints}
   onSelectCheckpoint={handleSelectCheckpoint}
   selectedCheckpointId={undefined}
   loading={initialLoading || isLoading}
  />
 )
}
