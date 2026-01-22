import{useRef,useEffect,useState,useCallback}from'react'
import type{MapAgent,AIService,UserNode,Connection}from'./strategyMapTypes'
import{drawPixelCharacter,getAgentDisplayConfig}from'../ai-game/pixelCharacters'

interface Props{
 agents:MapAgent[]
 aiServices:AIService[]
 user:UserNode
 connections:Connection[]
 width:number
 height:number
}

interface AgentPosition{
 x:number
 y:number
 vx:number
 vy:number
 targetX:number
 targetY:number
}

interface Particle{
 x:number
 y:number
 vx:number
 vy:number
 life:number
 color:string
 size:number
}

interface DataPacket{
 id:string
 x:number
 y:number
 targetX:number
 targetY:number
 color:string
 progress:number
}

const EASING=0.08
const AI_ZONE_Y_RATIO=0.12
const USER_ZONE_Y_RATIO=0.88
const WORK_ZONE_Y_MIN=0.25
const WORK_ZONE_Y_MAX=0.75

export default function StrategyMapCanvas({agents,aiServices,user,connections,width,height}:Props){
 const canvasRef=useRef<HTMLCanvasElement>(null)
 const frameRef=useRef(0)
 const positionsRef=useRef<Map<string,AgentPosition>>(new Map())
 const particlesRef=useRef<Particle[]>([])
 const packetsRef=useRef<DataPacket[]>([])
 const [zoom,setZoom]=useState(1)
 const [pan,setPan]=useState({x:0,y:0})
 const [dragging,setDragging]=useState(false)
 const [dragStart,setDragStart]=useState({x:0,y:0})

 const getAgentTarget=useCallback((agent:MapAgent,allAgents:MapAgent[]):{ x:number,y:number}=>{
  const aiZoneY=height*AI_ZONE_Y_RATIO
  const userZoneY=height*USER_ZONE_Y_RATIO
  const workZoneTop=height*WORK_ZONE_Y_MIN
  const workZoneBottom=height*WORK_ZONE_Y_MAX
  if(agent.status==='waiting_approval'){
   const waitingList=allAgents.filter(a=>a.status==='waiting_approval')
   const myIndex=waitingList.findIndex(a=>a.id===agent.id)
   const total=waitingList.length
   const spacing=Math.min(60,width*0.8/Math.max(total,1))
   const startX=user.x-(total-1)*spacing/2
   return{x:startX+myIndex*spacing,y:userZoneY-80}
  }
  if(agent.aiTarget&&agent.status==='running'){
   const ai=aiServices.find(s=>s.id===agent.aiTarget)
   if(ai){
    const atThisAI=allAgents.filter(a=>a.aiTarget===agent.aiTarget&&a.status==='running')
    const myIndex=atThisAI.findIndex(a=>a.id===agent.id)
    const total=atThisAI.length
    const angleSpread=Math.PI*0.8
    const baseAngle=Math.PI/2
    const angle=total===1?baseAngle:baseAngle-angleSpread/2+angleSpread*myIndex/(total-1)
    const radius=70+Math.floor(myIndex/5)*40
    return{x:ai.x+Math.cos(angle)*radius,y:ai.y+Math.sin(angle)*radius}
   }
  }
  if(agent.parentId){
   const parent=allAgents.find(a=>a.id===agent.parentId)
   if(parent){
    const parentPos=positionsRef.current.get(parent.id)
    if(parentPos){
     const siblings=allAgents.filter(a=>a.parentId===agent.parentId)
     const myIndex=siblings.findIndex(a=>a.id===agent.id)
     const total=siblings.length
     const spread=Math.min(total*50,300)
     const startX=parentPos.x-spread/2
     const offsetY=80+Math.floor(myIndex/6)*60
     return{x:startX+(myIndex%6)*(spread/Math.min(total,6)),y:parentPos.y+offsetY}
    }
   }
  }
  const leaders=allAgents.filter(a=>!a.parentId)
  const myIndex=leaders.findIndex(a=>a.id===agent.id)
  const total=leaders.length
  const spacing=Math.min(180,width*0.8/Math.max(total,1))
  const startX=width/2-(total-1)*spacing/2
  return{x:startX+myIndex*spacing,y:workZoneTop+50}
 },[height,width,aiServices,user.x])

 const updatePositions=useCallback((allAgents:MapAgent[])=>{
  allAgents.forEach(agent=>{
   let pos=positionsRef.current.get(agent.id)
   const target=getAgentTarget(agent,allAgents)
   if(!pos){
    pos={x:target.x,y:target.y,vx:0,vy:0,targetX:target.x,targetY:target.y}
    positionsRef.current.set(agent.id,pos)
    for(let i=0;i<8;i++){
     particlesRef.current.push({
      x:target.x,y:target.y,
      vx:(Math.random()-0.5)*4,
      vy:(Math.random()-0.5)*4,
      life:30,color:'#FFD700',size:3
     })
    }
   }else{
    pos.targetX=target.x
    pos.targetY=target.y
   }
  })
  const currentIds=new Set(allAgents.map(a=>a.id))
  positionsRef.current.forEach((pos,id)=>{
   if(!currentIds.has(id)){
    for(let i=0;i<5;i++){
     particlesRef.current.push({
      x:pos.x,y:pos.y,
      vx:(Math.random()-0.5)*3,
      vy:(Math.random()-0.5)*3,
      life:20,color:'#888',size:2
     })
    }
    positionsRef.current.delete(id)
   }
  })
  positionsRef.current.forEach(pos=>{
   const dx=pos.targetX-pos.x
   const dy=pos.targetY-pos.y
   pos.vx+=dx*EASING
   pos.vy+=dy*EASING
   pos.vx*=0.9
   pos.vy*=0.9
   pos.x+=pos.vx
   pos.y+=pos.vy
  })
 },[getAgentTarget])

 const spawnPacket=(fromX:number,fromY:number,toX:number,toY:number,color:string)=>{
  packetsRef.current.push({
   id:`${Date.now()}-${Math.random()}`,
   x:fromX,y:fromY,
   targetX:toX,targetY:toY,
   color,progress:0
  })
 }

 const updatePackets=()=>{
  packetsRef.current=packetsRef.current.filter(p=>{
   p.progress+=0.025
   p.x+=(p.targetX-p.x)*0.08
   p.y+=(p.targetY-p.y)*0.08
   if(p.progress>=1){
    for(let i=0;i<4;i++){
     particlesRef.current.push({
      x:p.targetX,y:p.targetY,
      vx:(Math.random()-0.5)*2,
      vy:(Math.random()-0.5)*2,
      life:15,color:p.color,size:2
     })
    }
    return false
   }
   return true
  })
 }

 const updateParticles=()=>{
  particlesRef.current=particlesRef.current.filter(p=>{
   p.x+=p.vx
   p.y+=p.vy
   p.vy+=0.15
   p.life--
   return p.life>0
  })
 }

 const drawAIService=(ctx:CanvasRenderingContext2D,ai:AIService,frame:number,count:number)=>{
  const{x,y,name,color}=ai
  const pulse=1+Math.sin(frame*0.05)*0.03
  const r=40*pulse
  const grad=ctx.createRadialGradient(x,y,r*0.3,x,y,r*1.5)
  grad.addColorStop(0,color+'30')
  grad.addColorStop(1,color+'00')
  ctx.fillStyle=grad
  ctx.beginPath()
  ctx.arc(x,y,r*1.5,0,Math.PI*2)
  ctx.fill()
  ctx.fillStyle=color
  ctx.beginPath()
  ctx.arc(x,y,r,0,Math.PI*2)
  ctx.fill()
  ctx.fillStyle='#fff'
  ctx.font='bold 13px sans-serif'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText(name,x,y)
  if(count>0){
   ctx.fillStyle=color
   ctx.beginPath()
   ctx.arc(x+r*0.7,y-r*0.7,14,0,Math.PI*2)
   ctx.fill()
   ctx.fillStyle='#fff'
   ctx.font='bold 11px sans-serif'
   ctx.fillText(String(count),x+r*0.7,y-r*0.7)
  }
 }

 const drawUserNode=(ctx:CanvasRenderingContext2D,u:UserNode,frame:number)=>{
  const{x,y,queue}=u
  const hasQueue=queue.length>0
  if(hasQueue){
   const alertPulse=0.2+Math.sin(frame*0.08)*0.15
   ctx.fillStyle=`rgba(200,80,80,${alertPulse})`
   ctx.beginPath()
   ctx.arc(x,y,55+queue.length*3,0,Math.PI*2)
   ctx.fill()
  }
  const grad=ctx.createRadialGradient(x,y-8,0,x,y,35)
  grad.addColorStop(0,'#D06060')
  grad.addColorStop(1,'#B85050')
  ctx.fillStyle=grad
  ctx.beginPath()
  ctx.arc(x,y,35,0,Math.PI*2)
  ctx.fill()
  ctx.strokeStyle='#904040'
  ctx.lineWidth=2
  ctx.stroke()
  ctx.fillStyle='#fff'
  ctx.font='bold 12px sans-serif'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText('USER',x,y-4)
  ctx.font='10px sans-serif'
  ctx.fillText('承認者',x,y+10)
 }

 const drawAgent=(ctx:CanvasRenderingContext2D,agent:MapAgent,pos:AgentPosition,frame:number)=>{
  const{x,y}=pos
  const{type,status,bubble,bubbleType,isSpawning,spawnProgress}=agent
  const config=getAgentDisplayConfig(type)
  ctx.save()
  let alpha=1
  if(isSpawning&&spawnProgress<1){
   alpha=spawnProgress
   const glow=ctx.createRadialGradient(x,y,0,x,y,50)
   glow.addColorStop(0,'rgba(255,255,200,0.6)')
   glow.addColorStop(1,'rgba(255,255,200,0)')
   ctx.fillStyle=glow
   ctx.beginPath()
   ctx.arc(x,y,50*(1-spawnProgress*0.5),0,Math.PI*2)
   ctx.fill()
  }
  ctx.globalAlpha=alpha
  if(status==='failed'||status==='blocked'){
   ctx.globalAlpha=0.5
  }
  if(status==='running'){
   const workGlow=ctx.createRadialGradient(x,y,0,x,y,35)
   const intensity=0.15+Math.sin(frame*0.12)*0.1
   workGlow.addColorStop(0,`rgba(255,200,100,${intensity})`)
   workGlow.addColorStop(1,'rgba(255,200,100,0)')
   ctx.fillStyle=workGlow
   ctx.beginPath()
   ctx.arc(x,y,35,0,Math.PI*2)
   ctx.fill()
  }
  if(status==='waiting_approval'){
   ctx.strokeStyle='#C4956C'
   ctx.lineWidth=2
   ctx.setLineDash([5,3])
   ctx.lineDashOffset=-frame*0.3
   ctx.beginPath()
   ctx.arc(x,y,28,0,Math.PI*2)
   ctx.stroke()
   ctx.setLineDash([])
  }
  const bobY=status==='running'?Math.sin(frame*0.1)*1.5:0
  drawPixelCharacter(ctx,x,y-8+bobY,type,status==='running',frame,0.85)
  ctx.globalAlpha=1
  ctx.fillStyle='#454138'
  ctx.font='9px sans-serif'
  ctx.textAlign='center'
  ctx.fillText(config.label,x,y+20)
  if(status==='pending'){
   ctx.fillStyle='#888'
   ctx.font='italic 8px sans-serif'
   const zOff=Math.sin(frame*0.06)*1.5
   ctx.fillText('zzz',x+15,y-15+zOff)
  }
  if(bubble){
   drawBubble(ctx,x,y-42,bubble,bubbleType,frame)
  }
  ctx.restore()
 }

 const drawBubble=(ctx:CanvasRenderingContext2D,x:number,y:number,text:string,type:string|null,frame:number)=>{
  ctx.save()
  ctx.font='9px sans-serif'
  const displayText=text.length>16?text.slice(0,14)+'…':text
  const w=Math.max(ctx.measureText(displayText).width+12,50)
  const h=18
  const floatY=y+Math.sin(frame*0.06)*1.5
  let bg='#F8F6F0',border='#454138'
  if(type==='success'){bg='#E8F5E9';border='#66A866'}
  if(type==='question'){bg='#FFF8E1';border='#C4956C'}
  if(type==='warning'){bg='#FFEBEE';border='#C06060'}
  ctx.shadowColor='rgba(0,0,0,0.1)'
  ctx.shadowBlur=4
  ctx.shadowOffsetY=2
  ctx.fillStyle=bg
  ctx.strokeStyle=border
  ctx.lineWidth=1
  ctx.beginPath()
  ctx.roundRect(x-w/2,floatY-h/2,w,h,4)
  ctx.fill()
  ctx.shadowBlur=0
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(x-4,floatY+h/2)
  ctx.lineTo(x,floatY+h/2+5)
  ctx.lineTo(x+4,floatY+h/2)
  ctx.closePath()
  ctx.fillStyle=bg
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle='#454138'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText(displayText,x,floatY)
  ctx.restore()
 }

 const drawConnection=(ctx:CanvasRenderingContext2D,from:{x:number,y:number},to:{x:number,y:number},type:string)=>{
  ctx.save()
  let color='#454138',lw=1.5,dash:number[]=[]
  if(type==='instruction'){color='#5588AA';lw=2}
  if(type==='confirm'){color='#C4956C';dash=[6,4]}
  if(type==='delivery'){color='#66A866';lw=2}
  if(type==='ai-request'){color='#8855AA';dash=[3,3]}
  if(type==='user-contact'){color='#C06060';lw=2}
  ctx.strokeStyle=color+'50'
  ctx.lineWidth=lw
  ctx.setLineDash(dash)
  ctx.beginPath()
  ctx.moveTo(from.x,from.y)
  ctx.lineTo(to.x,to.y)
  ctx.stroke()
  ctx.restore()
 }

 const drawPacket=(ctx:CanvasRenderingContext2D,p:DataPacket)=>{
  ctx.save()
  const grad=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,8)
  grad.addColorStop(0,p.color)
  grad.addColorStop(1,p.color+'00')
  ctx.fillStyle=grad
  ctx.beginPath()
  ctx.arc(p.x,p.y,8,0,Math.PI*2)
  ctx.fill()
  ctx.fillStyle='#fff'
  ctx.beginPath()
  ctx.arc(p.x,p.y,3,0,Math.PI*2)
  ctx.fill()
  ctx.restore()
 }

 const drawParticle=(ctx:CanvasRenderingContext2D,p:Particle)=>{
  ctx.save()
  ctx.globalAlpha=p.life/30
  ctx.fillStyle=p.color
  ctx.beginPath()
  ctx.arc(p.x,p.y,p.size*(p.life/30),0,Math.PI*2)
  ctx.fill()
  ctx.restore()
 }

 useEffect(()=>{
  let animId:number
  const loop=()=>{
   const canvas=canvasRef.current
   if(!canvas)return
   const ctx=canvas.getContext('2d')
   if(!ctx)return
   frameRef.current++
   const frame=frameRef.current
   updatePositions(agents)
   updatePackets()
   updateParticles()
   if(frame%20===0){
    connections.forEach(conn=>{
     if(!conn.active)return
     const fromPos=positionsRef.current.get(conn.fromId)
     const toPos=positionsRef.current.get(conn.toId)
     const toAI=aiServices.find(s=>s.id===conn.toId)
     if(!fromPos)return
     let toX=0,toY=0
     if(toPos){toX=toPos.x;toY=toPos.y}
     else if(toAI){toX=toAI.x;toY=toAI.y}
     else if(conn.toId==='user'){toX=user.x;toY=user.y}
     else return
     let color='#454138'
     if(conn.type==='instruction')color='#5588AA'
     if(conn.type==='confirm')color='#C4956C'
     if(conn.type==='delivery')color='#66A866'
     if(conn.type==='ai-request')color='#8855AA'
     if(conn.type==='user-contact')color='#C06060'
     spawnPacket(fromPos.x,fromPos.y,toX,toY,color)
    })
   }
   ctx.fillStyle='#E8E4D4'
   ctx.fillRect(0,0,width,height)
   ctx.save()
   ctx.translate(width/2,height/2)
   ctx.scale(zoom,zoom)
   ctx.translate(-width/2+pan.x,-height/2+pan.y)
   connections.forEach(conn=>{
    if(!conn.active)return
    const fromPos=positionsRef.current.get(conn.fromId)
    const toPos=positionsRef.current.get(conn.toId)
    const toAI=aiServices.find(s=>s.id===conn.toId)
    if(!fromPos)return
    let to={x:0,y:0}
    if(toPos)to={x:toPos.x,y:toPos.y}
    else if(toAI)to={x:toAI.x,y:toAI.y}
    else if(conn.toId==='user')to={x:user.x,y:user.y}
    else return
    drawConnection(ctx,{x:fromPos.x,y:fromPos.y},to,conn.type)
   })
   packetsRef.current.forEach(p=>drawPacket(ctx,p))
   aiServices.forEach(ai=>{
    const count=agents.filter(a=>a.aiTarget===ai.id&&a.status==='running').length
    drawAIService(ctx,ai,frame,count)
   })
   drawUserNode(ctx,user,frame)
   const sorted=[...agents].sort((a,b)=>{
    const pa=positionsRef.current.get(a.id)
    const pb=positionsRef.current.get(b.id)
    return(pa?.y??0)-(pb?.y??0)
   })
   sorted.forEach(agent=>{
    const pos=positionsRef.current.get(agent.id)
    if(pos)drawAgent(ctx,agent,pos,frame)
   })
   particlesRef.current.forEach(p=>drawParticle(ctx,p))
   ctx.restore()
   animId=requestAnimationFrame(loop)
  }
  loop()
  return()=>cancelAnimationFrame(animId)
 },[agents,aiServices,user,connections,width,height,zoom,pan,updatePositions])

 const onWheel=(e:React.WheelEvent)=>{
  e.preventDefault()
  setZoom(z=>Math.max(0.4,Math.min(2.5,z*(e.deltaY>0?0.92:1.08))))
 }
 const onMouseDown=(e:React.MouseEvent)=>{
  setDragging(true)
  setDragStart({x:e.clientX-pan.x,y:e.clientY-pan.y})
 }
 const onMouseMove=(e:React.MouseEvent)=>{
  if(!dragging)return
  setPan({x:e.clientX-dragStart.x,y:e.clientY-dragStart.y})
 }
 const onMouseUp=()=>setDragging(false)

 return(
  <canvas
   ref={canvasRef}
   width={width}
   height={height}
   className="cursor-grab active:cursor-grabbing"
   onWheel={onWheel}
   onMouseDown={onMouseDown}
   onMouseMove={onMouseMove}
   onMouseUp={onMouseUp}
   onMouseLeave={onMouseUp}
  />
 )
}
