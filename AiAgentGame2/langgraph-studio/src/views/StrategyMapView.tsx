import{useState,useEffect,useRef}from'react'
import{useAgentStore}from'../stores/agentStore'
import{useProjectStore}from'../stores/projectStore'
import StrategyMapCanvas from'../components/strategy-map/StrategyMapCanvas'
import type{MapAgent,AIService,UserNode,Connection}from'../components/strategy-map/strategyMapTypes'
import type{Agent}from'../types/agent'

const AI_SERVICES:AIService[]=[
 {id:'claude',name:'Claude',icon:'C',x:200,y:100,color:'#D97706'},
 {id:'openai',name:'OpenAI',icon:'O',x:500,y:80,color:'#10B981'},
 {id:'gemini',name:'Gemini',icon:'G',x:800,y:100,color:'#3B82F6'},
]

const USER_NODE:UserNode={x:500,y:600,queue:[]}

const prevAgentIdsRef={current:new Set<string>()}
const spawnTimesRef={current:new Map<string,number>()}

function getBubbleForAgent(agent:Agent):{text:string|null,type:'info'|'question'|'success'|'warning'|null}{
 if(agent.status==='running'&&agent.currentTask){
  return{text:agent.currentTask,type:'info'}
 }
 if(agent.status==='waiting_approval'){
  return{text:'確認をお願いします',type:'question'}
 }
 if(agent.status==='completed'){
  return{text:'タスク完了!',type:'success'}
 }
 if(agent.status==='failed'){
  return{text:agent.error||'エラー発生',type:'warning'}
 }
 if(agent.status==='blocked'){
  return{text:'ブロック中…',type:'warning'}
 }
 if(agent.status==='pending'){
  return{text:null,type:null}
 }
 return{text:null,type:null}
}

function getAITarget(agent:Agent,index:number):string|null{
 if(agent.status!=='running')return null
 const aiServices=['claude','openai','gemini']
 const typeHash=agent.type.split('').reduce((a,c)=>a+c.charCodeAt(0),0)
 return aiServices[(typeHash+index)%aiServices.length]
}

function agentToMapAgent(agent:Agent,index:number,allAgents:Agent[],now:number):MapAgent{
 const isNew=!prevAgentIdsRef.current.has(agent.id)
 if(isNew){
  spawnTimesRef.current.set(agent.id,now)
 }
 const spawnTime=spawnTimesRef.current.get(agent.id)||now
 const spawnDuration=1000
 const elapsed=now-spawnTime
 const spawnProgress=Math.min(1,elapsed/spawnDuration)
 const isSpawning=spawnProgress<1
 const{text:bubble,type:bubbleType}=getBubbleForAgent(agent)
 const aiTarget=getAITarget(agent,index)
 return{
  id:agent.id,
  type:agent.type,
  status:agent.status,
  parentId:agent.parentAgentId,
  x:0,
  y:0,
  targetX:0,
  targetY:0,
  currentTask:agent.currentTask,
  bubble,
  bubbleType,
  isSpawning,
  spawnProgress,
  workingFrame:0,
  aiTarget,
 }
}

function generateConnections(mapAgents:MapAgent[]):Connection[]{
 const conns:Connection[]=[]
 mapAgents.forEach(agent=>{
  if(agent.parentId){
   const parent=mapAgents.find(a=>a.id===agent.parentId)
   if(parent){
    if(agent.status==='running'){
     conns.push({
      id:`inst-${agent.id}`,
      fromId:parent.id,
      toId:agent.id,
      type:'instruction',
      progress:1,
      active:true
     })
    }
    if(agent.status==='waiting_approval'){
     conns.push({
      id:`conf-${agent.id}`,
      fromId:agent.id,
      toId:parent.id,
      type:'confirm',
      progress:0,
      active:true
     })
    }
    if(agent.status==='completed'){
     conns.push({
      id:`deliv-${agent.id}`,
      fromId:agent.id,
      toId:parent.id,
      type:'delivery',
      progress:0,
      active:true
     })
    }
   }
  }
  if(agent.aiTarget&&agent.status==='running'){
   conns.push({
    id:`ai-${agent.id}`,
    fromId:agent.id,
    toId:agent.aiTarget,
    type:'ai-request',
    progress:0,
    active:true
   })
  }
  if(agent.status==='waiting_approval'){
   conns.push({
    id:`user-${agent.id}`,
    fromId:agent.id,
    toId:'user',
    type:'user-contact',
    progress:0,
    active:true
   })
  }
 })
 return conns
}

export default function StrategyMapView(){
 const agents=useAgentStore((s:{agents:Agent[]})=>s.agents)
 const{currentProject}=useProjectStore()
 const containerRef=useRef<HTMLDivElement>(null)
 const [size,setSize]=useState({width:1000,height:700})
 const [mapAgents,setMapAgents]=useState<MapAgent[]>([])
 const [connections,setConnections]=useState<Connection[]>([])
 const [userNode,setUserNode]=useState<UserNode>(USER_NODE)

 useEffect(()=>{
  const updateSize=()=>{
   if(containerRef.current){
    const rect=containerRef.current.getBoundingClientRect()
    setSize({width:rect.width,height:rect.height})
    setUserNode((prev:UserNode)=>({...prev,x:rect.width/2,y:rect.height-80}))
   }
  }
  updateSize()
  window.addEventListener('resize',updateSize)
  return()=>window.removeEventListener('resize',updateSize)
 },[])

 useEffect(()=>{
  const projectAgents=currentProject?agents.filter((a:Agent)=>a.projectId===currentProject.id):agents
  const now=Date.now()
  const mapped=projectAgents.map((a:Agent,i:number)=>agentToMapAgent(a,i,projectAgents,now))
  prevAgentIdsRef.current=new Set(projectAgents.map((a:Agent)=>a.id))
  setMapAgents(mapped)
  const conns=generateConnections(mapped)
  setConnections(conns)
  const waiting=mapped.filter((a:MapAgent)=>a.status==='waiting_approval').map((a:MapAgent)=>a.id)
  setUserNode((prev:UserNode)=>({...prev,queue:waiting}))
 },[agents,currentProject])

 useEffect(()=>{
  const interval=setInterval(()=>{
   setMapAgents((prev:MapAgent[])=>prev.map((a:MapAgent)=>{
    if(a.isSpawning){
     const newProgress=Math.min(1,a.spawnProgress+0.02)
     return{...a,spawnProgress:newProgress,isSpawning:newProgress<1}
    }
    return a
   }))
  },16)
  return()=>clearInterval(interval)
 },[])

 const aiServicesPositioned=AI_SERVICES.map((s:AIService,i:number)=>({
  ...s,
  x:120+(size.width-240)/(AI_SERVICES.length-1||1)*i,
  y:90
 }))

 const runningCount=mapAgents.filter(a=>a.status==='running').length
 const waitingCount=mapAgents.filter(a=>a.status==='waiting_approval').length
 const completedCount=mapAgents.filter(a=>a.status==='completed').length

 return(
  <div className="h-full flex flex-col">
   <div className="nier-page-header-row mb-2">
    <h1 className="nier-page-title">戦略マップ</h1>
    <div className="flex gap-4 text-nier-small">
     <span className="text-nier-accent-orange">稼働: {runningCount}</span>
     <span className="text-nier-accent-yellow">待機: {waitingCount}</span>
     <span className="text-nier-accent-green">完了: {completedCount}</span>
     <span className="text-nier-text-light">計: {mapAgents.length}</span>
    </div>
   </div>
   <div className="text-nier-caption text-nier-text-light mb-1">
    ホイール: ズーム / ドラッグ: パン
   </div>
   <div ref={containerRef} className="flex-1 border border-nier-border-light rounded overflow-hidden bg-nier-bg-main">
    <StrategyMapCanvas
     agents={mapAgents}
     aiServices={aiServicesPositioned}
     user={userNode}
     connections={connections}
     width={size.width}
     height={size.height}
    />
   </div>
  </div>
 )
}
