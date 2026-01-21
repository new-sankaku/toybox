import{useEffect,useRef}from'react'
import{QueryClient,QueryClientProvider}from'@tanstack/react-query'
import AppLayout from'./components/layout/AppLayout'
import DashboardView from'./components/dashboard/DashboardView'
import{ProjectView,CheckpointsView,InterventionView,AgentsView,LogsView,DataView,AIView,CostView,ConfigView}from'./views'
import{useNavigationStore}from'./stores/navigationStore'
import{useProjectStore}from'./stores/projectStore'
import{useAgentDefinitionStore}from'./stores/agentDefinitionStore'
import{useNavigatorStore}from'./stores/navigatorStore'
import{websocketService}from'./services/websocketService'

const queryClient=new QueryClient({
 defaultOptions:{
  queries:{
   staleTime:1000*60*5,
   retry:1
  }
 }
})

export type{TabId}from'./stores/navigationStore'

function App():JSX.Element{
 const{activeTab,setActiveTab}=useNavigationStore()
 const{currentProject}=useProjectStore()
 const{fetchDefinitions}=useAgentDefinitionStore()
 const{showMessage}=useNavigatorStore()
 const previousProjectIdRef=useRef<string|null>(null)
 const previousProjectStatusRef=useRef<string|null>(null)
 const hasShownWelcomeRef=useRef(false)

 useEffect(()=>{
  const backendUrl=import.meta.env.VITE_BACKEND_URL||'http://localhost:5000'
  websocketService.connect(backendUrl)

  fetchDefinitions()

  // Show welcome message on app startup
  if(!hasShownWelcomeRef.current){
   hasShownWelcomeRef.current=true
   setTimeout(()=>{
    showMessage('オペレーター','システム起動完了。LangGraph Studio へようこそ。プロジェクトを選択して作業を開始してください。')
   },500)
  }

  return()=>{
   websocketService.disconnect()
  }
 },[fetchDefinitions,showMessage])

 useEffect(()=>{
  const projectId=currentProject?.id ?? null
  const projectStatus=currentProject?.status ?? null
  const projectName=currentProject?.name ?? ''

  if(previousProjectIdRef.current&&previousProjectIdRef.current!==projectId){
   websocketService.unsubscribeFromProject(previousProjectIdRef.current)
  }

  if(projectId){
   console.log('[App] Requesting WebSocket subscription for project:',projectId)
   websocketService.subscribeToProject(projectId)

   // Show message when project is selected (different project)
   if(previousProjectIdRef.current!==projectId){
    showMessage('オペレーター',`プロジェクト「${projectName}」を選択しました。ダッシュボードで進捗を確認できます。`)
   }
  }

  // Show message on project status change
  if(previousProjectStatusRef.current&&previousProjectStatusRef.current!==projectStatus&&projectStatus){
   const statusMessages:Record<string,string>={
    running:`プロジェクト「${projectName}」が開始されました。エージェントが稼働を開始します。`,
    paused:`プロジェクト「${projectName}」が一時停止されました。`,
    completed:`プロジェクト「${projectName}」が完了しました。お疲れ様でした。`,
    failed:`警告：プロジェクト「${projectName}」でエラーが発生しました。ログを確認してください。`
   }
   if(statusMessages[projectStatus]){
    showMessage('オペレーター',statusMessages[projectStatus])
   }
  }

  previousProjectIdRef.current=projectId
  previousProjectStatusRef.current=projectStatus
 },[currentProject?.id,currentProject?.status,currentProject?.name,showMessage])

 const renderContent=()=>{
  switch(activeTab){
   case'project':
    return<ProjectView/>
   case'checkpoints':
    return<CheckpointsView/>
   case'intervention':
    return<InterventionView/>
   case'system':
    return<DashboardView/>
   case'agents':
    return<AgentsView/>
   case'logs':
    return<LogsView/>
   case'data':
    return<DataView/>
   case'ai':
    return<AIView/>
   case'cost':
    return<CostView/>
   case'config':
    return<ConfigView/>
   default:
    return<DashboardView/>
  }
 }

 return(
  <QueryClientProvider client={queryClient}>
   <AppLayout activeTab={activeTab} onTabChange={setActiveTab}>
    {renderContent()}
   </AppLayout>
  </QueryClientProvider>
)
}

export default App
