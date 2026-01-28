import{useState,useEffect,useCallback}from'react'
import{AgentListView}from'@/components/agents'
import{Card,CardContent}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{useAgentStore}from'@/stores/agentStore'
import{agentApi,type ApiAgent,type ApiAgentLog}from'@/services/apiService'
import type{Agent,AgentLogEntry,AgentType,AgentStatus}from'@/types/agent'
import{FolderOpen}from'lucide-react'
import{useToastStore}from'@/stores/toastStore'

function convertApiAgent(apiAgent:ApiAgent):Agent{
 return{
  id:apiAgent.id,
  projectId:apiAgent.projectId,
  type:apiAgent.type as AgentType,
  status:apiAgent.status as AgentStatus,
  progress:apiAgent.progress,
  currentTask:apiAgent.currentTask,
  tokensUsed:apiAgent.tokensUsed,
  startedAt:apiAgent.startedAt,
  completedAt:apiAgent.completedAt,
  error:apiAgent.error,
  parentAgentId:apiAgent.parentAgentId,
  metadata:apiAgent.metadata,
  createdAt:apiAgent.createdAt,
  phase:apiAgent.phase as Agent['phase']
 }
}

function convertApiLog(apiLog:ApiAgentLog):AgentLogEntry{
 return{
  id:apiLog.id,
  timestamp:apiLog.timestamp,
  level:apiLog.level,
  message:apiLog.message,
  progress:apiLog.progress||undefined,
  metadata:apiLog.metadata,
 }
}

export default function AgentsView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{tabResetCounter}=useNavigationStore()
 const{agents,setAgents,agentLogs,isLoading,version}=useAgentStore()
 const addToast=useToastStore(s=>s.addToast)
 const[openAgentIds,setOpenAgentIds]=useState<Set<string>>(new Set())
 const[initialLoading,setInitialLoading]=useState(true)
 const[initialLogsFetched,setInitialLogsFetched]=useState<Record<string,boolean>>({})

 useEffect(()=>{
  setOpenAgentIds(new Set())
  setInitialLogsFetched({})
 },[tabResetCounter,version])

 useEffect(()=>{
  if(!currentProject){
   setAgents([])
   setInitialLoading(false)
   return
  }

  const fetchAgents=async()=>{
   setInitialLoading(true)
   try{
    const data=await agentApi.listByProject(currentProject.id)
    setAgents(data.map(convertApiAgent))
   }catch(error){
    console.error('Failed to fetch agents:',error)
   }finally{
    setInitialLoading(false)
   }
  }

  fetchAgents()
 },[currentProject?.id,setAgents,version])

 useEffect(()=>{
  if(openAgentIds.size===0)return
  const idsToFetch=[...openAgentIds].filter(id=>!initialLogsFetched[id])
  if(idsToFetch.length===0)return

  const fetchLogs=async(agentId:string)=>{
   try{
    const data=await agentApi.getLogs(agentId)
    const logs=data.map(convertApiLog)
    const{addLogEntry}=useAgentStore.getState()
    logs.forEach(log=>addLogEntry(agentId,log))
    setInitialLogsFetched(prev=>({...prev,[agentId]:true}))
   }catch(error){
    console.error('Failed to fetch agent logs:',error)
   }
  }

  idsToFetch.forEach(id=>fetchLogs(id))
 },[openAgentIds,initialLogsFetched])

 const projectAgents=currentProject
  ?agents.filter(a=>a.projectId===currentProject.id)
  : []

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <Card>
     <CardContent>
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
       <p className="text-nier-body">プロジェクトを選択してください</p>
      </div>
     </CardContent>
    </Card>
   </div>
)
 }

 const handleToggleAgent=(agent:Agent)=>{
  setOpenAgentIds(prev=>{
   const next=new Set(prev)
   if(next.has(agent.id))next.delete(agent.id)
   else next.add(agent.id)
   return next
  })
 }

 const handleRetry=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.retry(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
   }
  }catch(error){
   console.error('Failed to retry agent:',error)
  }
 },[setAgents])

 const handlePause=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.pause(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
   }
  }catch(error){
   console.error('Failed to pause agent:',error)
  }
 },[setAgents])

 const handleResume=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.resume(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
   }
  }catch(error){
   console.error('Failed to resume agent:',error)
  }
 },[setAgents])

 const handleExecute=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.execute(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
    addToast('エージェントを実行しました','success')
   }
  }catch(error:unknown){
   const axiosErr=error as{response?:{status:number}}
   if(axiosErr.response?.status===429){
    addToast('レート制限に達しました。しばらくお待ちください。','error')
   }else{
    console.error('Failed to execute agent:',error)
    addToast('エージェントの実行に失敗しました','error')
   }
  }
 },[setAgents,addToast])

 const handleExecuteWithWorkers=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.executeWithWorkers(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
    addToast('エージェント（Workers含む）を実行しました','success')
   }
  }catch(error:unknown){
   const axiosErr=error as{response?:{status:number}}
   if(axiosErr.response?.status===429){
    addToast('レート制限に達しました。しばらくお待ちください。','error')
   }else{
    console.error('Failed to execute agent with workers:',error)
    addToast('エージェントの実行に失敗しました','error')
   }
  }
 },[setAgents,addToast])

 return(
  <AgentListView
   agents={projectAgents}
   onToggleAgent={handleToggleAgent}
   openAgentIds={openAgentIds}
   loading={initialLoading||isLoading}
   onRetryAgent={handleRetry}
   onPauseAgent={handlePause}
   onResumeAgent={handleResume}
   onExecuteAgent={handleExecute}
   onExecuteWithWorkers={handleExecuteWithWorkers}
   agentLogsMap={agentLogs}
  />
)
}
