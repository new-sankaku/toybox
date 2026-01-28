import{io,Socket}from'socket.io-client'
import{useConnectionStore}from'@/stores/connectionStore'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentStore}from'@/stores/agentStore'
import{useCheckpointStore}from'@/stores/checkpointStore'
import{useAssetStore}from'@/stores/assetStore'
import{useMetricsStore}from'@/stores/metricsStore'
import{useNavigatorStore,type MessagePriority}from'@/stores/navigatorStore'
import{useToastStore}from'@/stores/toastStore'
import{useActivityFeedStore}from'@/stores/activityFeedStore'
import{useSpeechStore}from'@/stores/speechStore'
import type{Agent,AgentLogEntry}from'@/types/agent'
import type{Checkpoint}from'@/types/checkpoint'
import type{Project,ProjectMetrics,PhaseNumber}from'@/types/project'
import type{ApiAsset}from'@/services/apiService'

function getAgentDisplayName(agent?:Agent):string{
 if(!agent)return'不明なエージェント'
 return(agent.metadata?.displayName as string)||agent.type
}

interface ServerToClientEvents{
 connect:()=>void
 disconnect:()=>void
 error:(error:Error)=>void
 'connection:state_sync':(data:{
  status?:string
  sid?:string
  project?:Project
  agents?:Agent[]
  checkpoints?:Checkpoint[]
  metrics?:ProjectMetrics
 })=>void
 'agent:started':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'agent:created':(data:{agent:Agent;agentId:string;projectId:string;parentAgentId?:string})=>void
 'agent:running':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'agent:progress':(data:{agentId:string;projectId:string;progress:number;currentTask:string;tokensUsed:number;message:string})=>void
 'agent:log':(data:{agentId:string;entry:AgentLogEntry})=>void
 'agent:completed':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'agent:failed':(data:{agentId:string;projectId?:string;agent?:Agent;error:string})=>void
 'agent:waiting_provider':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'agent:paused':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'agent:resumed':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'agent:activated':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'agent:waiting_response':(data:{agent:Agent;agentId:string;projectId:string})=>void
 'checkpoint:created':(data:{checkpoint:Checkpoint;checkpointId:string;projectId:string;agentId:string;agentStatus?:string})=>void
 'checkpoint:resolved':(data:{checkpoint:Checkpoint;checkpointId?:string;agentId?:string;agentStatus?:string})=>void
 'asset:created':(data:{projectId:string;asset:ApiAsset;autoApproved?:boolean})=>void
 'asset:updated':(data:{projectId:string;asset:ApiAsset;autoApproved?:boolean})=>void
 'project:updated':(data:{projectId:string;updates:Partial<Project>})=>void
 'phase:changed':(data:{projectId:string;phase:PhaseNumber;phaseName:string})=>void
 'metrics:update':(data:{projectId:string;metrics:ProjectMetrics})=>void
 'navigator:message':(data:{speaker:string;text:string;priority:MessagePriority;source:'server'})=>void
 'agent:speech':(data:{agentId:string;projectId:string;message:string;source:'llm'|'pool';timestamp:string})=>void
}

interface ClientToServerEvents{
 'subscribe:project':(projectId:string)=>void
 'unsubscribe:project':(projectId:string)=>void
 'checkpoint:resolve':(data:{checkpointId:string;resolution:string;feedback?:string})=>void
}

type TypedSocket=Socket<ServerToClientEvents,ClientToServerEvents>

export interface WebSocketConfig{
 maxReconnectAttempts?:number
 reconnectDelay?:number
 reconnectDelayMax?:number
 timeout?:number
}

class WebSocketService{
 private socket:TypedSocket|null=null
 private config:Required<WebSocketConfig>={
  maxReconnectAttempts:5,
  reconnectDelay:1000,
  reconnectDelayMax:5000,
  timeout:10000
 }
 private pendingProjectId:string|null=null
 private currentProjectId:string|null=null

 connect(backendUrl:string,config?:WebSocketConfig):void{
  if(this.socket?.connected){
   console.log('[WS] Already connected')
   return
  }

  if(config){
   this.config={...this.config,...config}
  }

  const connectionStore=useConnectionStore.getState()
  connectionStore.setStatus('connecting')

  console.log('[WS] Connecting to:',backendUrl)

  this.socket=io(backendUrl,{
   transports:['websocket','polling'],
   reconnection:true,
   reconnectionAttempts:this.config.maxReconnectAttempts,
   reconnectionDelay:this.config.reconnectDelay,
   reconnectionDelayMax:this.config.reconnectDelayMax,
   timeout:this.config.timeout
  })

  this.setupEventHandlers()
 }

 private setupEventHandlers():void{
  if(!this.socket)return

  this.socket.on('connect',()=>{
   console.log('[WS] Connected! Socket ID:',this.socket?.id)
   const connectionStore=useConnectionStore.getState()
   connectionStore.setStatus('connected')
   connectionStore.setError(null)
   connectionStore.resetReconnect()

   if(this.pendingProjectId){
    console.log('[WS] Auto-subscribing to pending project:',this.pendingProjectId)
    this.doSubscribe(this.pendingProjectId)
   }
  })

  this.socket.on('disconnect',(reason)=>{
   console.log('[WS] Disconnected. Reason:',reason)
   useConnectionStore.getState().setStatus('disconnected')
   this.currentProjectId=null
  })

  this.socket.on('error'as keyof ServerToClientEvents,((error:Error)=>{
   console.error('[WS] Error:',error)
   useConnectionStore.getState().setError(error.message)
  })as()=>void)

  this.socket.on('connection:state_sync',(data)=>{
   console.log('[WS] State sync received:',{
    hasAgents:data.agents?.length||0,
    hasCheckpoints:data.checkpoints?.length||0,
    hasMetrics:!!data.metrics,
    status:data.status
   })

   if(data.agents&&data.agents.length>0){
    console.log('[WS] Setting agents from state sync:',data.agents.length)
    useAgentStore.getState().setAgents(data.agents)
   }
   if(data.checkpoints&&data.checkpoints.length>0){
    const checkpointStore=useCheckpointStore.getState()
    data.checkpoints.forEach(cp=>checkpointStore.addCheckpoint(cp))
   }
   if(data.metrics){
    useMetricsStore.getState().setProjectMetrics(data.metrics)
   }
  })

  this.socket.on('agent:started',(data)=>{
   console.log('[WS] Agent started:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.addAgent(data.agent)
    agentStore.updateAgentStatus(data.agent.id,'running')
   }
   const name=getAgentDisplayName(data.agent)
   useActivityFeedStore.getState().addEvent('agent_started',name,`${name} が開始しました`,data.agentId)
  })

  this.socket.on('agent:created',(data)=>{
   console.log('[WS] Agent created:',data.agentId,'parent:',data.parentAgentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.addAgent(data.agent)
   }
  })

  this.socket.on('agent:running',(data)=>{
   console.log('[WS] Agent running:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgentStatus(data.agentId,'running')
  })

  this.socket.on('agent:waiting_provider',(data)=>{
   console.log('[WS] Agent waiting provider:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgentStatus(data.agentId,'waiting_provider')
   const name=getAgentDisplayName(data.agent)
   useToastStore.getState().addToast('warning',`${name}: プロバイダ接続待機中`)
   useActivityFeedStore.getState().addEvent('agent_waiting_provider',name,`${name} がプロバイダ待機中`,data.agentId)
  })

  this.socket.on('agent:progress',(data)=>{
   console.log('[WS] Agent progress:',data.agentId,data.progress+'%')
   const agentStore=useAgentStore.getState()
   agentStore.updateAgent(data.agentId,{
    progress:data.progress,
    currentTask:data.currentTask,
    tokensUsed:data.tokensUsed
   })
  })

  this.socket.on('agent:log',({agentId,entry})=>{
   useAgentStore.getState().addLogEntry(agentId,entry)
  })

  this.socket.on('agent:completed',(data)=>{
   console.log('[WS] Agent completed:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgentStatus(data.agentId,'completed')
   const name=getAgentDisplayName(data.agent)
   const isLeader=!data.agent?.parentAgentId
   if(isLeader){
    useToastStore.getState().addToast('success',`${name} が完了しました`)
   }
   useActivityFeedStore.getState().addEvent('agent_completed',name,`${name} が完了しました`,data.agentId)
  })

  this.socket.on('agent:failed',(data)=>{
   console.error('[WS] Agent failed:',data.agentId,data.error)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgent(data.agentId,{error:data.error})
   agentStore.updateAgentStatus(data.agentId,'failed')
   agentStore.addLogEntry(data.agentId,{
    id:crypto.randomUUID(),
    timestamp:new Date().toISOString(),
    level:'error',
    message:data.error
   })
   const name=getAgentDisplayName(data.agent)
   useToastStore.getState().addToast('error',`${name} がエラーで停止しました`)
   useActivityFeedStore.getState().addEvent('agent_failed',name,`${name} がエラーで停止: ${data.error}`,data.agentId)
  })

  this.socket.on('agent:paused',(data)=>{
   console.log('[WS] Agent paused:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgentStatus(data.agentId,'paused')
   const name=getAgentDisplayName(data.agent)
   useActivityFeedStore.getState().addEvent('agent_paused',name,`${name} が一時停止しました`,data.agentId)
  })

  this.socket.on('agent:resumed',(data)=>{
   console.log('[WS] Agent resumed:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgentStatus(data.agentId,'running')
   const name=getAgentDisplayName(data.agent)
   useActivityFeedStore.getState().addEvent('agent_resumed',name,`${name} が再開しました`,data.agentId)
  })

  this.socket.on('agent:activated',(data)=>{
   console.log('[WS] Agent activated:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgentStatus(data.agentId,'running')
  })

  this.socket.on('agent:waiting_response',(data)=>{
   console.log('[WS] Agent waiting response:',data.agentId)
   const agentStore=useAgentStore.getState()
   if(data.agent){
    agentStore.updateAgent(data.agent.id,data.agent)
   }
   agentStore.updateAgentStatus(data.agentId,'waiting_response')
   const name=getAgentDisplayName(data.agent)
   useToastStore.getState().addToast('warning',`${name} がオペレーターの返答を待っています`)
   useActivityFeedStore.getState().addEvent('agent_waiting_response',name,`${name} がオペレーターの返答を待っています`,data.agentId)
  })

  this.socket.on('checkpoint:created',(data)=>{
   console.log('[WS] Checkpoint created:',data.checkpointId)
   if(data.checkpoint){
    useCheckpointStore.getState().addCheckpoint(data.checkpoint)
   }
   if(data.agentId&&data.agentStatus){
    useAgentStore.getState().updateAgentStatus(data.agentId,data.agentStatus as Agent['status'])
   }
   const agent=useAgentStore.getState().agents.find(a=>a.id===data.agentId)
   const name=getAgentDisplayName(agent)
   useToastStore.getState().addToast('warning',`${name} が承認を待っています`)
   useActivityFeedStore.getState().addEvent('checkpoint_created',name,`${name} が承認を待っています`,data.agentId)
  })

  this.socket.on('checkpoint:resolved',(data)=>{
   console.log('[WS] Checkpoint resolved:',data.checkpoint?.id||data.checkpointId)
   if(data.checkpoint){
    useCheckpointStore.getState().updateCheckpoint(data.checkpoint.id,data.checkpoint)
   }
   if(data.agentId&&data.agentStatus){
    useAgentStore.getState().updateAgentStatus(data.agentId,data.agentStatus as Agent['status'])
   }
   if(data.agentId){
    const agent=useAgentStore.getState().agents.find(a=>a.id===data.agentId)
    const name=getAgentDisplayName(agent)
    useActivityFeedStore.getState().addEvent('checkpoint_resolved',name,`${name} の承認が処理されました`,data.agentId)
   }
  })

  this.socket.on('asset:created',(data)=>{
   console.log('[WS] Asset created:',data.asset?.id)
   if(data.asset){
    useAssetStore.getState().addOrUpdateAsset(data.asset)
   }
  })

  this.socket.on('asset:updated',(data)=>{
   console.log('[WS] Asset updated:',data.asset?.id)
   if(data.asset){
    useAssetStore.getState().addOrUpdateAsset(data.asset)
   }
  })

  this.socket.on('project:updated',({projectId,updates})=>{
   console.log('[WS] Project updated:',projectId)
   useProjectStore.getState().updateProject(projectId,updates)
  })

  this.socket.on('phase:changed',({projectId,phase,phaseName})=>{
   console.log('[WS] Phase changed:',projectId,phase,phaseName)
   useProjectStore.getState().updateProject(projectId,{currentPhase:phase})
   useToastStore.getState().addToast('info',`PHASE ${phase} - ${phaseName} に移行しました`)
   useActivityFeedStore.getState().addEvent('phase_changed','System',`PHASE ${phase} - ${phaseName} に移行しました`)
  })

  this.socket.on('metrics:update',({projectId,metrics})=>{
   console.log('[WS] Metrics updated:',projectId,'Progress:',metrics.progressPercent+'%')
   useMetricsStore.getState().setProjectMetrics(metrics)
  })

  this.socket.on('agent:speech',(data)=>{
   useSpeechStore.getState().addSpeech(data.agentId,data.message,data.source)
  })

  this.socket.on('navigator:message',({speaker,text,priority})=>{
   console.log('[WS] Navigator message received:',speaker,text.substring(0,50)+'...')
   useNavigatorStore.getState().showServerMessage(speaker,text,priority)
  })
 }

 private doSubscribe(projectId:string):void{
  if(!this.socket){
   console.warn('[WS] Cannot subscribe: No socket')
   return
  }
  console.log('[WS] Emitting subscribe:project for:',projectId)
  this.socket.emit('subscribe:project',projectId)
  this.currentProjectId=projectId
 }

 subscribeToProject(projectId:string):void{
  console.log('[WS] subscribeToProject called:',projectId,'Connected:',this.socket?.connected)
  this.pendingProjectId=projectId

  if(!this.socket?.connected){
   console.warn('[WS] Not connected yet, will subscribe when connected')
   return
  }

  if(this.currentProjectId===projectId){
   console.log('[WS] Already subscribed to this project')
   return
  }

  if(this.currentProjectId&&this.currentProjectId!==projectId){
   this.doUnsubscribe(this.currentProjectId)
  }

  this.doSubscribe(projectId)
 }

 private doUnsubscribe(projectId:string):void{
  if(!this.socket?.connected)return
  console.log('[WS] Emitting unsubscribe:project for:',projectId)
  this.socket.emit('unsubscribe:project',projectId)
 }

 unsubscribeFromProject(projectId:string):void{
  console.log('[WS] unsubscribeFromProject called:',projectId)

  if(this.pendingProjectId===projectId){
   this.pendingProjectId=null
  }
  if(this.currentProjectId===projectId){
   this.doUnsubscribe(projectId)
   this.currentProjectId=null
  }
 }

 resolveCheckpoint(checkpointId:string,resolution:string,feedback?:string):void{
  if(!this.socket?.connected){
   console.warn('[WS] Cannot resolve checkpoint: Not connected')
   return
  }
  console.log('[WS] Resolving checkpoint:',checkpointId,resolution)
  this.socket.emit('checkpoint:resolve',{checkpointId,resolution,feedback})
 }

 disconnect():void{
  console.log('[WS] Disconnecting...')
  if(this.socket){
   this.socket.disconnect()
   this.socket=null
  }
  this.pendingProjectId=null
  this.currentProjectId=null
  useConnectionStore.getState().setStatus('disconnected')
 }

 isConnected():boolean{
  return this.socket?.connected ?? false
 }

 getStatus():{connected:boolean;currentProject:string|null;pendingProject:string|null}{
  return{
   connected:this.socket?.connected ?? false,
   currentProject:this.currentProjectId,
   pendingProject:this.pendingProjectId
  }
 }
}

export const websocketService=new WebSocketService()
