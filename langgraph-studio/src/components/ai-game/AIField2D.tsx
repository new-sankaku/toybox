import{useRef,useEffect,useCallback,useState,useMemo}from'react'
import type{CharacterState,AIServiceType}from'./types'
import{DEFAULT_SERVICE_CONFIG}from'./types'
import{drawPixelCharacter}from'./pixelCharacters'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'

interface AIField2DProps{
 characters:CharacterState[]
 onCharacterClick?:(character:CharacterState)=>void
 characterScale?:number
}

const NIER_COLORS={
 background:'#d4cdb8',
 backgroundDark:'#c4bda8',
 primary:'#4a4540',
 primaryDim:'#6a655a',
 accent:'#b5a078',
 accentBright:'#c4a574',
 textMain:'#4a4540',
 textDim:'#7a756a'
}

interface CharacterPosition{
 x:number
 y:number
 targetX:number
 targetY:number
 wanderTimer:number
 rotation:number
 wasWorking:boolean
}

export function AIField2D({characters,onCharacterClick,characterScale=1.0}:AIField2DProps):JSX.Element{
 const canvasRef=useRef<HTMLCanvasElement>(null)
 const containerRef=useRef<HTMLDivElement>(null)
 const[dimensions,setDimensions]=useState({width:800,height:500})
 const positionsRef=useRef<Map<string,CharacterPosition>>(new Map())
 const frameRef=useRef<number>(0)
 const animationRef=useRef<number>(0)
 const prevDimensionsRef=useRef({width:0,height:0})

 const{services,fetchServices,loaded}=useAIServiceStore()
 const{getLabel}=useAgentDefinitionStore()

 useEffect(()=>{
  fetchServices()
 },[fetchServices])

 const SERVICE_CONFIG=useMemo(()=>{
  if(!loaded)return DEFAULT_SERVICE_CONFIG
  return services
 },[services,loaded])

 const ROOM_X=0.60
 const ROOM_WIDTH=0.38
 const PLATFORM_X=0.03
 const PLATFORM_WIDTH=0.35

 useEffect(()=>{
  const container=containerRef.current
  const canvas=canvasRef.current
  if(!container||!canvas)return

  const updateDimensions=()=>{
   const rect=container.getBoundingClientRect()
   if(rect.width===0||rect.height===0)return

   const dpr=window.devicePixelRatio||1

   canvas.width=rect.width*dpr
   canvas.height=rect.height*dpr

   canvas.style.width=`${rect.width}px`
   canvas.style.height=`${rect.height}px`

   const ctx=canvas.getContext('2d')
   if(ctx){
    ctx.scale(dpr,dpr)
   }

   setDimensions({width:rect.width,height:rect.height})
  }

  const resizeObserver=new ResizeObserver(()=>{
   updateDimensions()
  })
  resizeObserver.observe(container)

  return()=>{
   resizeObserver.disconnect()
  }
 },[])

 useEffect(()=>{
  const positions=positionsRef.current
  const roomStartX=dimensions.width*ROOM_X
  const roomWidth=dimensions.width*ROOM_WIDTH
  const topY=dimensions.height*0.06
  const totalHeight=dimensions.height*0.88

  const dimensionsChanged=prevDimensionsRef.current.width!==dimensions.width||
   prevDimensionsRef.current.height!==dimensions.height
  prevDimensionsRef.current={width:dimensions.width,height:dimensions.height}

  const currentAgentIds=new Set(characters.map(c=>c.agentId))
  for(const agentId of positions.keys()){
   if(!currentAgentIds.has(agentId)){
    positions.delete(agentId)
   }
  }

  const spriteSize=56*characterScale
  const sortedChars=[...characters].sort((a,b)=>(a.phase??0)-(b.phase??0)||(a.agentType<b.agentType?-1:1))
  const agentIndexMap=new Map<string,number>()
  sortedChars.forEach((c,i)=>agentIndexMap.set(c.agentId,i))
  const gridCols=Math.max(1,Math.floor((roomWidth-30)/(spriteSize+10)))
  const gridRows=Math.max(Math.ceil(sortedChars.length/gridCols),4)
  const cellWidth=(roomWidth-30)/gridCols
  const cellHeight=(totalHeight-50)/gridRows

  characters.forEach((char)=>{
   const idx=agentIndexMap.get(char.agentId)??0
   const col=idx%gridCols
   const row=Math.floor(idx/gridCols)
   const x=roomStartX+20+col*cellWidth+cellWidth/2
   const y=topY+35+row*cellHeight+cellHeight/2

   const existing=positions.get(char.agentId)
   if(existing){
    if(dimensionsChanged){
     existing.x=x
     existing.y=y
     existing.targetX=x
     existing.targetY=y
    }
   }else{
    positions.set(char.agentId,{
     x,y,
     targetX:x,
     targetY:y,
     wanderTimer:0,
     rotation:0,
     wasWorking:false
    })
   }
  })
 },[characters,dimensions,characterScale])


 const drawPlatform=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,
  y:number,
  width:number,
  height:number,
  serviceType:AIServiceType,
  hasWorkers:boolean,
  frame:number
):{centerX:number;centerY:number}=>{
  const config=SERVICE_CONFIG[serviceType]

  ctx.fillStyle=hasWorkers?NIER_COLORS.backgroundDark : NIER_COLORS.background
  ctx.fillRect(x,y,width,height)

  ctx.strokeStyle=hasWorkers?NIER_COLORS.accent : NIER_COLORS.primaryDim
  ctx.lineWidth=hasWorkers?2 : 1
  ctx.strokeRect(x,y,width,height)

  const cs=8
  ctx.fillStyle=hasWorkers?NIER_COLORS.accent : NIER_COLORS.primary
  ctx.fillRect(x,y,cs,2)
  ctx.fillRect(x,y,2,cs)
  ctx.fillRect(x+width-cs,y,cs,2)
  ctx.fillRect(x+width-2,y,2,cs)
  ctx.fillRect(x,y+height-2,cs,2)
  ctx.fillRect(x,y+height-cs,2,cs)
  ctx.fillRect(x+width-cs,y+height-2,cs,2)
  ctx.fillRect(x+width-2,y+height-cs,2,cs)

  ctx.fillStyle=NIER_COLORS.textMain
  ctx.font='bold 13px "Courier New", monospace'
  ctx.textAlign='left'
  ctx.fillText(serviceType.toUpperCase(),x+12,y+20)

  ctx.font='10px "Courier New", monospace'
  ctx.fillStyle=NIER_COLORS.textDim
  ctx.fillText(config.description,x+12,y+36)

  const indicatorY=y+height-15
  if(hasWorkers){
   ctx.shadowColor=NIER_COLORS.accent
   ctx.shadowBlur=8+Math.sin(frame*0.1)*4
  }
  ctx.beginPath()
  ctx.arc(x+width/2,indicatorY,4,0,Math.PI*2)
  ctx.fillStyle=hasWorkers?NIER_COLORS.accent : NIER_COLORS.primaryDim
  ctx.fill()
  ctx.shadowBlur=0

  if(hasWorkers){
   const barW=width-30
   const barX=x+15
   const barY=y+height-30
   ctx.fillStyle=NIER_COLORS.primaryDim
   ctx.fillRect(barX,barY,barW,3)
   ctx.fillStyle=NIER_COLORS.accent
   ctx.fillRect(barX,barY,barW*((Math.sin(frame*0.05)+1)/2),3)
  }

  return{centerX:x+width/2,centerY:y+height/2}
 },[SERVICE_CONFIG])

 const drawRoom=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,
  y:number,
  width:number,
  height:number
)=>{
  ctx.fillStyle=NIER_COLORS.backgroundDark
  ctx.fillRect(x,y,width,height)

  ctx.strokeStyle=NIER_COLORS.primary
  ctx.lineWidth=2
  ctx.strokeRect(x,y,width,height)

  const cl=15
  ctx.fillStyle=NIER_COLORS.primary
  ctx.fillRect(x,y,cl,2)
  ctx.fillRect(x,y,2,cl)
  ctx.fillRect(x+width-cl,y,cl,2)
  ctx.fillRect(x+width-2,y,2,cl)
  ctx.fillRect(x,y+height-2,cl,2)
  ctx.fillRect(x,y+height-cl,2,cl)
  ctx.fillRect(x+width-cl,y+height-2,cl,2)
  ctx.fillRect(x+width-2,y+height-cl,2,cl)

  ctx.fillStyle=NIER_COLORS.textMain
  ctx.font='bold 11px "Courier New", monospace'
  ctx.textAlign='center'
  ctx.fillText('[ AGENTS ]',x+width/2,y+15)
 },[])

 const drawUserArea=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,
  y:number,
  width:number,
  height:number,
  hasWaiting:boolean,
  frame:number
)=>{
  ctx.fillStyle=hasWaiting?NIER_COLORS.backgroundDark : NIER_COLORS.background
  ctx.fillRect(x,y,width,height)

  ctx.strokeStyle=hasWaiting?NIER_COLORS.accent : NIER_COLORS.primaryDim
  ctx.lineWidth=hasWaiting?2 : 1
  ctx.strokeRect(x,y,width,height)

  const cs=8
  ctx.fillStyle=hasWaiting?NIER_COLORS.accent : NIER_COLORS.primary
  ctx.fillRect(x,y,cs,2)
  ctx.fillRect(x,y,2,cs)
  ctx.fillRect(x+width-cs,y,cs,2)
  ctx.fillRect(x+width-2,y,2,cs)
  ctx.fillRect(x,y+height-2,cs,2)
  ctx.fillRect(x,y+height-cs,2,cs)
  ctx.fillRect(x+width-cs,y+height-2,cs,2)
  ctx.fillRect(x+width-2,y+height-cs,2,cs)

  ctx.fillStyle=NIER_COLORS.textMain
  ctx.font='bold 13px "Courier New", monospace'
  ctx.textAlign='left'
  ctx.fillText('USER',x+12,y+20)

  ctx.font='10px "Courier New", monospace'
  ctx.fillStyle=NIER_COLORS.textDim
  ctx.fillText('承認待ち',x+12,y+36)

  const indicatorY=y+height-15
  if(hasWaiting){
   ctx.shadowColor=NIER_COLORS.accent
   ctx.shadowBlur=8+Math.sin(frame*0.1)*4
  }
  ctx.beginPath()
  ctx.arc(x+width/2,indicatorY,4,0,Math.PI*2)
  ctx.fillStyle=hasWaiting?NIER_COLORS.accent : NIER_COLORS.primaryDim
  ctx.fill()
  ctx.shadowBlur=0

  if(hasWaiting){
   const barW=width-30
   const barX=x+15
   const barY=y+height-30
   ctx.fillStyle=NIER_COLORS.primaryDim
   ctx.fillRect(barX,barY,barW,3)
   ctx.fillStyle=NIER_COLORS.accent
   ctx.fillRect(barX,barY,barW*((Math.sin(frame*0.05)+1)/2),3)
  }
 },[])

 const drawDataLine=useCallback((
  ctx:CanvasRenderingContext2D,
  platformRight:number,
  platformCenterY:number,
  roomLeft:number,
  roomCenterY:number,
  frame:number
)=>{
  ctx.strokeStyle=NIER_COLORS.primaryDim
  ctx.lineWidth=2
  ctx.setLineDash([])
  ctx.beginPath()
  ctx.moveTo(platformRight,platformCenterY)
  ctx.lineTo(roomLeft,roomCenterY)
  ctx.stroke()

  const dx=roomLeft-platformRight
  const dy=roomCenterY-platformCenterY

  const packetsToApi=4
  for(let i=0;i<packetsToApi;i++){
   const t=((frame*0.015+i/packetsToApi)%1)
   const px=roomLeft-dx*t
   const py=roomCenterY-dy*t

   ctx.fillStyle=NIER_COLORS.accent
   ctx.beginPath()
   ctx.arc(px,py,4,0,Math.PI*2)
   ctx.fill()
  }

  const packetsFromApi=4
  for(let i=0;i<packetsFromApi;i++){
   const t=((frame*0.012+i/packetsFromApi+0.5)%1)
   const px=platformRight+dx*t
   const py=platformCenterY+dy*t

   ctx.fillStyle='#7a7a7a'
   ctx.beginPath()
   ctx.rect(px-3,py-3,6,6)
   ctx.fill()
  }
 },[])

 const drawSpeechBubble=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,
  y:number,
  text:string,
  direction:'top-right'|'top-left'|'bottom-right'|'bottom-left'='top-right'
)=>{
  ctx.font='11px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'

  const padding=6
  const lineHeight=14
  const maxLineWidth=240

  let lines:string[]=[]
  const textWidth=ctx.measureText(text).width
  if(textWidth<=maxLineWidth){
   lines=[text]
  }else{
   let currentLine=''
   for(const char of text.split('')){
    const testLine=currentLine+char
    if(ctx.measureText(testLine).width>maxLineWidth){
     if(currentLine)lines.push(currentLine)
     currentLine=char
    }else{
     currentLine=testLine
    }
   }
   if(currentLine)lines.push(currentLine)
   if(lines.length>2){
    lines=lines.slice(0,2)
    lines[1]=lines[1].slice(0,-3)+'...'
   }
  }

  const actualTextWidth=Math.max(...lines.map(l=>ctx.measureText(l).width))
  const bubbleWidth=actualTextWidth+padding*2+4
  const bubbleHeight=lines.length*lineHeight+padding*2
  const offset=30

  let bubbleX:number,bubbleY:number
  if(direction==='top-right'){
   bubbleX=Math.round(x+offset)
   bubbleY=Math.round(y-bubbleHeight-15)
  }else if(direction==='top-left'){
   bubbleX=Math.round(x-bubbleWidth-offset)
   bubbleY=Math.round(y-bubbleHeight-15)
  }else if(direction==='bottom-right'){
   bubbleX=Math.round(x+offset)
   bubbleY=Math.round(y+25)
  }else{
   bubbleX=Math.round(x-bubbleWidth-offset)
   bubbleY=Math.round(y+25)
  }

  ctx.fillStyle='#e8e4d8'
  ctx.fillRect(bubbleX,bubbleY,bubbleWidth,bubbleHeight)

  ctx.strokeStyle='#8a8070'
  ctx.lineWidth=1
  ctx.strokeRect(bubbleX+0.5,bubbleY+0.5,bubbleWidth-1,bubbleHeight-1)

  ctx.fillStyle='#e8e4d8'
  ctx.beginPath()
  if(direction==='top-right'){
   ctx.moveTo(bubbleX,bubbleY+bubbleHeight)
   ctx.lineTo(x+15,y-5)
   ctx.lineTo(bubbleX+15,bubbleY+bubbleHeight)
  }else if(direction==='top-left'){
   ctx.moveTo(bubbleX+bubbleWidth,bubbleY+bubbleHeight)
   ctx.lineTo(x-15,y-5)
   ctx.lineTo(bubbleX+bubbleWidth-15,bubbleY+bubbleHeight)
  }else if(direction==='bottom-right'){
   ctx.moveTo(bubbleX,bubbleY)
   ctx.lineTo(x+15,y+15)
   ctx.lineTo(bubbleX+15,bubbleY)
  }else{
   ctx.moveTo(bubbleX+bubbleWidth,bubbleY)
   ctx.lineTo(x-15,y+15)
   ctx.lineTo(bubbleX+bubbleWidth-15,bubbleY)
  }
  ctx.closePath()
  ctx.fill()

  ctx.fillStyle='#3a3530'
  ctx.textAlign='left'
  lines.forEach((line,i)=>{
   ctx.fillText(line,bubbleX+padding,bubbleY+padding+(i+1)*lineHeight-3)
  })
 },[])

 useEffect(()=>{
  const canvas=canvasRef.current
  if(!canvas)return

  const ctx=canvas.getContext('2d')
  if(!ctx)return

  const render=()=>{
   frameRef.current++
   const frame=frameRef.current

   const dpr=window.devicePixelRatio||1
   ctx.setTransform(dpr,0,0,dpr,0,0)

   ctx.fillStyle=NIER_COLORS.background
   ctx.fillRect(0,0,dimensions.width,dimensions.height)

   const platformX=dimensions.width*PLATFORM_X
   const platformWidth=dimensions.width*PLATFORM_WIDTH
   const roomX=dimensions.width*ROOM_X
   const roomWidth=dimensions.width*ROOM_WIDTH
   const topY=dimensions.height*0.06
   const totalHeight=dimensions.height*0.88

   const waitingAgentsCount=characters.filter(c=>c.status==='waiting_approval').length

   const services=Object.keys(SERVICE_CONFIG)as AIServiceType[]
   const numServices=services.length
   const totalSlots=numServices+1
   const platformGap=dimensions.height*0.015
   const totalGapHeight=(totalSlots-1)*platformGap
   const platformHeight=(totalHeight-totalGapHeight)/totalSlots
   const platformCenters:Record<AIServiceType,{centerX:number;centerY:number}>={}as any

   services.forEach((service,index)=>{
    const py=topY+index*(platformHeight+platformGap)
    const hasWorkers=characters.some(c=>c.status==='working'&&c.targetService===service)
    platformCenters[service]=drawPlatform(ctx,platformX,py,platformWidth,platformHeight,service,hasWorkers,frame)
   })

   const userAreaY=topY+numServices*(platformHeight+platformGap)
   drawUserArea(ctx,platformX,userAreaY,platformWidth,platformHeight,waitingAgentsCount>0,frame)

   drawRoom(ctx,roomX,topY,roomWidth,totalHeight)

   const positions=positionsRef.current
   const spriteSize=56*characterScale
   const workingAgents:{char:CharacterState;pos:CharacterPosition}[]=[]

   const workingPerService:Record<AIServiceType,number>={}as Record<AIServiceType,number>
   services.forEach(s=>{workingPerService[s]=0})
   const workingIndexMap=new Map<string,number>()

   const waitingIndexMap=new Map<string,number>()
   let waitingIndex=0

   characters.forEach((char)=>{
    if(char.status==='working'&&char.targetService){
     workingIndexMap.set(char.agentId,workingPerService[char.targetService])
     workingPerService[char.targetService]++
    }else if(char.status==='waiting_approval'){
     waitingIndexMap.set(char.agentId,waitingIndex)
     waitingIndex++
    }
   })

   const sortedChars=[...characters].sort((a,b)=>(a.phase??0)-(b.phase??0)||(a.agentType<b.agentType?-1:1))
   const agentIndexMap=new Map<string,number>()
   sortedChars.forEach((c,i)=>agentIndexMap.set(c.agentId,i))
   const gridCols=Math.max(1,Math.floor((roomWidth-30)/(spriteSize+10)))
   const cellWidth=(roomWidth-30)/gridCols
   const gridRows=Math.max(Math.ceil(sortedChars.length/gridCols),4)
   const cellHeight=(totalHeight-50)/gridRows

   characters.forEach((char)=>{
    const pos=positions.get(char.agentId)
    if(!pos)return

    const isWorking=char.status==='working'
    const isWaiting=char.status==='waiting_approval'

    if(isWorking&&char.targetService){
     const pc=platformCenters[char.targetService]
     const workingIdx=workingIndexMap.get(char.agentId)||0
     const agentSpacing=spriteSize+20
     pos.targetX=platformX+50+workingIdx*agentSpacing
     pos.targetY=pc.centerY
     pos.wasWorking=true
     workingAgents.push({char,pos})
    }else if(isWaiting){
     const waitIdx=waitingIndexMap.get(char.agentId)||0
     const waitCols=Math.max(1,Math.floor((platformWidth-30)/(spriteSize+5)))
     const waitCol=waitIdx%waitCols
     const waitRow=Math.floor(waitIdx/waitCols)
     const waitCellW=(platformWidth-30)/waitCols
     const waitCellH=(platformHeight-45)/Math.max(Math.ceil(waitingAgentsCount/waitCols),1)
     pos.targetX=platformX+15+waitCol*waitCellW+waitCellW/2
     pos.targetY=userAreaY+40+waitRow*waitCellH+waitCellH/2
     pos.wasWorking=false
    }else{
     const idx=agentIndexMap.get(char.agentId)??0
     const col=idx%gridCols
     const row=Math.floor(idx/gridCols)
     pos.targetX=roomX+20+col*cellWidth+cellWidth/2
     pos.targetY=topY+35+row*cellHeight+cellHeight/2
     pos.wasWorking=false
    }

    const speed=isWorking?0.08:(isWaiting?0.07:0.06)
    pos.x+=(pos.targetX-pos.x)*speed
    pos.y+=(pos.targetY-pos.y)*speed
   })

   const activeServices=new Set<AIServiceType>()
   workingAgents.forEach(({char,pos})=>{
    if(char.targetService){
     const distToTarget=Math.sqrt(Math.pow(pos.x-pos.targetX,2)+Math.pow(pos.y-pos.targetY,2))
     if(distToTarget<50){
      activeServices.add(char.targetService)
     }
    }
   })

   activeServices.forEach((service)=>{
    const pc=platformCenters[service]
    const platformRightEdge=platformX+platformWidth
    drawDataLine(ctx,platformRightEdge,pc.centerY,roomX,topY+totalHeight/2,frame)
   })

   type BubbleDir='top-right'|'top-left'|'bottom-right'|'bottom-left'
   const bubbleOffset=30
   const defaultBubbleW=260
   const defaultBubbleH=50

   const getBubbleRect=(
    x:number,y:number,dir:BubbleDir
):{x1:number;y1:number;x2:number;y2:number}=>{
    if(dir==='top-right')return{x1:x+bubbleOffset,y1:y-defaultBubbleH-15,x2:x+bubbleOffset+defaultBubbleW,y2:y-15}
    if(dir==='top-left')return{x1:x-defaultBubbleW-bubbleOffset,y1:y-defaultBubbleH-15,x2:x-bubbleOffset,y2:y-15}
    if(dir==='bottom-right')return{x1:x+bubbleOffset,y1:y+25,x2:x+bubbleOffset+defaultBubbleW,y2:y+25+defaultBubbleH}
    return{x1:x-defaultBubbleW-bubbleOffset,y1:y+25,x2:x-bubbleOffset,y2:y+25+defaultBubbleH}
   }

   const rectsOverlap=(
    a:{x1:number;y1:number;x2:number;y2:number},
    b:{x1:number;y1:number;x2:number;y2:number}
):boolean=>{
    return!(a.x2<b.x1||b.x2<a.x1||a.y2<b.y1||b.y2<a.y1)
   }

   const workingCharsWithPos=characters
    .filter(c=>c.status==='working'&&c.request)
    .map(c=>({char:c,pos:positions.get(c.agentId)!}))
    .filter(cp=>cp.pos)

   const assignedBubbles:Map<string,{dir:BubbleDir;rect:{x1:number;y1:number;x2:number;y2:number}}>=new Map()
   const directions:BubbleDir[]=['top-right','bottom-right','bottom-left','top-left']

   workingCharsWithPos.forEach(({char,pos})=>{
    let chosenDir:BubbleDir='top-right'
    for(const dir of directions){
     const candidateRect=getBubbleRect(pos.x,pos.y,dir)
     let overlaps=false
     for(const[,assigned]of assignedBubbles){
      if(rectsOverlap(candidateRect,assigned.rect)){
       overlaps=true
       break
      }
     }
     if(!overlaps){
      chosenDir=dir
      break
     }
    }
    assignedBubbles.set(char.agentId,{dir:chosenDir,rect:getBubbleRect(pos.x,pos.y,chosenDir)})
   })

   characters.forEach((char)=>{
    const pos=positions.get(char.agentId)
    if(!pos)return

    const isWorking=char.status==='working'
    const isWaiting=char.status==='waiting_approval'
    const isActive=char.isActive??(isWorking||isWaiting)

    if(!isActive){
     ctx.globalAlpha=0.4
    }
    drawPixelCharacter(ctx,pos.x,pos.y,char.agentType,isWorking||isWaiting,frame,characterScale)
    ctx.globalAlpha=1.0

    ctx.font='10px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
    ctx.fillStyle=isActive?NIER_COLORS.textMain : NIER_COLORS.textDim
    ctx.textAlign='center'
    ctx.fillText(getLabel(char.agentType),pos.x,pos.y+spriteSize/2+12)
   })

   characters.forEach((char)=>{
    if(char.status!=='working'||!char.request)return
    const pos=positions.get(char.agentId)
    if(!pos)return
    const bubbleInfo=assignedBubbles.get(char.agentId)
    const bubbleDir=bubbleInfo?.dir||'top-right'
    drawSpeechBubble(ctx,pos.x,pos.y,char.request.input,bubbleDir)
   })

   animationRef.current=requestAnimationFrame(render)
  }

  render()

  return()=>{
   if(animationRef.current){
    cancelAnimationFrame(animationRef.current)
   }
  }
 },[characters,dimensions,characterScale,drawPlatform,drawRoom,drawUserArea,drawDataLine,drawSpeechBubble,SERVICE_CONFIG,getLabel])

 const handleClick=useCallback((e:React.MouseEvent<HTMLCanvasElement>)=>{
  if(!onCharacterClick)return

  const canvas=canvasRef.current
  if(!canvas)return

  const rect=canvas.getBoundingClientRect()
  const x=e.clientX-rect.left
  const y=e.clientY-rect.top
  const spriteSize=56*characterScale

  const positions=positionsRef.current
  for(const char of characters){
   const pos=positions.get(char.agentId)
   if(!pos)continue

   const dist=Math.sqrt(Math.pow(x-pos.x,2)+Math.pow(y-pos.y,2))
   if(dist<spriteSize/2+12){
    onCharacterClick(char)
    return
   }
  }
 },[characters,onCharacterClick,characterScale])

 return(
  <div ref={containerRef} className="w-full h-full" style={{backgroundColor:'#d4cdb8'}}>
   <canvas
    ref={canvasRef}
    onClick={handleClick}
    className="cursor-pointer"
   />
  </div>
)
}
