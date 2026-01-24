import { useRef,useEffect,useCallback } from 'react'
import 'pixi.js/unsafe-eval'
import { Application,Graphics,Text,Container } from 'pixi.js'
import type {
 MapAgent,
 AIService,
 UserNode,
 Connection,
 AgentPositionState,
 Vec2,
 ConnectionType,
} from './strategyMapTypes'
import {
 PHYSICS,
 LAYOUT,
 TIMING,
 SIZES,
 COLORS,
 ZOOM,
} from './strategyMapConfig'
import { getAgentDisplayConfig } from '../ai-game/pixelCharacters'

interface Props {
 agents: readonly MapAgent[]
 aiServices: readonly AIService[]
 user: UserNode
 connections: readonly Connection[]
 width: number
 height: number
}

interface RenderState {
 positions: Map<string,AgentPositionState>
 frame: number
}

interface CanvasState {
 zoom: number
 panX: number
 panY: number
 isDragging: boolean
 dragStartX: number
 dragStartY: number
}

const CONNECTION_COLORS: Record<ConnectionType,number>={
 instruction: 0x5080B0,
 confirm: 0xC49060,
 delivery: 0x60A060,
 'ai-request': 0x9060B0,
 'user-contact': 0xB05050,
}

function hexToNumber(hex: string): number {
 return parseInt(hex.replace('#',''),16)
}

function computeAgentTarget(
 agent: MapAgent,
 allAgents: readonly MapAgent[],
 positions: Map<string,AgentPositionState>,
 aiServices: readonly AIService[],
 user: UserNode,
 width: number,
 height: number
): Vec2 {
 const userZoneY=height*LAYOUT.USER_ZONE_Y
 const workZoneTop=height*LAYOUT.WORK_ZONE_TOP

 if (agent.status==='waiting_approval') {
  const waiting=allAgents.filter(a=>a.status==='waiting_approval')
  const idx=waiting.findIndex(a=>a.id===agent.id)
  const count=waiting.length
  const spacing=Math.min(LAYOUT.APPROVAL_QUEUE_SPACING,(width*0.75)/Math.max(count,1))
  const startX=user.x-((count-1)*spacing)/2
  return { x: startX+idx*spacing,y: userZoneY-LAYOUT.APPROVAL_QUEUE_OFFSET_Y }
 }

 if (agent.aiTarget&&agent.status==='running') {
  const ai=aiServices.find(s=>s.id===agent.aiTarget)
  if (ai) {
   const atThisAI=allAgents.filter(a=>a.aiTarget===agent.aiTarget&&a.status==='running')
   const idx=atThisAI.findIndex(a=>a.id===agent.id)
   const count=atThisAI.length
   const angleSpread=LAYOUT.AI_ORBIT_ANGLE_SPREAD
   const baseAngle=Math.PI/2
   const angle=count===1
    ? baseAngle
    : baseAngle-angleSpread/2+(angleSpread*idx)/(count-1)
   const layer=Math.floor(idx/6)
   const radius=LAYOUT.AI_ORBIT_RADIUS_BASE+layer*LAYOUT.AI_ORBIT_RADIUS_STEP
   return {
    x: ai.x+Math.cos(angle)*radius,
    y: ai.y+Math.sin(angle)*radius,
   }
  }
 }

 if (agent.parentId) {
  const parentPos=positions.get(agent.parentId)
  if (parentPos) {
   const siblings=allAgents.filter(a=>a.parentId===agent.parentId)
   const idx=siblings.findIndex(a=>a.id===agent.id)
   const count=siblings.length
   const spread=Math.min(count*LAYOUT.CHILD_SPREAD_FACTOR,LAYOUT.CHILD_SPREAD_MAX)
   const col=idx%6
   const row=Math.floor(idx/6)
   const colCount=Math.min(count,6)
   const startX=parentPos.x-spread/2
   const xStep=spread/Math.max(colCount-1,1)
   return {
    x: startX+col*xStep,
    y: parentPos.y+LAYOUT.CHILD_VERTICAL_GAP+row*LAYOUT.CHILD_ROW_GAP,
   }
  }
 }

 const leaders=allAgents.filter(a=>!a.parentId)
 const idx=leaders.findIndex(a=>a.id===agent.id)
 const count=leaders.length
 const availableWidth=width-LAYOUT.MARGIN_X*2
 const spacing=Math.min(LAYOUT.LEADER_SPACING_MAX,availableWidth/Math.max(count,1))
 const startX=width/2-((count-1)*spacing)/2
 return { x: startX+idx*spacing,y: workZoneTop+LAYOUT.LEADER_OFFSET_Y }
}

function findAvoidanceDirection(
 positions: Map<string,AgentPositionState>,
 currentId: string,
 pos: AgentPositionState,
 dirX: number,
 dirY: number
): Vec2 {
 const avoidRadius=PHYSICS.REPULSION_RADIUS
 const avoidRadiusSq=avoidRadius*avoidRadius*4
 let closestDistSq=Infinity
 let closestX=0
 let closestY=0

 positions.forEach((other,otherId)=>{
  if (otherId===currentId) return
  const toOtherX=other.x-pos.x
  const toOtherY=other.y-pos.y
  const distSq=toOtherX*toOtherX+toOtherY*toOtherY
  if (distSq<avoidRadiusSq&&distSq>PHYSICS.EPSILON) {
   const dotProduct=dirX*toOtherX+dirY*toOtherY
   if (dotProduct>0&&distSq<closestDistSq) {
    closestDistSq=distSq
    closestX=other.x
    closestY=other.y
   }
  }
 })

 if (closestDistSq===Infinity) return { x: dirX,y: dirY }

 const toObsX=closestX-pos.x
 const toObsY=closestY-pos.y
 const perpX=-toObsY
 const perpY=toObsX
 const perpLenSq=perpX*perpX+perpY*perpY
 if (perpLenSq<PHYSICS.EPSILON) return { x: dirX,y: dirY }

 const perpLen=Math.sqrt(perpLenSq)
 const normPerpX=perpX/perpLen
 const normPerpY=perpY/perpLen
 const cross=dirX*toObsY-dirY*toObsX
 const sign=cross>=0 ? 1 :-1
 const strength=PHYSICS.AVOIDANCE_STRENGTH
 const newDirX=dirX*(1-strength)+normPerpX*sign*strength
 const newDirY=dirY*(1-strength)+normPerpY*sign*strength
 const lenSq=newDirX*newDirX+newDirY*newDirY
 if (lenSq<PHYSICS.EPSILON) return { x: dirX,y: dirY }
 const len=Math.sqrt(lenSq)
 return { x: newDirX/len,y: newDirY/len }
}

function updatePhysics(
 positions: Map<string,AgentPositionState>,
 id: string,
 pos: AgentPositionState
): void {
 const dx=pos.targetX-pos.x
 const dy=pos.targetY-pos.y
 const dist=Math.sqrt(dx*dx+dy*dy)

 if (dist<1) {
  pos.vx*=PHYSICS.DAMPING
  pos.vy*=PHYSICS.DAMPING
  pos.x+=pos.vx
  pos.y+=pos.vy
  return
 }

 const dirX=dx/dist
 const dirY=dy/dist
 const adjusted=findAvoidanceDirection(positions,id,pos,dirX,dirY)
 pos.vx+=adjusted.x*dist*PHYSICS.SPRING_STIFFNESS
 pos.vy+=adjusted.y*dist*PHYSICS.SPRING_STIFFNESS
 pos.vx*=PHYSICS.DAMPING
 pos.vy*=PHYSICS.DAMPING
 if (Math.abs(pos.vx)<PHYSICS.MIN_VELOCITY) pos.vx=0
 if (Math.abs(pos.vy)<PHYSICS.MIN_VELOCITY) pos.vy=0
 pos.x+=pos.vx
 pos.y+=pos.vy
}

function drawHexagon(g: Graphics,x: number,y: number,radius: number): void {
 const points: number[]=[]
 for (let i=0;i<6;i++) {
  const angle=Math.PI/6+i*Math.PI/3
  points.push(x+Math.cos(angle)*radius)
  points.push(y+Math.sin(angle)*radius)
 }
 g.poly(points,true)
}

export default function StrategyMapPixi({
 agents,
 aiServices,
 user,
 connections,
 width,
 height,
}: Props) {
 const containerRef=useRef<HTMLDivElement>(null)
 const appRef=useRef<Application|null>(null)

 const renderStateRef=useRef<RenderState>({
  positions: new Map(),
  frame: 0,
 })

 const canvasStateRef=useRef<CanvasState>({
  zoom: 1,
  panX: 0,
  panY: 0,
  isDragging: false,
  dragStartX: 0,
  dragStartY: 0,
 })

 const objectsRef=useRef<{
  world: Container|null
  aiNodes: Map<string,Container>
  userNode: Container|null
  agentNodes: Map<string,Container>
  packets: Graphics|null
 }>({
  world: null,
  aiNodes: new Map(),
  userNode: null,
  agentNodes: new Map(),
  packets: null,
 })

 const updatePositions=useCallback(()=>{
  const state=renderStateRef.current
  const { positions }=state
  const agentIdsSet=new Set(agents.map(a=>a.id))

  for (const agent of agents) {
   const target=computeAgentTarget(agent,agents,positions,aiServices,user,width,height)
   let pos=positions.get(agent.id)
   if (!pos) {
    pos={ x: target.x,y: target.y,vx: 0,vy: 0,targetX: target.x,targetY: target.y }
    positions.set(agent.id,pos)
   } else {
    pos.targetX=target.x
    pos.targetY=target.y
   }
  }

  positions.forEach((_,id)=>{
   if (!agentIdsSet.has(id)) positions.delete(id)
  })

  positions.forEach((pos,id)=>updatePhysics(positions,id,pos))
 },[agents,aiServices,user,width,height])

 useEffect(()=>{
  if (!containerRef.current) return

  let app: Application|null=null
  let destroyed=false

  const init=async ()=>{
   app=new Application()
   await app.init({
    width,
    height,
    backgroundColor: hexToNumber(COLORS.BACKGROUND),
    antialias: true,
    resolution: window.devicePixelRatio||1,
    autoDensity: true,
   })

   if (destroyed) {
    app.destroy(true)
    return
   }

   appRef.current=app
   containerRef.current?.appendChild(app.canvas as HTMLCanvasElement)

   const world=new Container()
   app.stage.addChild(world)
   objectsRef.current.world=world

   const packets=new Graphics()
   world.addChild(packets)
   objectsRef.current.packets=packets

   for (const ai of aiServices) {
    const node=createAINode(ai)
    world.addChild(node)
    objectsRef.current.aiNodes.set(ai.id,node)
   }

   const userNode=createUserNode(user)
   world.addChild(userNode)
   objectsRef.current.userNode=userNode

   app.ticker.add(()=>{
    if (destroyed) return
    renderStateRef.current.frame++
    updatePositions()
    updateWorld()
   })
  }

  const createAINode=(ai: AIService): Container=>{
   const container=new Container()
   container.x=ai.x
   container.y=ai.y

   const g=new Graphics()
   g.fill({ color: 0xF5F0E8 })
   drawHexagon(g,0,0,SIZES.AI_NODE_RADIUS)
   g.fill()
   g.stroke({ color: hexToNumber(COLORS.TEXT_SECONDARY),width: 1.5 })
   drawHexagon(g,0,0,SIZES.AI_NODE_RADIUS)
   g.stroke()
   container.addChild(g)

   const text=new Text({
    text: ai.name,
    style: { fontFamily: 'system-ui, sans-serif',fontSize: 12,fontWeight: 'bold',fill: COLORS.TEXT_PRIMARY },
   })
   text.anchor.set(0.5)
   container.addChild(text)

   return container
  }

  const createUserNode=(u: UserNode): Container=>{
   const container=new Container()
   container.x=u.x
   container.y=u.y

   const g=new Graphics()
   g.fill({ color: 0xF5F0E8 })
   drawHexagon(g,0,0,SIZES.USER_NODE_RADIUS)
   g.fill()
   g.stroke({ color: hexToNumber(COLORS.TEXT_SECONDARY),width: 1.5 })
   drawHexagon(g,0,0,SIZES.USER_NODE_RADIUS)
   g.stroke()
   container.addChild(g)

   const title=new Text({
    text: 'USER',
    style: { fontFamily: 'system-ui, sans-serif',fontSize: 11,fontWeight: 'bold',fill: COLORS.TEXT_PRIMARY },
   })
   title.anchor.set(0.5)
   title.y=-4
   container.addChild(title)

   const sub=new Text({
    text: '承認者',
    style: { fontFamily: 'system-ui, sans-serif',fontSize: 9,fill: COLORS.TEXT_SECONDARY },
   })
   sub.anchor.set(0.5)
   sub.y=8
   container.addChild(sub)

   return container
  }

  const createAgentNode=(agent: MapAgent): Container=>{
   const container=new Container()
   const config=getAgentDisplayConfig(agent.type)

   const g=new Graphics()
   g.circle(0,0,12)
   g.fill({ color: 0xF5F0E8 })
   g.stroke({ color: hexToNumber(COLORS.TEXT_SECONDARY),width: 1 })
   container.addChild(g)

   const text=new Text({
    text: config.shortLabel||config.label.slice(0,2),
    style: { fontFamily: 'system-ui, sans-serif',fontSize: 8,fontWeight: 'bold',fill: COLORS.TEXT_PRIMARY },
   })
   text.anchor.set(0.5)
   container.addChild(text)

   const label=new Text({
    text: config.label,
    style: { fontFamily: 'system-ui, sans-serif',fontSize: 9,fill: COLORS.TEXT_PRIMARY },
   })
   label.anchor.set(0.5)
   label.y=SIZES.AGENT_LABEL_OFFSET_Y
   container.addChild(label)

   return container
  }

  const updateWorld=()=>{
   const state=renderStateRef.current
   const canvasState=canvasStateRef.current
   const world=objectsRef.current.world
   if (!world) return

   world.x=width/2
   world.y=height/2
   world.scale.set(canvasState.zoom)
   world.pivot.set(width/2-canvasState.panX,height/2-canvasState.panY)

   const userNode=objectsRef.current.userNode
   if (userNode) {
    userNode.x=user.x
    userNode.y=user.y
   }

   for (const ai of aiServices) {
    const node=objectsRef.current.aiNodes.get(ai.id)
    if (node) {
     node.x=ai.x
     node.y=ai.y
    }
   }

   const agentIdsSet=new Set(agents.map(a=>a.id))
   objectsRef.current.agentNodes.forEach((node,id)=>{
    if (!agentIdsSet.has(id)) {
     node.destroy()
     objectsRef.current.agentNodes.delete(id)
    }
   })

   for (const agent of agents) {
    let node=objectsRef.current.agentNodes.get(agent.id)
    if (!node) {
     node=createAgentNode(agent)
     world.addChild(node)
     objectsRef.current.agentNodes.set(agent.id,node)
    }
    const pos=state.positions.get(agent.id)
    if (pos) {
     node.x=pos.x
     node.y=pos.y
     node.alpha=agent.status==='failed'||agent.status==='blocked' ? 0.5 : 1
    }
   }

   const packets=objectsRef.current.packets
   if (packets) {
    packets.clear()
    for (const conn of connections) {
     if (!conn.active) continue
     const fromPos=state.positions.get(conn.fromId)
     if (!fromPos) continue

     let toX=0,toY=0
     const toPos=state.positions.get(conn.toId)
     const toAI=aiServices.find(s=>s.id===conn.toId)
     if (toPos) { toX=toPos.x;toY=toPos.y }
     else if (toAI) { toX=toAI.x;toY=toAI.y }
     else if (conn.toId==='user') { toX=user.x;toY=user.y }
     else continue

     const t=(state.frame%TIMING.PACKET_SPAWN_INTERVAL)/TIMING.PACKET_SPAWN_INTERVAL
     const px=fromPos.x+(toX-fromPos.x)*t
     const py=fromPos.y+(toY-fromPos.y)*t
     packets.circle(px,py,4)
     packets.fill({ color: CONNECTION_COLORS[conn.type] })
    }
   }
  }

  init()

  return ()=>{
   destroyed=true
   if (appRef.current) {
    appRef.current.destroy(true)
    appRef.current=null
   }
  }
 },[width,height,aiServices,user,agents,connections,updatePositions])

 const handleWheel=useCallback((e: React.WheelEvent)=>{
  e.preventDefault()
  const state=canvasStateRef.current
  const factor=e.deltaY>0 ? 1-ZOOM.STEP : 1+ZOOM.STEP
  state.zoom=Math.max(ZOOM.MIN,Math.min(ZOOM.MAX,state.zoom*factor))
 },[])

 const handleMouseDown=useCallback((e: React.MouseEvent)=>{
  const state=canvasStateRef.current
  state.isDragging=true
  state.dragStartX=e.clientX-state.panX
  state.dragStartY=e.clientY-state.panY
 },[])

 const handleMouseMove=useCallback((e: React.MouseEvent)=>{
  const state=canvasStateRef.current
  if (!state.isDragging) return
  state.panX=e.clientX-state.dragStartX
  state.panY=e.clientY-state.dragStartY
 },[])

 const handleMouseUp=useCallback(()=>{
  canvasStateRef.current.isDragging=false
 },[])

 return (
  <div
   ref={containerRef}
   className="cursor-grab active:cursor-grabbing"
   style={{ width,height }}
   onWheel={handleWheel}
   onMouseDown={handleMouseDown}
   onMouseMove={handleMouseMove}
   onMouseUp={handleMouseUp}
   onMouseLeave={handleMouseUp}
  />
 )
}
