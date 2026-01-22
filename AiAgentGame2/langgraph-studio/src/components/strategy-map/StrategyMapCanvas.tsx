import{useRef,useEffect,useState}from'react'
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

interface Particle{
 x:number
 y:number
 vx:number
 vy:number
 life:number
 maxLife:number
 color:string
 size:number
}

interface Packet{
 id:string
 fromX:number
 fromY:number
 toX:number
 toY:number
 progress:number
 speed:number
 color:string
 trail:Array<{x:number,y:number,alpha:number}>
}

const AGENT_SIZE=50
const AI_SERVICE_RADIUS=45
const USER_RADIUS=40
const SPRING_STRENGTH=0.02
const DAMPING=0.85
const REPULSION=800
const MIN_DISTANCE=70

export default function StrategyMapCanvas({agents,aiServices,user,connections,width,height}:Props){
 const canvasRef=useRef<HTMLCanvasElement>(null)
 const frameRef=useRef(0)
 const particlesRef=useRef<Particle[]>([])
 const packetsRef=useRef<Packet[]>([])
 const positionsRef=useRef<Map<string,{x:number,y:number,vx:number,vy:number}>>(new Map())
 const [zoom,setZoom]=useState(1)
 const [offset,setOffset]=useState({x:0,y:0})
 const [isDragging,setIsDragging]=useState(false)
 const [dragStart,setDragStart]=useState({x:0,y:0})
 const lastPacketTimeRef=useRef<Map<string,number>>(new Map())

 const getTargetPosition=(agent:MapAgent,allAgents:MapAgent[],aiSvcs:AIService[],usr:UserNode):{x:number,y:number}=>{
  if(agent.status==='waiting_approval'){
   const waitingAgents=allAgents.filter(a=>a.status==='waiting_approval')
   const idx=waitingAgents.findIndex(a=>a.id===agent.id)
   const queueStartX=usr.x-((waitingAgents.length-1)*45)/2
   return{x:queueStartX+idx*45,y:usr.y-90}
  }
  if(agent.aiTarget&&agent.status==='running'){
   const ai=aiSvcs.find(s=>s.id===agent.aiTarget)
   if(ai){
    const agentsAtAI=allAgents.filter(a=>a.aiTarget===agent.aiTarget&&a.status==='running')
    const idx=agentsAtAI.findIndex(a=>a.id===agent.id)
    const angle=(idx/(agentsAtAI.length||1))*Math.PI*2-Math.PI/2
    const radius=AI_SERVICE_RADIUS+50+idx*15
    return{x:ai.x+Math.cos(angle)*radius,y:ai.y+Math.sin(angle)*radius+30}
   }
  }
  if(agent.parentId){
   const parent=allAgents.find(a=>a.id===agent.parentId)
   if(parent){
    const siblings=allAgents.filter(a=>a.parentId===agent.parentId)
    const idx=siblings.findIndex(a=>a.id===agent.id)
    const parentPos=positionsRef.current.get(parent.id)
    const px=parentPos?.x??width/2
    const py=parentPos?.y??height/2
    const angle=((idx+1)/(siblings.length+1))*Math.PI-Math.PI/2
    return{x:px+Math.cos(angle)*120,y:py+Math.sin(angle)*80+100}
   }
  }
  const leaders=allAgents.filter(a=>!a.parentId)
  const idx=leaders.findIndex(a=>a.id===agent.id)
  const spacing=Math.min(200,width/(leaders.length+1))
  return{x:spacing*(idx+1),y:height*0.4}
 }

 const updatePhysics=(allAgents:MapAgent[],aiSvcs:AIService[],usr:UserNode)=>{
  allAgents.forEach(agent=>{
   if(!positionsRef.current.has(agent.id)){
    const target=getTargetPosition(agent,allAgents,aiSvcs,usr)
    positionsRef.current.set(agent.id,{x:target.x,y:target.y,vx:0,vy:0})
   }
  })
  const toRemove:string[]=[]
  positionsRef.current.forEach((_,id)=>{
   if(!allAgents.find(a=>a.id===id))toRemove.push(id)
  })
  toRemove.forEach(id=>positionsRef.current.delete(id))
  allAgents.forEach(agent=>{
   const pos=positionsRef.current.get(agent.id)
   if(!pos)return
   const target=getTargetPosition(agent,allAgents,aiSvcs,usr)
   let fx=(target.x-pos.x)*SPRING_STRENGTH
   let fy=(target.y-pos.y)*SPRING_STRENGTH
   allAgents.forEach(other=>{
    if(other.id===agent.id)return
    const otherPos=positionsRef.current.get(other.id)
    if(!otherPos)return
    const dx=pos.x-otherPos.x
    const dy=pos.y-otherPos.y
    const dist=Math.sqrt(dx*dx+dy*dy)||1
    if(dist<MIN_DISTANCE){
     const force=REPULSION/(dist*dist)
     fx+=dx/dist*force
     fy+=dy/dist*force
    }
   })
   pos.vx=(pos.vx+fx)*DAMPING
   pos.vy=(pos.vy+fy)*DAMPING
   pos.x+=pos.vx
   pos.y+=pos.vy
   pos.x=Math.max(50,Math.min(width-50,pos.x))
   pos.y=Math.max(100,Math.min(height-80,pos.y))
  })
 }

 const spawnParticles=(x:number,y:number,color:string,count:number)=>{
  for(let i=0;i<count;i++){
   const angle=Math.random()*Math.PI*2
   const speed=1+Math.random()*3
   particlesRef.current.push({
    x,y,
    vx:Math.cos(angle)*speed,
    vy:Math.sin(angle)*speed,
    life:30+Math.random()*20,
    maxLife:50,
    color,
    size:2+Math.random()*3
   })
  }
 }

 const updateParticles=()=>{
  particlesRef.current=particlesRef.current.filter(p=>{
   p.x+=p.vx
   p.y+=p.vy
   p.vy+=0.1
   p.life--
   return p.life>0
  })
 }

 const spawnPacket=(fromX:number,fromY:number,toX:number,toY:number,color:string,id:string)=>{
  const now=Date.now()
  const lastTime=lastPacketTimeRef.current.get(id)||0
  if(now-lastTime<200)return
  lastPacketTimeRef.current.set(id,now)
  packetsRef.current.push({
   id:`${id}-${now}`,
   fromX,fromY,toX,toY,
   progress:0,
   speed:0.015+Math.random()*0.01,
   color,
   trail:[]
  })
 }

 const updatePackets=()=>{
  packetsRef.current=packetsRef.current.filter(p=>{
   p.progress+=p.speed
   const x=p.fromX+(p.toX-p.fromX)*p.progress
   const y=p.fromY+(p.toY-p.fromY)*p.progress
   p.trail.unshift({x,y,alpha:1})
   if(p.trail.length>15)p.trail.pop()
   p.trail.forEach((t,i)=>{t.alpha=1-i/15})
   if(p.progress>=1){
    spawnParticles(p.toX,p.toY,p.color,5)
    return false
   }
   return true
  })
 }

 const drawAIService=(ctx:CanvasRenderingContext2D,service:AIService,frame:number,agentCount:number)=>{
  const{x,y,name,color}=service
  ctx.save()
  const pulse=1+Math.sin(frame*0.05)*0.05
  const glowRadius=AI_SERVICE_RADIUS+20+agentCount*5
  const gradient=ctx.createRadialGradient(x,y,AI_SERVICE_RADIUS,x,y,glowRadius)
  gradient.addColorStop(0,color+'40')
  gradient.addColorStop(1,color+'00')
  ctx.fillStyle=gradient
  ctx.beginPath()
  ctx.arc(x,y,glowRadius*pulse,0,Math.PI*2)
  ctx.fill()
  ctx.fillStyle=color
  ctx.beginPath()
  ctx.arc(x,y,AI_SERVICE_RADIUS,0,Math.PI*2)
  ctx.fill()
  ctx.strokeStyle=color
  ctx.lineWidth=2
  ctx.beginPath()
  ctx.arc(x,y,AI_SERVICE_RADIUS+8+Math.sin(frame*0.03)*3,0,Math.PI*2)
  ctx.stroke()
  ctx.fillStyle='#E8E4D4'
  ctx.font='bold 14px sans-serif'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText(name,x,y)
  if(agentCount>0){
   ctx.fillStyle='#ffffff'
   ctx.font='bold 11px sans-serif'
   ctx.beginPath()
   ctx.arc(x+AI_SERVICE_RADIUS-5,y-AI_SERVICE_RADIUS+5,12,0,Math.PI*2)
   ctx.fillStyle=color
   ctx.fill()
   ctx.fillStyle='#ffffff'
   ctx.fillText(`${agentCount}`,x+AI_SERVICE_RADIUS-5,y-AI_SERVICE_RADIUS+6)
  }
  ctx.restore()
 }

 const drawUser=(ctx:CanvasRenderingContext2D,u:UserNode,frame:number)=>{
  const{x,y,queue}=u
  ctx.save()
  if(queue.length>0){
   const alertPulse=0.3+Math.sin(frame*0.1)*0.2
   ctx.fillStyle=`rgba(184,92,92,${alertPulse})`
   ctx.beginPath()
   ctx.arc(x,y,USER_RADIUS+20+queue.length*3,0,Math.PI*2)
   ctx.fill()
  }
  const gradient=ctx.createRadialGradient(x,y-10,0,x,y,USER_RADIUS)
  gradient.addColorStop(0,'#C97070')
  gradient.addColorStop(1,'#B85C5C')
  ctx.fillStyle=gradient
  ctx.beginPath()
  ctx.arc(x,y,USER_RADIUS,0,Math.PI*2)
  ctx.fill()
  ctx.strokeStyle='#9A4A4A'
  ctx.lineWidth=3
  ctx.stroke()
  ctx.fillStyle='#E8E4D4'
  ctx.font='bold 14px sans-serif'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText('USER',x,y-5)
  ctx.font='11px sans-serif'
  ctx.fillText('承認者',x,y+10)
  if(queue.length>0){
   ctx.fillStyle='#454138'
   ctx.font='bold 11px sans-serif'
   const queueText=`待機中: ${queue.length}`
   ctx.fillText(queueText,x,y+USER_RADIUS+18)
  }
  ctx.restore()
 }

 const drawAgent=(ctx:CanvasRenderingContext2D,agent:MapAgent,pos:{x:number,y:number},frame:number)=>{
  const{type,status,isSpawning,spawnProgress,bubble,bubbleType}=agent
  const{x,y}=pos
  const config=getAgentDisplayConfig(type)
  ctx.save()
  if(isSpawning&&spawnProgress<1){
   ctx.globalAlpha=spawnProgress
   const scale=0.3+spawnProgress*0.7
   ctx.translate(x,y)
   ctx.scale(scale,scale)
   ctx.translate(-x,-y)
   const spawnGlow=ctx.createRadialGradient(x,y,0,x,y,60)
   spawnGlow.addColorStop(0,'rgba(255,255,200,0.8)')
   spawnGlow.addColorStop(1,'rgba(255,255,200,0)')
   ctx.fillStyle=spawnGlow
   ctx.beginPath()
   ctx.arc(x,y,60,0,Math.PI*2)
   ctx.fill()
  }
  if(status==='blocked'||status==='failed'){
   ctx.globalAlpha=0.5
   ctx.filter='grayscale(70%)'
  }
  if(status==='running'){
   const workGlow=ctx.createRadialGradient(x,y,0,x,y,AGENT_SIZE)
   const glowIntensity=0.2+Math.sin(frame*0.15)*0.15
   workGlow.addColorStop(0,`rgba(255,200,100,${glowIntensity})`)
   workGlow.addColorStop(1,'rgba(255,200,100,0)')
   ctx.fillStyle=workGlow
   ctx.beginPath()
   ctx.arc(x,y,AGENT_SIZE,0,Math.PI*2)
   ctx.fill()
  }
  if(status==='waiting_approval'){
   ctx.strokeStyle='#C4956C'
   ctx.lineWidth=2
   ctx.setLineDash([6,4])
   const dashOffset=frame*0.5
   ctx.lineDashOffset=-dashOffset
   ctx.beginPath()
   ctx.arc(x,y,AGENT_SIZE/2+8,0,Math.PI*2)
   ctx.stroke()
   ctx.setLineDash([])
  }
  const isWorking=status==='running'
  const bobY=isWorking?Math.sin(frame*0.1)*2:0
  drawPixelCharacter(ctx,x,y-12+bobY,type,isWorking,frame,0.9)
  ctx.globalAlpha=1
  ctx.filter='none'
  ctx.fillStyle='#454138'
  ctx.font='10px sans-serif'
  ctx.textAlign='center'
  ctx.fillText(config.label,x,y+22)
  if(status==='pending'){
   ctx.fillStyle='#5A5548'
   ctx.font='italic 9px sans-serif'
   const zzzOffset=Math.sin(frame*0.08)*2
   ctx.fillText('zzz',x+18,y-18+zzzOffset)
  }
  if(bubble){
   drawBubble(ctx,x,y-45,bubble,bubbleType,frame)
  }
  ctx.restore()
 }

 const drawBubble=(ctx:CanvasRenderingContext2D,x:number,y:number,text:string,type:string|null,frame:number)=>{
  const padding=8
  ctx.font='10px sans-serif'
  const metrics=ctx.measureText(text)
  const w=Math.min(metrics.width+padding*2,120)
  const h=20
  const floatY=y+Math.sin(frame*0.08)*2
  let bgColor='#F5F2E8'
  let borderColor='#454138'
  let shadowColor='rgba(0,0,0,0.1)'
  if(type==='success'){bgColor='#E8F5E9';borderColor='#7AAA7A';shadowColor='rgba(122,170,122,0.2)'}
  if(type==='question'){bgColor='#FFF8E1';borderColor='#C4956C';shadowColor='rgba(196,149,108,0.2)'}
  if(type==='warning'){bgColor='#FFEBEE';borderColor='#B85C5C';shadowColor='rgba(184,92,92,0.2)'}
  ctx.save()
  ctx.shadowColor=shadowColor
  ctx.shadowBlur=8
  ctx.shadowOffsetY=2
  ctx.fillStyle=bgColor
  ctx.strokeStyle=borderColor
  ctx.lineWidth=1.5
  ctx.beginPath()
  ctx.roundRect(x-w/2,floatY-h/2,w,h,6)
  ctx.fill()
  ctx.shadowBlur=0
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(x-6,floatY+h/2)
  ctx.lineTo(x,floatY+h/2+8)
  ctx.lineTo(x+6,floatY+h/2)
  ctx.closePath()
  ctx.fillStyle=bgColor
  ctx.fill()
  ctx.strokeStyle=borderColor
  ctx.beginPath()
  ctx.moveTo(x-6,floatY+h/2)
  ctx.lineTo(x,floatY+h/2+8)
  ctx.lineTo(x+6,floatY+h/2)
  ctx.stroke()
  ctx.fillStyle='#454138'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  const displayText=text.length>14?text.slice(0,12)+'…':text
  ctx.fillText(displayText,x,floatY)
  ctx.restore()
 }

 const drawConnection=(ctx:CanvasRenderingContext2D,fromX:number,fromY:number,toX:number,toY:number,type:string,_frame:number)=>{
  ctx.save()
  let color='#454138'
  let lineWidth=1.5
  let dash:number[]=[]
  if(type==='instruction'){color='#6B8FAA';lineWidth=2}
  if(type==='confirm'){color='#C4956C';dash=[8,4]}
  if(type==='delivery'){color='#7AAA7A';lineWidth=2.5}
  if(type==='ai-request'){color='#9060c0';lineWidth=1.5;dash=[4,4]}
  if(type==='user-contact'){color='#B85C5C';lineWidth=2}
  ctx.strokeStyle=color+'60'
  ctx.lineWidth=lineWidth
  ctx.setLineDash(dash)
  ctx.beginPath()
  ctx.moveTo(fromX,fromY)
  ctx.lineTo(toX,toY)
  ctx.stroke()
  ctx.restore()
 }

 const drawPackets=(ctx:CanvasRenderingContext2D)=>{
  packetsRef.current.forEach(p=>{
   ctx.save()
   p.trail.forEach((t,i)=>{
    ctx.fillStyle=p.color+Math.floor(t.alpha*180).toString(16).padStart(2,'0')
    ctx.beginPath()
    ctx.arc(t.x,t.y,4-i*0.2,0,Math.PI*2)
    ctx.fill()
   })
   const x=p.fromX+(p.toX-p.fromX)*p.progress
   const y=p.fromY+(p.toY-p.fromY)*p.progress
   const glow=ctx.createRadialGradient(x,y,0,x,y,12)
   glow.addColorStop(0,p.color)
   glow.addColorStop(1,p.color+'00')
   ctx.fillStyle=glow
   ctx.beginPath()
   ctx.arc(x,y,12,0,Math.PI*2)
   ctx.fill()
   ctx.fillStyle='#ffffff'
   ctx.beginPath()
   ctx.arc(x,y,4,0,Math.PI*2)
   ctx.fill()
   ctx.restore()
  })
 }

 const drawParticles=(ctx:CanvasRenderingContext2D)=>{
  particlesRef.current.forEach(p=>{
   ctx.save()
   ctx.globalAlpha=p.life/p.maxLife
   ctx.fillStyle=p.color
   ctx.beginPath()
   ctx.arc(p.x,p.y,p.size*(p.life/p.maxLife),0,Math.PI*2)
   ctx.fill()
   ctx.restore()
  })
 }

 useEffect(()=>{
  let animationId:number
  const loop=()=>{
   const canvas=canvasRef.current
   if(!canvas)return
   const ctx=canvas.getContext('2d')
   if(!ctx)return
   frameRef.current++
   const frame=frameRef.current
   updatePhysics(agents,aiServices,user)
   updateParticles()
   updatePackets()
   connections.forEach(conn=>{
    if(!conn.active)return
    const fromPos=positionsRef.current.get(conn.fromId)
    const toAgent=agents.find(a=>a.id===conn.toId)
    const toPos=toAgent?positionsRef.current.get(conn.toId):null
    const toAI=aiServices.find(s=>s.id===conn.toId)
    let fromX=fromPos?.x??0,fromY=fromPos?.y??0
    let toX=0,toY=0
    if(toPos){toX=toPos.x;toY=toPos.y}
    if(toAI){toX=toAI.x;toY=toAI.y}
    if(conn.toId==='user'){toX=user.x;toY=user.y}
    if(fromX&&toX&&Math.random()<0.03){
     let color='#454138'
     if(conn.type==='instruction')color='#6B8FAA'
     if(conn.type==='confirm')color='#C4956C'
     if(conn.type==='delivery')color='#7AAA7A'
     if(conn.type==='ai-request')color='#9060c0'
     if(conn.type==='user-contact')color='#B85C5C'
     spawnPacket(fromX,fromY,toX,toY,color,conn.id)
    }
   })
   ctx.fillStyle='#E8E4D4'
   ctx.fillRect(0,0,width,height)
   ctx.save()
   ctx.translate(width/2,height/2)
   ctx.scale(zoom,zoom)
   ctx.translate(-width/2+offset.x,-height/2+offset.y)
   connections.forEach(conn=>{
    if(!conn.active)return
    const fromPos=positionsRef.current.get(conn.fromId)
    const toAgent=agents.find(a=>a.id===conn.toId)
    const toPos=toAgent?positionsRef.current.get(conn.toId):null
    const toAI=aiServices.find(s=>s.id===conn.toId)
    let fromX=fromPos?.x??0,fromY=fromPos?.y??0
    let toX=0,toY=0
    if(toPos){toX=toPos.x;toY=toPos.y}
    if(toAI){toX=toAI.x;toY=toAI.y}
    if(conn.toId==='user'){toX=user.x;toY=user.y}
    if(fromX&&toX){
     drawConnection(ctx,fromX,fromY,toX,toY,conn.type,frame)
    }
   })
   drawPackets(ctx)
   aiServices.forEach(s=>{
    const count=agents.filter(a=>a.aiTarget===s.id&&a.status==='running').length
    drawAIService(ctx,s,frame,count)
   })
   drawUser(ctx,user,frame)
   const sortedAgents=[...agents].sort((a,b)=>{
    const posA=positionsRef.current.get(a.id)
    const posB=positionsRef.current.get(b.id)
    return(posA?.y??0)-(posB?.y??0)
   })
   sortedAgents.forEach(agent=>{
    const pos=positionsRef.current.get(agent.id)
    if(pos)drawAgent(ctx,agent,pos,frame)
   })
   drawParticles(ctx)
   ctx.restore()
   animationId=requestAnimationFrame(loop)
  }
  loop()
  return()=>cancelAnimationFrame(animationId)
 },[agents,aiServices,user,connections,width,height,zoom,offset])

 const handleWheel=(e:React.WheelEvent)=>{
  e.preventDefault()
  const delta=e.deltaY>0?0.9:1.1
  setZoom(z=>Math.max(0.5,Math.min(2,z*delta)))
 }

 const handleMouseDown=(e:React.MouseEvent)=>{
  setIsDragging(true)
  setDragStart({x:e.clientX-offset.x,y:e.clientY-offset.y})
 }

 const handleMouseMove=(e:React.MouseEvent)=>{
  if(!isDragging)return
  setOffset({x:e.clientX-dragStart.x,y:e.clientY-dragStart.y})
 }

 const handleMouseUp=()=>setIsDragging(false)

 return(
  <canvas
   ref={canvasRef}
   width={width}
   height={height}
   className="cursor-grab active:cursor-grabbing"
   onWheel={handleWheel}
   onMouseDown={handleMouseDown}
   onMouseMove={handleMouseMove}
   onMouseUp={handleMouseUp}
   onMouseLeave={handleMouseUp}
  />
 )
}
