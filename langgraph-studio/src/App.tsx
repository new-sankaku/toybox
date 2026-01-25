import{useEffect,useRef,useCallback}from'react'
import{QueryClient,QueryClientProvider}from'@tanstack/react-query'
import AppLayout from'./components/layout/AppLayout'
import DashboardView from'./components/dashboard/DashboardView'
import{ProjectView,CheckpointsView,InterventionView,AgentsView,LogsView,DataView,CostView,ConfigView}from'./views'
import{useNavigationStore}from'./stores/navigationStore'
import{useProjectStore}from'./stores/projectStore'
import{useAgentStore}from'./stores/agentStore'
import{useCheckpointStore}from'./stores/checkpointStore'
import{useMetricsStore}from'./stores/metricsStore'
import{useLogStore}from'./stores/logStore'
import{useAgentDefinitionStore}from'./stores/agentDefinitionStore'
import{useUIConfigStore}from'./stores/uiConfigStore'
import{useNavigatorStore}from'./stores/navigatorStore'
import{websocketService}from'./services/websocketService'
import{agentApi}from'./services/apiService'
import type{Agent,AgentStatus}from'./types/agent'

const queryClient=new QueryClient({
 defaultOptions:{
  queries:{
   staleTime:1000*60*5,
   retry:1
  }
 }
})

export type{TabId}from'./stores/navigationStore'

const BACKGROUND_POLL_INTERVAL=1000

function App():JSX.Element{
 const{activeTab,setActiveTab}=useNavigationStore()
 const{currentProject,dataVersion}=useProjectStore()
 const{setAgents,reset:resetAgentStore}=useAgentStore()
 const resetCheckpointStore=useCheckpointStore(s=>s.reset)
 const resetMetricsStore=useMetricsStore(s=>s.reset)
 const resetLogStore=useLogStore(s=>s.reset)
 const{fetchDefinitions}=useAgentDefinitionStore()
 const{fetchSettings:fetchUISettings}=useUIConfigStore()
 const{showMessage}=useNavigatorStore()
 const previousProjectIdRef=useRef<string|null>(null)
 const previousDataVersionRef=useRef<number>(dataVersion)
 const previousProjectStatusRef=useRef<string|null>(null)
 const hasShownWelcomeRef=useRef(false)
 const pollIntervalRef=useRef<number|null>(null)

 const fetchAgentsForProject=useCallback(async(projectId:string)=>{
  try{
   const agentsData=await agentApi.listByProject(projectId)
   const agentsConverted:Agent[]=agentsData.map(a=>({
    id:a.id,
    projectId:a.projectId,
    type:a.type as Agent['type'],
    phase:a.phase as Agent['phase'],
    status:a.status as AgentStatus,
    progress:a.progress,
    currentTask:a.currentTask,
    tokensUsed:a.tokensUsed,
    startedAt:a.startedAt,
    completedAt:a.completedAt,
    error:a.error,
    parentAgentId:a.parentAgentId,
    metadata:a.metadata,
    createdAt:a.createdAt
   }))
   setAgents(agentsConverted)
  }catch(error){
   console.error('[App] Background poll failed:',error)
  }
 },[setAgents])

 useEffect(()=>{
  const handleVisibilityChange=()=>{
   const projectId=currentProject?.id
   if(document.hidden&&projectId){
    if(!pollIntervalRef.current){
     console.log('[App] Starting background polling')
     pollIntervalRef.current=window.setInterval(()=>{
      fetchAgentsForProject(projectId)
     },BACKGROUND_POLL_INTERVAL)
    }
   }else{
    if(pollIntervalRef.current){
     console.log('[App] Stopping background polling')
     clearInterval(pollIntervalRef.current)
     pollIntervalRef.current=null
    }
   }
  }

  document.addEventListener('visibilitychange',handleVisibilityChange)
  return()=>{
   document.removeEventListener('visibilitychange',handleVisibilityChange)
   if(pollIntervalRef.current){
    clearInterval(pollIntervalRef.current)
    pollIntervalRef.current=null
   }
  }
 },[currentProject?.id,fetchAgentsForProject])

 useEffect(()=>{
  const backendUrl=(import.meta as unknown as{env:Record<string,string>}).env.VITE_BACKEND_URL||'http://localhost:5000'
  websocketService.connect(backendUrl)

  fetchDefinitions()
  fetchUISettings()

  if(!hasShownWelcomeRef.current){
   hasShownWelcomeRef.current=true
   setTimeout(()=>{
    showMessage('オペレーター','システム起動完了。LangGraph Studio へようこそ。プロジェクトを選択して作業を開始してください。')
   },500)
  }

  return()=>{
   websocketService.disconnect()
  }
 },[fetchDefinitions,fetchUISettings,showMessage])

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

   if(previousProjectIdRef.current!==projectId){
    showMessage('オペレーター',`プロジェクト「${projectName}」を選択しました。ダッシュボードで進捗を確認できます。`)
   }
  }

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

 useEffect(()=>{
  if(previousDataVersionRef.current!==dataVersion){
   resetAgentStore()
   resetCheckpointStore()
   resetMetricsStore()
   resetLogStore()
   previousDataVersionRef.current=dataVersion
  }
 },[dataVersion,resetAgentStore,resetCheckpointStore,resetMetricsStore,resetLogStore])

 const renderOtherContent=()=>{
  switch(activeTab){
   case'project':
    return<ProjectView/>
   case'checkpoints':
    return<CheckpointsView/>
   case'intervention':
    return<InterventionView/>
   case'agents':
    return<AgentsView/>
   case'logs':
    return<LogsView/>
   case'data':
    return<DataView/>
   case'cost':
    return<CostView/>
   case'config':
    return<ConfigView/>
   default:
    return null
  }
 }

 const dataKey=`${currentProject?.id||'none'}-${dataVersion}`

 return(
  <QueryClientProvider client={queryClient}>
   <AppLayout activeTab={activeTab} onTabChange={setActiveTab}>
    {/*DASHBOARDは常にマウント、非表示時はdisplay:noneで隠す*/}
    {/*key変更でコンポーネント再マウント→データ再取得*/}
    <div key={`dashboard-${dataKey}`} style={{display:activeTab==='system'?'block':'none'}}>
     <DashboardView/>
    </div>
    {activeTab!=='system'&&<div key={`content-${dataKey}`} className="h-full">{renderOtherContent()}</div>}
   </AppLayout>
  </QueryClientProvider>
)
}

export default App
