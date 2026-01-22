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

function agentToMapAgent(agent:Agent,index:number,allAgents:Agent[]):MapAgent{
 const parent=agent.parentAgentId?allAgents.find(a=>a.id===agent.parentAgentId):null
 let baseX=300+Math.random()*400
 let baseY=250+Math.random()*200
 if(parent){
  const parentMap=allAgents.findIndex(a=>a.id===parent.id)
  const siblingIndex=allAgents.filter(a=>a.parentAgentId===agent.parentAgentId).findIndex(a=>a.id===agent.id)
  baseX=300+(parentMap%5)*150+(siblingIndex%3)*50
  baseY=300+Math.floor(parentMap/5)*100+(siblingIndex)*40
 }else{
  const leaderIndex=allAgents.filter(a=>!a.parentAgentId).findIndex(a=>a.id===agent.id)
  baseX=150+leaderIndex*200
  baseY=250
 }
 let bubble:string|null=null
 let bubbleType:'info'|'question'|'success'|'warning'|null=null
 if(agent.status==='running'&&agent.currentTask){
  bubble=agent.currentTask.slice(0,15)+'...'
  bubbleType='info'
 }
 if(agent.status==='waiting_approval'){
  bubble='確認待ち'
  bubbleType='question'
 }
 if(agent.status==='completed'){
  bubble='完了!'
  bubbleType='success'
 }
 if(agent.status==='failed'){
  bubble='エラー'
  bubbleType='warning'
 }
 let aiTarget:string|null=null
 if(agent.status==='running'){
  aiTarget=['claude','openai','gemini'][index%3]
 }
 return{
  id:agent.id,
  type:agent.type,
  status:agent.status,
  parentId:agent.parentAgentId,
  x:baseX,
  y:baseY,
  targetX:baseX,
  targetY:baseY,
  currentTask:agent.currentTask,
  bubble,
  bubbleType,
  isSpawning:false,
  spawnProgress:1,
  workingFrame:0,
  aiTarget,
 }
}

function generateConnections(mapAgents:MapAgent[],_user:UserNode):Connection[]{
 const conns:Connection[]=[]
 mapAgents.forEach(agent=>{
  if(agent.parentId){
   const parent=mapAgents.find(a=>a.id===agent.parentId)
   if(parent){
    if(agent.status==='running'){
     conns.push({id:`inst-${agent.id}`,fromId:parent.id,toId:agent.id,type:'instruction',progress:1,active:true})
    }
    if(agent.status==='waiting_approval'){
     conns.push({id:`conf-${agent.id}`,fromId:agent.id,toId:parent.id,type:'confirm',progress:0.5+Math.sin(Date.now()*0.002)*0.3,active:true})
    }
    if(agent.status==='completed'){
     conns.push({id:`deliv-${agent.id}`,fromId:agent.id,toId:parent.id,type:'delivery',progress:1,active:true})
    }
   }
  }
  if(agent.aiTarget){
   conns.push({id:`ai-${agent.id}`,fromId:agent.id,toId:agent.aiTarget,type:'ai-request',progress:Math.random(),active:true})
  }
 })
 const waitingApproval=mapAgents.filter(a=>a.status==='waiting_approval')
 waitingApproval.forEach(agent=>{
  conns.push({id:`user-${agent.id}`,fromId:agent.id,toId:'user',type:'user-contact',progress:0.7,active:true})
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
  const mapped=projectAgents.map((a:Agent,i:number)=>agentToMapAgent(a,i,projectAgents))
  setMapAgents(mapped)
  const conns=generateConnections(mapped,userNode)
  setConnections(conns)
  const waiting=mapped.filter((a:MapAgent)=>a.status==='waiting_approval').map((a:MapAgent)=>a.id)
  setUserNode((prev:UserNode)=>({...prev,queue:waiting}))
 },[agents,currentProject,userNode.x,userNode.y])

 useEffect(()=>{
  const interval=setInterval(()=>{
   setConnections((prev:Connection[])=>prev.map((c:Connection)=>{
    if(c.type==='ai-request'||c.type==='confirm'){
     return{...c,progress:(c.progress+0.02)%1}
    }
    return c
   }))
  },50)
  return()=>clearInterval(interval)
 },[])

 const aiServicesPositioned=AI_SERVICES.map((s:AIService,i:number)=>({
  ...s,
  x:150+(size.width-300)/(AI_SERVICES.length-1)*i,
  y:80
 }))

 return(
  <div className="h-full flex flex-col">
   <div className="nier-page-header-row mb-2">
    <h1 className="nier-page-title">戦略マップ</h1>
    <p className="nier-page-subtitle">Agent {mapAgents.length}体稼働中</p>
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
