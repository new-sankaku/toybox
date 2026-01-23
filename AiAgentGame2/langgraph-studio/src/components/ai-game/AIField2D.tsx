import{useRef,useEffect,useCallback,useState}from'react'
import type{CharacterState}from'./types'
import{AGENT_HIERARCHY,DIVISION_AGENTS,getAgentsByDivision,getAgentLevel}from'./types'
import{drawPixelCharacter,getAgentDisplayConfig}from'./pixelCharacters'
import type{AgentType}from'@/types/agent'

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
 textDim:'#7a756a',
 divisionBg:'#e8e4d8',
 divisionBorder:'#9a9080',
 orchestraBg:'#d0c8b0',
 orchestraBorder:'#8a8070',
 summonGlow:'rgba(200,180,120,0.5)',
 activeGlow:'rgba(180,160,100,0.8)'
}

interface CharacterPosition{
 x:number
 y:number
 targetX:number
 targetY:number
 scale:number
 targetScale:number
 opacity:number
 targetOpacity:number
 summoned:boolean
 summonProgress:number
}

interface DivisionLayout{
 x:number
 y:number
 width:number
 height:number
 agentType:AgentType
 workers:CharacterState[]
 divisionChar?:CharacterState
}

const MAX_VISIBLE_WORKERS=3
const SUMMON_DURATION=60 // frames for summon animation

export function AIField2D({characters,onCharacterClick,characterScale=1.0}:AIField2DProps):JSX.Element{
 const canvasRef=useRef<HTMLCanvasElement>(null)
 const containerRef=useRef<HTMLDivElement>(null)
 const[dimensions,setDimensions]=useState({width:800,height:500})
 const positionsRef=useRef<Map<string,CharacterPosition>>(new Map())
 const frameRef=useRef<number>(0)
 const animationRef=useRef<number>(0)
 const summonOrderRef=useRef<Map<string,number>>(new Map())
 const summonCounterRef=useRef<number>(0)

 // Canvas resize handling
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
   if(ctx)ctx.scale(dpr,dpr)

   setDimensions({width:rect.width,height:rect.height})
  }

  const resizeObserver=new ResizeObserver(()=>updateDimensions())
  resizeObserver.observe(container)
  return()=>resizeObserver.disconnect()
 },[])

 // Group characters by hierarchy
 const groupCharacters=useCallback(()=>{
  const orchestrator=characters.find(c=>getAgentLevel(c.agentType)==='orchestrator')
  const divisions:Map<AgentType,{division?:CharacterState,workers:CharacterState[]}>=new Map()

  DIVISION_AGENTS.forEach(div=>{
   const workerTypes=getAgentsByDivision(div)
   const divChar=characters.find(c=>c.agentType===div)
   const workers=characters.filter(c=>workerTypes.includes(c.agentType))
   if(divChar||workers.length>0){
    divisions.set(div,{division:divChar,workers})
   }
  })

  return{orchestrator,divisions}
 },[characters])

 // Calculate division layouts dynamically
 const calculateDivisionLayouts=useCallback((
  divisions:Map<AgentType,{division?:CharacterState,workers:CharacterState[]}>
 ):DivisionLayout[]=>{
  const layouts:DivisionLayout[]=[]
  const activeDivisions=Array.from(divisions.entries()).filter(([_,v])=>v.division||v.workers.length>0)
  const count=activeDivisions.length
  if(count===0)return layouts

  const padding=20
  const orchestraHeight=dimensions.height*0.22
  const availableHeight=dimensions.height-orchestraHeight-padding*2
  const availableWidth=dimensions.width-padding*2

  // Calculate grid layout for divisions
  const cols=count<=2?count:2
  const rows=Math.ceil(count/cols)
  const divWidth=(availableWidth-padding*(cols-1))/cols
  const divHeight=(availableHeight-padding*(rows-1))/rows
  const minDivSize=Math.min(divWidth,divHeight,200)

  activeDivisions.forEach(([agentType,data],index)=>{
   const col=index%cols
   const row=Math.floor(index/cols)
   const itemsInRow=row===rows-1?(count-row*cols):cols
   const rowStartX=padding+(availableWidth-itemsInRow*(minDivSize+padding)+padding)/2

   layouts.push({
    x:rowStartX+col*(minDivSize+padding),
    y:orchestraHeight+padding+row*(minDivSize+padding),
    width:minDivSize,
    height:minDivSize,
    agentType,
    workers:data.workers,
    divisionChar:data.division
   })
  })

  return layouts
 },[dimensions])

 // Update character positions
 useEffect(()=>{
  const positions=positionsRef.current
  const summonOrder=summonOrderRef.current

  // Remove positions for characters that no longer exist
  const currentIds=new Set(characters.map(c=>c.agentId))
  for(const id of positions.keys()){
   if(!currentIds.has(id)){
    positions.delete(id)
    summonOrder.delete(id)
   }
  }

  // Track new characters for summon animation
  characters.forEach(char=>{
   if(!summonOrder.has(char.agentId)){
    summonOrder.set(char.agentId,summonCounterRef.current++)
   }
  })

  const{orchestrator,divisions}=groupCharacters()
  const layouts=calculateDivisionLayouts(divisions)
  const spriteSize=48*characterScale

  // Position orchestrator at top center
  if(orchestrator){
   const x=dimensions.width/2
   const y=dimensions.height*0.11
   const existing=positions.get(orchestrator.agentId)
   if(existing){
    existing.targetX=x
    existing.targetY=y
    existing.targetScale=1.3
    existing.targetOpacity=1
   }else{
    positions.set(orchestrator.agentId,{
     x,y,targetX:x,targetY:y,
     scale:0,targetScale:1.3,
     opacity:0,targetOpacity:1,
     summoned:false,summonProgress:0
    })
   }
  }

  // Position division agents and their workers
  layouts.forEach(layout=>{
   // Position division agent at top of its box
   if(layout.divisionChar){
    const x=layout.x+layout.width/2
    const y=layout.y+spriteSize/2+15
    const existing=positions.get(layout.divisionChar.agentId)
    if(existing){
     existing.targetX=x
     existing.targetY=y
     existing.targetScale=1.0
     existing.targetOpacity=1
    }else{
     positions.set(layout.divisionChar.agentId,{
      x,y,targetX:x,targetY:y,
      scale:0,targetScale:1.0,
      opacity:0,targetOpacity:1,
      summoned:false,summonProgress:0
     })
    }
   }

   // Position workers inside the division box
   const visibleWorkers=layout.workers.slice(0,MAX_VISIBLE_WORKERS)
   const workerCount=Math.min(visibleWorkers.length,MAX_VISIBLE_WORKERS)
   const workerAreaY=layout.y+spriteSize+40
   const workerAreaHeight=layout.height-spriteSize-50
   const workerSpacing=Math.min(spriteSize+10,workerAreaHeight/Math.max(workerCount,1))

   visibleWorkers.forEach((worker,index)=>{
    const x=layout.x+layout.width/2
    const y=workerAreaY+workerSpacing*index+workerSpacing/2
    const existing=positions.get(worker.agentId)
    if(existing){
     existing.targetX=x
     existing.targetY=y
     existing.targetScale=0.85
     existing.targetOpacity=1
    }else{
     // New workers spawn from division center
     const spawnX=layout.x+layout.width/2
     const spawnY=layout.y+spriteSize/2+15
     positions.set(worker.agentId,{
      x:spawnX,y:spawnY,targetX:x,targetY:y,
      scale:0,targetScale:0.85,
      opacity:0,targetOpacity:1,
      summoned:false,summonProgress:0
     })
    }
   })
  })
 },[characters,dimensions,characterScale,groupCharacters,calculateDivisionLayouts])

 // Draw orchestrator area
 const drawOrchestraArea=useCallback((
  ctx:CanvasRenderingContext2D,
  orchestrator:CharacterState|undefined,
  frame:number
 )=>{
  const centerX=dimensions.width/2
  const y=dimensions.height*0.02
  const width=Math.min(dimensions.width*0.5,280)
  const height=dimensions.height*0.18

  // Background with subtle glow when active
  const isActive=orchestrator?.status==='working'
  if(isActive){
   ctx.shadowColor=NIER_COLORS.activeGlow
   ctx.shadowBlur=15+Math.sin(frame*0.08)*5
  }
  ctx.fillStyle=NIER_COLORS.orchestraBg
  ctx.fillRect(centerX-width/2,y,width,height)
  ctx.shadowBlur=0

  // Border
  ctx.strokeStyle=NIER_COLORS.orchestraBorder
  ctx.lineWidth=2
  ctx.strokeRect(centerX-width/2,y,width,height)

  // Corner decorations
  const cs=12
  ctx.fillStyle=NIER_COLORS.primary
  const corners=[
   [centerX-width/2,y],
   [centerX+width/2-cs,y],
   [centerX-width/2,y+height-cs],
   [centerX+width/2-cs,y+height-cs]
  ]
  corners.forEach(([cx,cy])=>{
   ctx.fillRect(cx,cy,cs,2)
   ctx.fillRect(cx,cy,2,cs)
  })

  // Title
  ctx.fillStyle=NIER_COLORS.textMain
  ctx.font='bold 12px "Courier New", monospace'
  ctx.textAlign='center'
  ctx.fillText('[ ORCHESTRATOR ]',centerX,y+height-8)
 },[dimensions])

 // Draw division box
 const drawDivisionBox=useCallback((
  ctx:CanvasRenderingContext2D,
  layout:DivisionLayout,
  frame:number
 )=>{
  const{x,y,width,height,agentType,workers,divisionChar}=layout
  const isActive=divisionChar?.status==='working'||workers.some(w=>w.status==='working')
  const hierarchy=AGENT_HIERARCHY[agentType]

  // Background with glow when active
  if(isActive){
   ctx.shadowColor=NIER_COLORS.summonGlow
   ctx.shadowBlur=10+Math.sin(frame*0.1)*5
  }
  ctx.fillStyle=NIER_COLORS.divisionBg
  ctx.fillRect(x,y,width,height)
  ctx.shadowBlur=0

  // Border
  ctx.strokeStyle=isActive?NIER_COLORS.accent:NIER_COLORS.divisionBorder
  ctx.lineWidth=isActive?2:1
  ctx.strokeRect(x,y,width,height)

  // Corner decorations
  const cs=8
  ctx.fillStyle=isActive?NIER_COLORS.accent:NIER_COLORS.primaryDim
  ;[[x,y],[x+width-cs,y],[x,y+height-cs],[x+width-cs,y+height-cs]].forEach(([cx,cy])=>{
   ctx.fillRect(cx,cy,cs,2)
   ctx.fillRect(cx,cy,2,cs)
  })

  // Division label at bottom
  ctx.fillStyle=NIER_COLORS.textDim
  ctx.font='10px "Courier New", monospace'
  ctx.textAlign='center'
  ctx.fillText(`[ ${hierarchy?.groupLabel||agentType} ]`,x+width/2,y+height-6)

  // Worker count indicator if more than MAX_VISIBLE_WORKERS
  if(workers.length>MAX_VISIBLE_WORKERS){
   const extraCount=workers.length-MAX_VISIBLE_WORKERS
   ctx.fillStyle=NIER_COLORS.accent
   ctx.font='bold 11px "Courier New", monospace'
   ctx.textAlign='right'
   ctx.fillText(`+${extraCount}`,x+width-8,y+height-6)

   // Power-up indicator (multiple rings)
   const indicatorX=x+width-20
   const indicatorY=y+height-25
   for(let i=0;i<Math.min(extraCount,3);i++){
    ctx.strokeStyle=`rgba(180,160,120,${0.6-i*0.15})`
    ctx.lineWidth=1
    ctx.beginPath()
    ctx.arc(indicatorX,indicatorY,6+i*4+Math.sin(frame*0.1+i)*1,0,Math.PI*2)
    ctx.stroke()
   }
  }
 },[])

 // Draw speech bubble
 const drawSpeechBubble=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,
  y:number,
  text:string,
  scale:number
 )=>{
  ctx.font=`${11*scale}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`

  const padding=6*scale
  const lineHeight=14*scale
  const maxLineWidth=160*scale

  // Word wrap
  let lines:string[]=[]
  const words=text.split('')
  let currentLine=''
  for(const char of words){
   const testLine=currentLine+char
   if(ctx.measureText(testLine).width>maxLineWidth){
    if(currentLine)lines.push(currentLine)
    currentLine=char
   }else{
    currentLine=testLine
   }
  }
  if(currentLine)lines.push(currentLine)

  // Limit to 3 lines
  if(lines.length>3){
   lines=lines.slice(0,3)
   lines[2]=lines[2].slice(0,-3)+'...'
  }

  const actualWidth=Math.max(...lines.map(l=>ctx.measureText(l).width))
  const bubbleWidth=actualWidth+padding*2+4
  const bubbleHeight=lines.length*lineHeight+padding*2

  const bubbleX=Math.round(x+40*scale)
  const bubbleY=Math.round(y-bubbleHeight/2)

  // Bubble background
  ctx.fillStyle='#e8e4d8'
  ctx.fillRect(bubbleX,bubbleY,bubbleWidth,bubbleHeight)
  ctx.strokeStyle='#8a8070'
  ctx.lineWidth=1
  ctx.strokeRect(bubbleX+0.5,bubbleY+0.5,bubbleWidth-1,bubbleHeight-1)

  // Pointer
  ctx.fillStyle='#e8e4d8'
  ctx.beginPath()
  ctx.moveTo(bubbleX,y-5*scale)
  ctx.lineTo(bubbleX-8*scale,y)
  ctx.lineTo(bubbleX,y+5*scale)
  ctx.closePath()
  ctx.fill()

  // Text
  ctx.fillStyle='#3a3530'
  ctx.textAlign='left'
  lines.forEach((line,i)=>{
   ctx.fillText(line,bubbleX+padding,bubbleY+padding+(i+1)*lineHeight-3*scale)
  })
 },[])

 // Draw connection line between orchestrator and divisions
 const drawConnectionLine=useCallback((
  ctx:CanvasRenderingContext2D,
  fromX:number,
  fromY:number,
  toX:number,
  toY:number,
  isActive:boolean,
  frame:number
 )=>{
  ctx.strokeStyle=isActive?NIER_COLORS.accent:NIER_COLORS.primaryDim
  ctx.lineWidth=isActive?2:1
  ctx.setLineDash(isActive?[]:[4,4])
  ctx.beginPath()
  ctx.moveTo(fromX,fromY)
  ctx.lineTo(toX,toY)
  ctx.stroke()
  ctx.setLineDash([])

  // Animated particles on active connections
  if(isActive){
   const dx=toX-fromX
   const dy=toY-fromY
   for(let i=0;i<3;i++){
    const t=((frame*0.02+i/3)%1)
    const px=fromX+dx*t
    const py=fromY+dy*t
    ctx.fillStyle=`rgba(200,180,120,${0.8-t*0.6})`
    ctx.beginPath()
    ctx.arc(px,py,3,0,Math.PI*2)
    ctx.fill()
   }
  }
 },[])

 // Main render loop
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

   // Clear canvas
   ctx.fillStyle=NIER_COLORS.background
   ctx.fillRect(0,0,dimensions.width,dimensions.height)

   const{orchestrator,divisions}=groupCharacters()
   const layouts=calculateDivisionLayouts(divisions)
   const positions=positionsRef.current
   const spriteSize=48*characterScale

   // Draw orchestrator area
   drawOrchestraArea(ctx,orchestrator,frame)

   // Draw division boxes
   layouts.forEach(layout=>{
    drawDivisionBox(ctx,layout,frame)
   })

   // Draw connection lines from orchestrator to divisions
   if(orchestrator){
    const orchPos=positions.get(orchestrator.agentId)
    if(orchPos){
     layouts.forEach(layout=>{
      const isActive=layout.divisionChar?.status==='working'||layout.workers.some(w=>w.status==='working')
      drawConnectionLine(
       ctx,
       orchPos.x,
       orchPos.y+spriteSize*orchPos.scale/2+10,
       layout.x+layout.width/2,
       layout.y,
       isActive,
       frame
      )
     })
    }
   }

   // Update and draw all characters
   characters.forEach(char=>{
    const pos=positions.get(char.agentId)
    if(!pos)return

    // Smooth animation with easing
    const easeSpeed=0.06
    pos.x+=(pos.targetX-pos.x)*easeSpeed
    pos.y+=(pos.targetY-pos.y)*easeSpeed
    pos.scale+=(pos.targetScale-pos.scale)*easeSpeed
    pos.opacity+=(pos.targetOpacity-pos.opacity)*easeSpeed

    // Summon animation progress
    if(!pos.summoned){
     pos.summonProgress++
     if(pos.summonProgress>=SUMMON_DURATION){
      pos.summoned=true
     }
    }

    // Skip if not visible
    if(pos.opacity<0.01||pos.scale<0.01)return

    const isWorking=char.status==='working'
    const isActive=char.isActive??isWorking
    const config=getAgentDisplayConfig(char.agentType)

    // Apply opacity for inactive or summoning agents
    let alpha=pos.opacity
    if(!isActive)alpha*=0.5
    if(!pos.summoned)alpha*=pos.summonProgress/SUMMON_DURATION

    ctx.globalAlpha=alpha

    // Draw summon effect for new agents
    if(!pos.summoned&&pos.summonProgress<SUMMON_DURATION){
     const progress=pos.summonProgress/SUMMON_DURATION
     ctx.strokeStyle=NIER_COLORS.summonGlow
     ctx.lineWidth=2
     ctx.beginPath()
     ctx.arc(pos.x,pos.y,spriteSize*pos.scale*(1.5-progress*0.5),0,Math.PI*2*progress)
     ctx.stroke()
    }

    // Draw character
    drawPixelCharacter(ctx,pos.x,pos.y,char.agentType,isWorking,frame,pos.scale*characterScale)

    ctx.globalAlpha=1.0

    // Draw label (never truncated)
    ctx.font=`${10*pos.scale}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
    ctx.fillStyle=isActive?NIER_COLORS.textMain:NIER_COLORS.textDim
    ctx.textAlign='center'
    ctx.fillText(config.label,pos.x,pos.y+spriteSize*pos.scale/2+12*pos.scale)

    // Draw speech bubble for working agents (never truncated severely)
    if(isWorking&&char.request){
     drawSpeechBubble(ctx,pos.x,pos.y,char.request.input,pos.scale)
    }
   })

   // Status display
   const activeCount=characters.filter(c=>c.status==='working').length
   ctx.fillStyle=NIER_COLORS.textDim
   ctx.font='10px "Courier New", monospace'
   ctx.textAlign='left'
   ctx.fillText(`AGENTS: ${characters.length}`,10,dimensions.height-8)
   ctx.fillText(`ACTIVE: ${activeCount}`,90,dimensions.height-8)

   animationRef.current=requestAnimationFrame(render)
  }

  render()

  return()=>{
   if(animationRef.current)cancelAnimationFrame(animationRef.current)
  }
 },[characters,dimensions,characterScale,groupCharacters,calculateDivisionLayouts,drawOrchestraArea,drawDivisionBox,drawSpeechBubble,drawConnectionLine])

 // Click handler
 const handleClick=useCallback((e:React.MouseEvent<HTMLCanvasElement>)=>{
  if(!onCharacterClick)return

  const canvas=canvasRef.current
  if(!canvas)return

  const rect=canvas.getBoundingClientRect()
  const x=e.clientX-rect.left
  const y=e.clientY-rect.top
  const positions=positionsRef.current

  for(const char of characters){
   const pos=positions.get(char.agentId)
   if(!pos)continue

   const spriteSize=48*characterScale*pos.scale
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
