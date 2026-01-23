import { useState,useEffect,useRef,useMemo,useCallback } from 'react'
import { useAgentStore } from '../stores/agentStore'
import { useProjectStore } from '../stores/projectStore'
import StrategyMapCanvas from '../components/strategy-map/StrategyMapCanvas'
import { AI_SERVICES_CONFIG,TIMING,LAYOUT } from '../components/strategy-map/strategyMapConfig'
import { createFullDemoScenario,DemoRunner } from '../components/strategy-map/DemoScenarioGenerator'
import type { DemoEvent } from '../components/strategy-map/DemoScenarioGenerator'
import type { MapAgent,AIService,UserNode,Connection,BubbleType,ConnectionType } from '../components/strategy-map/strategyMapTypes'
import type { AIServiceId } from '../components/strategy-map/strategyMapConfig'
import type { Agent,AgentStatus,AgentType } from '../types/agent'
import { SoundManager } from '../components/strategy-map/SoundManager'
import { Button } from '../components/ui/Button'
import { Play,Pause,RotateCcw } from 'lucide-react'

interface SpawnTracker {
 spawnTimes: Map<string,number>
 previousIds: Set<string>
}

interface DemoAgentState {
 id: string
 type: AgentType
 status: AgentStatus
 parentId: string|null
 currentTask: string|null
 spawnProgress: number
 spawnTime: number
}

function determineBubble(agent: Agent): { text: string|null; type: BubbleType|null } {
 switch (agent.status) {
  case 'running':
   return agent.currentTask
    ? { text: agent.currentTask,type: 'info' }
    : { text: null,type: null }
  case 'waiting_approval':
   return { text: '確認をお願いします',type: 'question' }
  case 'completed':
   return { text: 'タスク完了!',type: 'success' }
  case 'failed':
   return { text: agent.error||'エラー発生',type: 'warning' }
  case 'blocked':
   return { text: 'ブロック中…',type: 'warning' }
  default:
   return { text: null,type: null }
 }
}

function determineDemoBubble(agent: DemoAgentState): { text: string|null; type: BubbleType|null } {
 switch (agent.status) {
  case 'running':
   return agent.currentTask
    ? { text: agent.currentTask,type: 'info' }
    : { text: null,type: null }
  case 'waiting_approval':
   return { text: '承認待ち',type: 'question' }
  case 'completed':
   return { text: '完了',type: 'success' }
  default:
   return { text: null,type: null }
 }
}

function computeAITarget(agent: Agent|DemoAgentState,index: number): AIServiceId|null {
 if (agent.status!=='running') return null

 const serviceIds=AI_SERVICES_CONFIG.map(s=>s.id)
 const typeHash=agent.type.split('').reduce((sum,char)=>sum+char.charCodeAt(0),0)
 return serviceIds[(typeHash+index)%serviceIds.length]
}

function convertAgentToMapAgent(
 agent: Agent,
 index: number,
 now: number,
 tracker: SpawnTracker
): MapAgent {
 const isNew=!tracker.previousIds.has(agent.id)
 if (isNew) {
  tracker.spawnTimes.set(agent.id,now)
 }

 const spawnTime=tracker.spawnTimes.get(agent.id)??now
 const elapsed=now-spawnTime
 const spawnProgress=Math.min(1,elapsed/TIMING.SPAWN_DURATION_MS)

 const bubble=determineBubble(agent)
 const aiTarget=computeAITarget(agent,index)

 return {
  id: agent.id,
  type: agent.type,
  status: agent.status,
  parentId: agent.parentAgentId,
  currentTask: agent.currentTask,
  aiTarget,
  bubble: bubble.text,
  bubbleType: bubble.type,
  spawnProgress,
 }
}

function convertDemoAgentToMapAgent(
 agent: DemoAgentState,
 index: number,
 now: number,
 aiTargetOverride?: AIServiceId|null
): MapAgent {
 const elapsed=now-agent.spawnTime
 const spawnProgress=Math.min(1,elapsed/TIMING.SPAWN_DURATION_MS)

 const bubble=determineDemoBubble(agent)
 const aiTarget=aiTargetOverride??computeAITarget(agent,index)

 return {
  id: agent.id,
  type: agent.type,
  status: agent.status,
  parentId: agent.parentId,
  currentTask: agent.currentTask,
  aiTarget,
  bubble: bubble.text,
  bubbleType: bubble.type,
  spawnProgress,
 }
}

function generateConnections(agents: readonly MapAgent[]): Connection[] {
 const connections: Connection[]=[]

 for (const agent of agents) {
  if (agent.parentId) {
   const parentExists=agents.some(a=>a.id===agent.parentId)
   if (parentExists) {
    const connectionType=getParentConnectionType(agent.status)
    if (connectionType) {
     connections.push({
      id: `${connectionType}-${agent.id}`,
      fromId: connectionType==='instruction'?agent.parentId:agent.id,
      toId: connectionType==='instruction'?agent.id:agent.parentId,
      type: connectionType,
      active: true,
     })
    }
   }
  }

  if (agent.aiTarget&&agent.status==='running') {
   connections.push({
    id: `ai-${agent.id}`,
    fromId: agent.id,
    toId: agent.aiTarget,
    type: 'ai-request',
    active: true,
   })
  }

  if (agent.status==='waiting_approval') {
   connections.push({
    id: `user-${agent.id}`,
    fromId: agent.id,
    toId: 'user',
    type: 'user-contact',
    active: true,
   })
  }
 }

 return connections
}

function getParentConnectionType(status: AgentStatus): ConnectionType|null {
 switch (status) {
  case 'running':
   return 'instruction'
  case 'waiting_approval':
   return 'confirm'
  case 'completed':
   return 'delivery'
  default:
   return null
 }
}

function positionAIServices(width: number): AIService[] {
 const count=AI_SERVICES_CONFIG.length
 const margin=LAYOUT.MARGIN_X
 const availableWidth=width-margin*2

 return AI_SERVICES_CONFIG.map((config,index)=>({
  ...config,
  x: margin+(availableWidth/Math.max(count-1,1))*index,
  y: 85,
 }))
}

export default function StrategyMapView() {
 const agents=useAgentStore(state=>state.agents)
 const { currentProject }=useProjectStore()

 const containerRef=useRef<HTMLDivElement>(null)
 const trackerRef=useRef<SpawnTracker>({
  spawnTimes: new Map(),
  previousIds: new Set(),
 })

 const [dimensions,setDimensions]=useState({ width: 1000,height: 700 })
 const [mapAgents,setMapAgents]=useState<MapAgent[]>([])
 const [connections,setConnections]=useState<Connection[]>([])
 const [userNode,setUserNode]=useState<UserNode>({ x: 500,y: 600,queue: [] })

 const [demoMode,setDemoMode]=useState(false)
 const [demoRunning,setDemoRunning]=useState(false)
 const [currentPhase,setCurrentPhase]=useState<number|null>(null)
 const [demoAgents,setDemoAgents]=useState<Map<string,DemoAgentState>>(new Map())
 const [aiTargets,setAiTargets]=useState<Map<string,AIServiceId>>(new Map())

 const demoRunnerRef=useRef<DemoRunner|null>(null)
 const soundManagerRef=useRef<SoundManager|null>(null)

 useEffect(()=>{
  soundManagerRef.current=new SoundManager()
  return ()=>{
   soundManagerRef.current?.destroy()
  }
 },[])

 const updateDimensions=useCallback(()=>{
  const container=containerRef.current
  if (!container) return

  const rect=container.getBoundingClientRect()
  setDimensions({ width: rect.width,height: rect.height })
  setUserNode(prev=>({
   ...prev,
   x: rect.width/2,
   y: rect.height*LAYOUT.USER_ZONE_Y+20,
  }))
 },[])

 useEffect(()=>{
  updateDimensions()
  window.addEventListener('resize',updateDimensions)
  return ()=>window.removeEventListener('resize',updateDimensions)
 },[updateDimensions])

 const handleDemoEvent=useCallback((event: DemoEvent)=>{
  const now=Date.now()

  if (event.sound&&soundManagerRef.current) {
   soundManagerRef.current.play(event.sound)
  }

  switch (event.type) {
   case 'phase_change':
    if (event.phase!==undefined) {
     setCurrentPhase(event.phase)
    }
    break

   case 'spawn':
    if (event.agentType) {
     setDemoAgents(prev=>{
      const next=new Map(prev)
      next.set(event.agentId,{
       id: event.agentId,
       type: event.agentType!,
       status: event.status??'running',
       parentId: event.parentId??null,
       currentTask: event.task??null,
       spawnProgress: 0,
       spawnTime: now,
      })
      return next
     })
    }
    break

   case 'status_change':
    setDemoAgents(prev=>{
     const next=new Map(prev)
     const agent=next.get(event.agentId)
     if (agent) {
      next.set(event.agentId,{
       ...agent,
       status: event.status??agent.status,
       currentTask: event.task??agent.currentTask,
      })
     }
     return next
    })
    break

   case 'task_update':
    setDemoAgents(prev=>{
     const next=new Map(prev)
     const agent=next.get(event.agentId)
     if (agent) {
      next.set(event.agentId,{
       ...agent,
       currentTask: event.task??agent.currentTask,
      })
     }
     return next
    })
    break

   case 'llm_call':
    if (event.aiService) {
     setAiTargets(prev=>{
      const next=new Map(prev)
      next.set(event.agentId,event.aiService as AIServiceId)
      return next
     })
    }
    break

   case 'approval_granted':
    setDemoAgents(prev=>{
     const next=new Map(prev)
     const agent=next.get(event.agentId)
     if (agent) {
      next.set(event.agentId,{
       ...agent,
       status: 'completed',
      })
     }
     return next
    })
    break

   case 'despawn':
    setDemoAgents(prev=>{
     const next=new Map(prev)
     next.delete(event.agentId)
     return next
    })
    setAiTargets(prev=>{
     const next=new Map(prev)
     next.delete(event.agentId)
     return next
    })
    break
  }
 },[])

 const handleDemoComplete=useCallback(()=>{
  setDemoRunning(false)
 },[])

 const startDemo=useCallback(()=>{
  const scenario=createFullDemoScenario()
  demoRunnerRef.current=new DemoRunner(scenario,handleDemoEvent,handleDemoComplete)
  setDemoMode(true)
  setDemoRunning(true)
  setDemoAgents(new Map())
  setAiTargets(new Map())
  setCurrentPhase(null)
  demoRunnerRef.current.start()
 },[handleDemoEvent,handleDemoComplete])

 const pauseDemo=useCallback(()=>{
  demoRunnerRef.current?.stop()
  setDemoRunning(false)
 },[])

 const resumeDemo=useCallback(()=>{
  demoRunnerRef.current?.start()
  setDemoRunning(true)
 },[])

 const resetDemo=useCallback(()=>{
  demoRunnerRef.current?.reset()
  setDemoMode(false)
  setDemoRunning(false)
  setDemoAgents(new Map())
  setAiTargets(new Map())
  setCurrentPhase(null)
 },[])

 useEffect(()=>{
  if (!demoMode) {
   const projectAgents=currentProject
    ? agents.filter(a=>a.projectId===currentProject.id)
    : agents

   const now=Date.now()
   const tracker=trackerRef.current

   const mapped=projectAgents.map((agent,index)=>
    convertAgentToMapAgent(agent,index,now,tracker)
   )

   tracker.previousIds=new Set(projectAgents.map(a=>a.id))

   setMapAgents(mapped)
   setConnections(generateConnections(mapped))

   const waitingIds=mapped
    .filter(a=>a.status==='waiting_approval')
    .map(a=>a.id)
   setUserNode(prev=>({ ...prev,queue: waitingIds }))
  }
 },[agents,currentProject,demoMode])

 useEffect(()=>{
  if (demoMode) {
   const now=Date.now()
   const agentsList=Array.from(demoAgents.values())

   const mapped=agentsList.map((agent,index)=>
    convertDemoAgentToMapAgent(agent,index,now,aiTargets.get(agent.id))
   )

   setMapAgents(mapped)
   setConnections(generateConnections(mapped))

   const waitingIds=mapped
    .filter(a=>a.status==='waiting_approval')
    .map(a=>a.id)
   setUserNode(prev=>({ ...prev,queue: waitingIds }))
  }
 },[demoMode,demoAgents,aiTargets])

 useEffect(()=>{
  const intervalId=setInterval(()=>{
   setMapAgents(prev=>
    prev.map(agent=>{
     if (agent.spawnProgress>=1) return agent
     const newProgress=Math.min(1,agent.spawnProgress+0.025)
     return { ...agent,spawnProgress: newProgress }
    })
   )
  },16)

  return ()=>clearInterval(intervalId)
 },[])

 const aiServices=useMemo(
  ()=>positionAIServices(dimensions.width),
  [dimensions.width]
 )

 const stats=useMemo(()=>({
  running: mapAgents.filter(a=>a.status==='running').length,
  waiting: mapAgents.filter(a=>a.status==='waiting_approval').length,
  completed: mapAgents.filter(a=>a.status==='completed').length,
  total: mapAgents.length,
 }),[mapAgents])

 const phaseLabels=['Phase0: コンセプト','Phase1: 企画','Phase2: 開発','Phase3: 品質']

 return (
  <div className="h-full flex flex-col">
   <div className="nier-page-header-row mb-2">
    <div className="flex items-center gap-4">
     <h1 className="nier-page-title">戦略マップ</h1>
     {demoMode&&currentPhase!==null&&(
      <span className="text-nier-small text-nier-accent-orange font-medium">
       {phaseLabels[currentPhase]||`Phase${currentPhase}`}
      </span>
     )}
    </div>
    <div className="flex items-center gap-4">
     <div className="flex gap-4 text-nier-small">
      <span className="text-nier-accent-orange">稼働: {stats.running}</span>
      <span className="text-nier-accent-yellow">待機: {stats.waiting}</span>
      <span className="text-nier-accent-green">完了: {stats.completed}</span>
      <span className="text-nier-text-light">計: {stats.total}</span>
     </div>
     <div className="flex gap-2">
      {!demoMode?(
       <Button size="sm" onClick={startDemo}>
        <Play className="w-3 h-3 mr-1" />
        デモ開始
       </Button>
      ):(
       <>
        {demoRunning?(
         <Button size="sm" onClick={pauseDemo}>
          <Pause className="w-3 h-3 mr-1" />
          一時停止
         </Button>
        ):(
         <Button size="sm" onClick={resumeDemo}>
          <Play className="w-3 h-3 mr-1" />
          再開
         </Button>
        )}
        <Button size="sm" variant="secondary" onClick={resetDemo}>
         <RotateCcw className="w-3 h-3 mr-1" />
         リセット
        </Button>
       </>
      )}
     </div>
    </div>
   </div>
   <div className="text-nier-caption text-nier-text-light mb-1">
    ホイール: ズーム / ドラッグ: パン
   </div>
   <div
    ref={containerRef}
    className="flex-1 border border-nier-border-light rounded overflow-hidden bg-nier-bg-main"
   >
    <StrategyMapCanvas
     agents={mapAgents}
     aiServices={aiServices}
     user={userNode}
     connections={connections}
     width={dimensions.width}
     height={dimensions.height}
    />
   </div>
  </div>
 )
}
