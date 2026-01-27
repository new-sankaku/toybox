import{useState,useEffect,useCallback}from'react'
import{AgentListView}from'@/components/agents'
import{AgentSlideOver}from'@/components/agents/AgentSlideOver'
import{Card,CardContent}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{useAgentStore}from'@/stores/agentStore'
import{agentApi,type ApiAgent,type ApiAgentLog}from'@/services/apiService'
import type{Agent,AgentLogEntry,AgentType,AgentStatus}from'@/types/agent'
import{FolderOpen}from'lucide-react'

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
 const[selectedAgent,setSelectedAgent]=useState<Agent|null>(null)
 const[initialLoading,setInitialLoading]=useState(true)
 const[initialLogsFetched,setInitialLogsFetched]=useState<Record<string,boolean>>({})

 useEffect(()=>{
  setSelectedAgent(null)
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
  if(!selectedAgent)return
  if(initialLogsFetched[selectedAgent.id])return

  const fetchLogs=async()=>{
   try{
    const data=await agentApi.getLogs(selectedAgent.id)
    const logs=data.map(convertApiLog)
    const{addLogEntry}=useAgentStore.getState()
    logs.forEach(log=>addLogEntry(selectedAgent.id,log))
    setInitialLogsFetched(prev=>({...prev,[selectedAgent.id]:true}))
   }catch(error){
    console.error('Failed to fetch agent logs:',error)
   }
  }

  fetchLogs()
 },[selectedAgent?.id,initialLogsFetched])

 const selectedAgentLogs=selectedAgent
  ?(agentLogs[selectedAgent.id]||[])
   .slice()
   .sort((a,b)=>new Date(b.timestamp).getTime()-new Date(a.timestamp).getTime())
  : []

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

 const handleSelectAgent=(agent:Agent)=>{
  setSelectedAgent(prev=>prev?.id===agent.id?null:agent)
 }

 const handleCloseSlideOver=()=>{
  setSelectedAgent(null)
 }

 const handleRetry=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.retry(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
    if(selectedAgent?.id===agent.id){
     setSelectedAgent(updatedAgent)
    }
   }
  }catch(error){
   console.error('Failed to retry agent:',error)
  }
 },[selectedAgent,setAgents])

 const handlePause=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.pause(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
    if(selectedAgent?.id===agent.id){
     setSelectedAgent(updatedAgent)
    }
   }
  }catch(error){
   console.error('Failed to pause agent:',error)
  }
 },[selectedAgent,setAgents])

 const handleResume=useCallback(async(agent:Agent)=>{
  try{
   const result=await agentApi.resume(agent.id)
   if(result.success){
    const updatedAgent=convertApiAgent(result.agent)
    const currentAgents=useAgentStore.getState().agents
    const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
    setAgents(newAgents)
    if(selectedAgent?.id===agent.id){
     setSelectedAgent(updatedAgent)
    }
   }
  }catch(error){
   console.error('Failed to resume agent:',error)
  }
 },[selectedAgent,setAgents])

 const currentAgentData=selectedAgent
  ?projectAgents.find(a=>a.id===selectedAgent.id)||selectedAgent
  :null
 const canRetry=currentAgentData?['failed','interrupted','cancelled'].includes(currentAgentData.status):false
 const canPause=currentAgentData?['running','waiting_approval'].includes(currentAgentData.status):false
 const canResume=currentAgentData?['paused','waiting_response'].includes(currentAgentData.status):false

 return(
  <>
   <AgentListView
    agents={projectAgents}
    onSelectAgent={handleSelectAgent}
    selectedAgentId={selectedAgent?.id}
    loading={initialLoading||isLoading}
    onRetryAgent={handleRetry}
   />
   <AgentSlideOver
    agent={currentAgentData}
    logs={selectedAgentLogs}
    onClose={handleCloseSlideOver}
    onRetry={canRetry&&currentAgentData?()=>handleRetry(currentAgentData):undefined}
    onPause={canPause&&currentAgentData?()=>handlePause(currentAgentData):undefined}
    onResume={canResume&&currentAgentData?()=>handleResume(currentAgentData):undefined}
   />
  </>
)
}
