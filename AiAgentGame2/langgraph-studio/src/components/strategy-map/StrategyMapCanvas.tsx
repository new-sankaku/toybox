import{useRef,useEffect,useCallback,useState}from'react'
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

const AGENT_SIZE=60
const AI_SERVICE_SIZE=80
const USER_SIZE=70

export default function StrategyMapCanvas({agents,aiServices,user,connections,width,height}:Props){
 const canvasRef=useRef<HTMLCanvasElement>(null)
 const frameRef=useRef(0)
 const [isDragging,setIsDragging]=useState(false)
 const [offset,setOffset]=useState({x:0,y:0})
 const [dragStart,setDragStart]=useState({x:0,y:0})

 const drawAIService=(ctx:CanvasRenderingContext2D,service:AIService,agentsNearby:number)=>{
  const{x,y,name,color}=service
  ctx.save()
  ctx.globalAlpha=0.15
  ctx.fillStyle=color
  ctx.beginPath()
  ctx.arc(x,y,AI_SERVICE_SIZE+20,0,Math.PI*2)
  ctx.fill()
  ctx.globalAlpha=1
  ctx.fillStyle=color
  ctx.beginPath()
  ctx.arc(x,y,AI_SERVICE_SIZE/2,0,Math.PI*2)
  ctx.fill()
  ctx.fillStyle='#E8E4D4'
  ctx.font='bold 14px sans-serif'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText(name,x,y)
  if(agentsNearby>0){
   ctx.fillStyle='#454138'
   ctx.font='12px sans-serif'
   ctx.fillText(`${agentsNearby}`,x,y+AI_SERVICE_SIZE/2+15)
  }
  ctx.restore()
 }

 const drawUser=(ctx:CanvasRenderingContext2D,u:UserNode,_frame:number)=>{
  const{x,y,queue}=u
  ctx.save()
  ctx.fillStyle='#B85C5C'
  ctx.beginPath()
  ctx.arc(x,y,USER_SIZE/2,0,Math.PI*2)
  ctx.fill()
  ctx.fillStyle='#E8E4D4'
  ctx.font='bold 16px sans-serif'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText('USER',x,y)
  if(queue.length>0){
   ctx.fillStyle='#454138'
   ctx.font='11px sans-serif'
   ctx.fillText(`承認待ち: ${queue.length}`,x,y+USER_SIZE/2+12)
  }
  ctx.restore()
 }

 const drawAgent=(ctx:CanvasRenderingContext2D,agent:MapAgent,frame:number)=>{
  const{x,y,type,status,isSpawning,spawnProgress,bubble,bubbleType}=agent
  const config=getAgentDisplayConfig(type)
  ctx.save()
  if(isSpawning){
   ctx.globalAlpha=spawnProgress
   const scale=0.5+spawnProgress*0.5
   ctx.translate(x,y)
   ctx.scale(scale,scale)
   ctx.translate(-x,-y)
  }
  if(status==='blocked'||status==='failed'){
   ctx.globalAlpha=0.4
  }
  const isWorking=status==='running'
  drawPixelCharacter(ctx,x,y-10,type,isWorking,frame,1)
  ctx.globalAlpha=1
  ctx.fillStyle='#454138'
  ctx.font='11px sans-serif'
  ctx.textAlign='center'
  ctx.fillText(config.label,x,y+25)
  if(status==='running'){
   ctx.fillStyle=`rgba(255,200,100,${0.3+Math.sin(frame*0.1)*0.2})`
   ctx.beginPath()
   ctx.arc(x,y,AGENT_SIZE/2+5,0,Math.PI*2)
   ctx.fill()
  }
  if(status==='waiting_approval'){
   ctx.strokeStyle='#C4956C'
   ctx.lineWidth=2
   ctx.setLineDash([4,4])
   ctx.beginPath()
   ctx.arc(x,y,AGENT_SIZE/2+3,0,Math.PI*2)
   ctx.stroke()
   ctx.setLineDash([])
  }
  if(status==='pending'){
   ctx.fillStyle='#5A5548'
   ctx.font='10px sans-serif'
   ctx.fillText('Zzz',x+20,y-20)
  }
  if(bubble){
   drawBubble(ctx,x,y-50,bubble,bubbleType)
  }
  ctx.restore()
 }

 const drawBubble=(ctx:CanvasRenderingContext2D,x:number,y:number,text:string,type:string|null)=>{
  const padding=6
  ctx.font='11px sans-serif'
  const metrics=ctx.measureText(text)
  const w=metrics.width+padding*2
  const h=18
  let bgColor='#E8E4D4'
  let borderColor='#454138'
  if(type==='success'){bgColor='#d4edda';borderColor='#7AAA7A'}
  if(type==='question'){bgColor='#fff3cd';borderColor='#C4956C'}
  if(type==='warning'){bgColor='#f8d7da';borderColor='#B85C5C'}
  ctx.fillStyle=bgColor
  ctx.strokeStyle=borderColor
  ctx.lineWidth=1
  ctx.beginPath()
  ctx.roundRect(x-w/2,y-h/2,w,h,4)
  ctx.fill()
  ctx.stroke()
  ctx.beginPath()
  ctx.moveTo(x-5,y+h/2)
  ctx.lineTo(x,y+h/2+6)
  ctx.lineTo(x+5,y+h/2)
  ctx.closePath()
  ctx.fill()
  ctx.stroke()
  ctx.fillStyle='#454138'
  ctx.textAlign='center'
  ctx.textBaseline='middle'
  ctx.fillText(text,x,y)
 }

 const drawConnection=(ctx:CanvasRenderingContext2D,conn:Connection,agents:MapAgent[],aiServices:AIService[],user:UserNode,_frame:number)=>{
  const{fromId,toId,type,progress,active}=conn
  if(!active)return
  let fromX=0,fromY=0,toX=0,toY=0
  const fromAgent=agents.find(a=>a.id===fromId)
  if(fromAgent){fromX=fromAgent.x;fromY=fromAgent.y}
  const toAgent=agents.find(a=>a.id===toId)
  if(toAgent){toX=toAgent.x;toY=toAgent.y}
  const toAI=aiServices.find(s=>s.id===toId)
  if(toAI){toX=toAI.x;toY=toAI.y}
  if(toId==='user'){toX=user.x;toY=user.y}
  if(fromId==='user'){fromX=user.x;fromY=user.y}
  ctx.save()
  let color='#454138'
  let dash:number[]=[]
  if(type==='instruction'){color='#6B8FAA'}
  if(type==='confirm'){color='#C4956C';dash=[4,4]}
  if(type==='delivery'){color='#7AAA7A'}
  if(type==='ai-request'){color='#9060c0'}
  if(type==='user-contact'){color='#B85C5C'}
  ctx.strokeStyle=color
  ctx.lineWidth=2
  ctx.setLineDash(dash)
  ctx.beginPath()
  ctx.moveTo(fromX,fromY)
  ctx.lineTo(toX,toY)
  ctx.stroke()
  if(progress>0&&progress<1){
   const px=fromX+(toX-fromX)*progress
   const py=fromY+(toY-fromY)*progress
   ctx.fillStyle=color
   ctx.beginPath()
   ctx.arc(px,py,5,0,Math.PI*2)
   ctx.fill()
  }
  ctx.restore()
 }

 const draw=useCallback(()=>{
  const canvas=canvasRef.current
  if(!canvas)return
  const ctx=canvas.getContext('2d')
  if(!ctx)return
  frameRef.current++
  const frame=frameRef.current
  ctx.fillStyle='#E8E4D4'
  ctx.fillRect(0,0,width,height)
  ctx.save()
  ctx.translate(offset.x,offset.y)
  connections.forEach(c=>drawConnection(ctx,c,agents,aiServices,user,frame))
  aiServices.forEach(s=>{
   const nearby=agents.filter(a=>a.aiTarget===s.id).length
   drawAIService(ctx,s,nearby)
  })
  drawUser(ctx,user,frame)
  const sortedAgents=[...agents].sort((a,b)=>a.y-b.y)
  sortedAgents.forEach(a=>drawAgent(ctx,a,frame))
  ctx.restore()
 },[agents,aiServices,user,connections,width,height,offset])

 useEffect(()=>{
  let animationId:number
  const loop=()=>{
   draw()
   animationId=requestAnimationFrame(loop)
  }
  loop()
  return()=>cancelAnimationFrame(animationId)
 },[draw])

 const handleMouseDown=(e:React.MouseEvent)=>{
  setIsDragging(true)
  setDragStart({x:e.clientX-offset.x,y:e.clientY-offset.y})
 }

 const handleMouseMove=(e:React.MouseEvent)=>{
  if(!isDragging)return
  setOffset({x:e.clientX-dragStart.x,y:e.clientY-dragStart.y})
 }

 const handleMouseUp=()=>{
  setIsDragging(false)
 }

 return(
  <canvas
   ref={canvasRef}
   width={width}
   height={height}
   className="cursor-grab active:cursor-grabbing"
   onMouseDown={handleMouseDown}
   onMouseMove={handleMouseMove}
   onMouseUp={handleMouseUp}
   onMouseLeave={handleMouseUp}
  />
 )
}
