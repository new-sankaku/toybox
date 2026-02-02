import{useState,useEffect,useCallback}from'react'
import{AgentListView}from'@/components/agents'
import{Card,CardContent}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{useAgentStore}from'@/stores/agentStore'
import{agentApi}from'@/services/apiService'
import{convertApiAgent,convertApiAgents,convertApiLogs}from'@/services/converters/agentConverter'
import type{Agent}from'@/types/agent'
import{FolderOpen}from'lucide-react'
import{useToastStore}from'@/stores/toastStore'

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
 },[tabResetCounter])

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
    setAgents(convertApiAgents(data))
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
    const logs=convertApiLogs(data)
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
    addToast('success','エージェントを実行しました')
   }
  }catch(error:unknown){
   const axiosErr=error as{response?:{status:number}}
   if(axiosErr.response?.status===429){
    addToast('error','レート制限に達しました。しばらくお待ちください。')
   }else{
    console.error('Failed to execute agent:',error)
    addToast('error','エージェントの実行に失敗しました')
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
    addToast('success','エージェント（Workers含む）を実行しました')
   }
  }catch(error:unknown){
   const axiosErr=error as{response?:{status:number}}
   if(axiosErr.response?.status===429){
    addToast('error','レート制限に達しました。しばらくお待ちください。')
   }else{
    console.error('Failed to execute agent with workers:',error)
    addToast('error','エージェントの実行に失敗しました')
   }
  }
 },[setAgents,addToast])

 const handleRetryAll=useCallback(async()=>{
  const retryableAgents=projectAgents.filter(a=>['failed','interrupted'].includes(a.status))
  if(retryableAgents.length===0)return 0
  let retriedCount=0
  for(const agent of retryableAgents){
   try{
    const result=await agentApi.retry(agent.id)
    if(result.success){
     retriedCount++
     const updatedAgent=convertApiAgent(result.agent)
     const currentAgents=useAgentStore.getState().agents
     const newAgents=currentAgents.map(a=>a.id===updatedAgent.id?updatedAgent:a)
     setAgents(newAgents)
    }
   }catch(error){
    console.error('Failed to retry agent:',error)
   }
  }
  if(retriedCount>0){
   addToast('success',`${retriedCount}件のエージェントを再起動しました`)
  }
  return retriedCount
 },[projectAgents,setAgents,addToast])

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
   onRetryAll={handleRetryAll}
   agentLogsMap={agentLogs}
  />
)
}
