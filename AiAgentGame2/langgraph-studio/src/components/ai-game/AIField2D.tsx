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
 activeGlow:'rgba(180,160,100,0.8)',
 lightning:'#f0e060',
 magicCircle:'#c0a060',
 warpGate:'#80c0e0',
 roadLine:'rgba(120,110,90,0.3)'
}

// 召喚エフェクトタイプ
type SummonEffectType='magic_circle'|'lightning'|'warp_gate'|'merge'

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
 summonEffect:SummonEffectType
 // 道路移動用
 pathPoints:Array<{x:number,y:number}>
 pathIndex:number
 lane:number // 0=左車線, 1=右車線
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

// 道路ノード
interface RoadNode{
 x:number
 y:number
 id:string
}

// 道路セグメント
interface RoadSegment{
 from:RoadNode
 to:RoadNode
 width:number
}

const MAX_VISIBLE_WORKERS=3
const SUMMON_DURATION=90 // フレーム数
const ROAD_WIDTH=40 // 道路幅（2車線分）
const LANE_OFFSET=8 // 車線中心からのオフセット

// Agentの重要度からエフェクトを決定
function getSummonEffect(agentType:AgentType):SummonEffectType{
 const level=getAgentLevel(agentType)
 if(level==='orchestrator')return'magic_circle'
 if(level==='division')return'lightning'
 // workerはランダムまたはワープゲート
 const hash=agentType.split('').reduce((a,c)=>a+c.charCodeAt(0),0)
 return hash%3===0?'merge':'warp_gate'
}

export function AIField2D({characters,onCharacterClick,characterScale=1.0}:AIField2DProps):JSX.Element{
 const canvasRef=useRef<HTMLCanvasElement>(null)
 const containerRef=useRef<HTMLDivElement>(null)
 const[dimensions,setDimensions]=useState({width:800,height:500})
 const positionsRef=useRef<Map<string,CharacterPosition>>(new Map())
 const frameRef=useRef<number>(0)
 const animationRef=useRef<number>(0)
 const roadNodesRef=useRef<RoadNode[]>([])
 const roadSegmentsRef=useRef<RoadSegment[]>([])

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

 // 道路ネットワークを構築（障害物間の中心線）
 const buildRoadNetwork=useCallback((layouts:DivisionLayout[])=>{
  const nodes:RoadNode[]=[]
  const segments:RoadSegment[]=[]

  // オーケストラ位置
  const orchX=dimensions.width/2
  const orchY=dimensions.height*0.11
  const orchNode:RoadNode={x:orchX,y:orchY+40,id:'orch'}
  nodes.push(orchNode)

  // 各Division boxの入口ノード
  layouts.forEach((layout,i)=>{
   const entryNode:RoadNode={
    x:layout.x+layout.width/2,
    y:layout.y-10,
    id:`div_entry_${i}`
   }
   const innerNode:RoadNode={
    x:layout.x+layout.width/2,
    y:layout.y+layout.height/2,
    id:`div_inner_${i}`
   }
   nodes.push(entryNode,innerNode)

   // オーケストラからDivision入口への道路
   segments.push({from:orchNode,to:entryNode,width:ROAD_WIDTH})
   // Division入口から内部への道路
   segments.push({from:entryNode,to:innerNode,width:ROAD_WIDTH*0.7})
  })

  // 横方向の接続道路（Division間）
  const sortedByY=layouts.map((l,i)=>({layout:l,index:i}))
   .sort((a,b)=>a.layout.y-b.layout.y)

  for(let i=0;i<sortedByY.length-1;i++){
   const curr=sortedByY[i]
   const next=sortedByY[i+1]
   if(Math.abs(curr.layout.y-next.layout.y)<50){
    // 同じ行にあるDivision間を接続
    const midY=(curr.layout.y+next.layout.y)/2-10
    const leftNode=nodes.find(n=>n.id===`div_entry_${curr.index}`)
    const rightNode=nodes.find(n=>n.id===`div_entry_${next.index}`)
    if(leftNode&&rightNode){
     const midNode:RoadNode={
      x:(leftNode.x+rightNode.x)/2,
      y:midY,
      id:`mid_${i}`
     }
     nodes.push(midNode)
     segments.push({from:leftNode,to:midNode,width:ROAD_WIDTH*0.6})
     segments.push({from:midNode,to:rightNode,width:ROAD_WIDTH*0.6})
    }
   }
  }

  roadNodesRef.current=nodes
  roadSegmentsRef.current=segments
 },[dimensions])

 // A*による経路探索（2車線対応）
 const findPath=useCallback((
  fromX:number,
  fromY:number,
  toX:number,
  toY:number,
  lane:number
 ):Array<{x:number,y:number}>=>{
  const nodes=roadNodesRef.current
  const segments=roadSegmentsRef.current

  if(nodes.length===0||segments.length===0){
   // 道路がない場合は直線
   return[{x:fromX,y:fromY},{x:toX,y:toY}]
  }

  // 最寄りのノードを探す
  const findNearest=(x:number,y:number):RoadNode|null=>{
   let nearest:RoadNode|null=null
   let minDist=Infinity
   for(const node of nodes){
    const d=Math.hypot(node.x-x,node.y-y)
    if(d<minDist){
     minDist=d
     nearest=node
    }
   }
   return nearest
  }

  const startNode=findNearest(fromX,fromY)
  const endNode=findNearest(toX,toY)

  if(!startNode||!endNode){
   return[{x:fromX,y:fromY},{x:toX,y:toY}]
  }

  // 簡易A*実装
  const getNeighbors=(node:RoadNode):RoadNode[]=>{
   const neighbors:RoadNode[]=[]
   for(const seg of segments){
    if(seg.from.id===node.id)neighbors.push(seg.to)
    if(seg.to.id===node.id)neighbors.push(seg.from)
   }
   return neighbors
  }

  const heuristic=(a:RoadNode,b:RoadNode):number=>Math.hypot(a.x-b.x,a.y-b.y)

  const openSet=new Set<string>([startNode.id])
  const cameFrom=new Map<string,RoadNode>()
  const gScore=new Map<string,number>()
  const fScore=new Map<string,number>()

  gScore.set(startNode.id,0)
  fScore.set(startNode.id,heuristic(startNode,endNode))

  while(openSet.size>0){
   // fScoreが最小のノードを取得
   let current:RoadNode|null=null
   let minF=Infinity
   for(const id of openSet){
    const f=fScore.get(id)??Infinity
    if(f<minF){
     minF=f
     current=nodes.find(n=>n.id===id)||null
    }
   }

   if(!current)break

   if(current.id===endNode.id){
    // パスを再構築
    const path:Array<{x:number,y:number}>=[]
    let curr:RoadNode|undefined=current
    while(curr){
     // 車線オフセットを適用
     const laneOff=lane===0?-LANE_OFFSET:LANE_OFFSET
     path.unshift({x:curr.x+laneOff,y:curr.y})
     curr=cameFrom.get(curr.id)
    }
    // 開始点と終了点を追加
    path.unshift({x:fromX,y:fromY})
    path.push({x:toX,y:toY})
    return path
   }

   openSet.delete(current.id)

   for(const neighbor of getNeighbors(current)){
    const tentativeG=(gScore.get(current.id)??Infinity)+heuristic(current,neighbor)
    if(tentativeG<(gScore.get(neighbor.id)??Infinity)){
     cameFrom.set(neighbor.id,current)
     gScore.set(neighbor.id,tentativeG)
     fScore.set(neighbor.id,tentativeG+heuristic(neighbor,endNode))
     openSet.add(neighbor.id)
    }
   }
  }

  // パスが見つからない場合は直線
  return[{x:fromX,y:fromY},{x:toX,y:toY}]
 },[])

 // Update character positions
 useEffect(()=>{
  const positions=positionsRef.current
  const{orchestrator,divisions}=groupCharacters()
  const layouts=calculateDivisionLayouts(divisions)

  // 道路ネットワークを構築
  buildRoadNetwork(layouts)

  const currentIds=new Set(characters.map(c=>c.agentId))
  for(const id of positions.keys()){
   if(!currentIds.has(id)){
    positions.delete(id)
   }
  }

  const spriteSize=48*characterScale
  let laneCounter=0 // 車線割り当て用

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
     summoned:false,summonProgress:0,
     summonEffect:getSummonEffect(orchestrator.agentType),
     pathPoints:[],pathIndex:0,lane:0
    })
   }
  }

  // Position division agents and their workers
  layouts.forEach(layout=>{
   if(layout.divisionChar){
    const x=layout.x+layout.width/2
    const y=layout.y+spriteSize/2+15
    const existing=positions.get(layout.divisionChar.agentId)
    if(existing){
     if(Math.hypot(existing.targetX-x,existing.targetY-y)>5){
      // 位置が変わった場合は経路を再計算
      existing.pathPoints=findPath(existing.x,existing.y,x,y,existing.lane)
      existing.pathIndex=0
     }
     existing.targetX=x
     existing.targetY=y
     existing.targetScale=1.0
     existing.targetOpacity=1
    }else{
     const lane=laneCounter++%2
     positions.set(layout.divisionChar.agentId,{
      x:dimensions.width/2,y:dimensions.height*0.11+40,
      targetX:x,targetY:y,
      scale:0,targetScale:1.0,
      opacity:0,targetOpacity:1,
      summoned:false,summonProgress:0,
      summonEffect:getSummonEffect(layout.divisionChar.agentType),
      pathPoints:findPath(dimensions.width/2,dimensions.height*0.11+40,x,y,lane),
      pathIndex:0,lane
     })
    }
   }

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
     if(Math.hypot(existing.targetX-x,existing.targetY-y)>5){
      existing.pathPoints=findPath(existing.x,existing.y,x,y,existing.lane)
      existing.pathIndex=0
     }
     existing.targetX=x
     existing.targetY=y
     existing.targetScale=0.85
     existing.targetOpacity=1
    }else{
     const spawnX=layout.x+layout.width/2
     const spawnY=layout.y+spriteSize/2+15
     const lane=laneCounter++%2
     positions.set(worker.agentId,{
      x:spawnX,y:spawnY,targetX:x,targetY:y,
      scale:0,targetScale:0.85,
      opacity:0,targetOpacity:1,
      summoned:false,summonProgress:0,
      summonEffect:getSummonEffect(worker.agentType),
      pathPoints:findPath(spawnX,spawnY,x,y,lane),
      pathIndex:0,lane
     })
    }
   })
  })
 },[characters,dimensions,characterScale,groupCharacters,calculateDivisionLayouts,buildRoadNetwork,findPath])

 // ===== 召喚エフェクト描画関数 =====

 // 魔法陣エフェクト（オーケストラ用）
 const drawMagicCircle=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,y:number,
  progress:number,
  frame:number,
  size:number
 )=>{
  const radius=size*(0.3+progress*0.7)
  const rotation=frame*0.05

  ctx.save()
  ctx.translate(x,y)

  // 外側の円
  ctx.strokeStyle=NIER_COLORS.magicCircle
  ctx.lineWidth=2
  ctx.globalAlpha=progress*0.8
  ctx.beginPath()
  ctx.arc(0,0,radius,0,Math.PI*2)
  ctx.stroke()

  // 内側の回転する六芒星
  ctx.rotate(rotation)
  ctx.beginPath()
  for(let i=0;i<6;i++){
   const angle=(i/6)*Math.PI*2
   const r=radius*0.7
   const px=Math.cos(angle)*r
   const py=Math.sin(angle)*r
   if(i===0)ctx.moveTo(px,py)
   else ctx.lineTo(px,py)
  }
  ctx.closePath()
  ctx.stroke()

  // 逆回転する内側の円
  ctx.rotate(-rotation*2)
  ctx.beginPath()
  ctx.arc(0,0,radius*0.4,0,Math.PI*2)
  ctx.stroke()

  // ルーン文字風の装飾
  const runeCount=8
  for(let i=0;i<runeCount;i++){
   const angle=(i/runeCount)*Math.PI*2+rotation*0.5
   const rx=Math.cos(angle)*radius*0.85
   const ry=Math.sin(angle)*radius*0.85
   ctx.fillStyle=NIER_COLORS.magicCircle
   ctx.globalAlpha=progress*(0.5+Math.sin(frame*0.1+i)*0.3)
   ctx.fillRect(rx-2,ry-4,4,8)
  }

  // 中央の光
  const gradient=ctx.createRadialGradient(0,0,0,0,0,radius*0.3)
  gradient.addColorStop(0,`rgba(255,240,180,${progress*0.6})`)
  gradient.addColorStop(1,'rgba(255,240,180,0)')
  ctx.fillStyle=gradient
  ctx.globalAlpha=1
  ctx.beginPath()
  ctx.arc(0,0,radius*0.3,0,Math.PI*2)
  ctx.fill()

  ctx.restore()
 },[])

 // 稲妻エフェクト（Division用）
 const drawLightning=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,y:number,
  progress:number,
  frame:number,
  size:number
 )=>{
  if(progress<0.1)return

  ctx.save()
  ctx.globalAlpha=Math.min(1,(1-progress)*3)*0.9

  // 複数の稲妻を描画
  const boltCount=3
  for(let b=0;b<boltCount;b++){
   const seed=frame*0.3+b*100
   ctx.strokeStyle=b===0?NIER_COLORS.lightning:'rgba(255,255,200,0.5)'
   ctx.lineWidth=b===0?3:1

   ctx.beginPath()
   let bx=x+(Math.sin(seed+b)*20)
   let by=y-size*1.5
   ctx.moveTo(bx,by)

   // ジグザグに下へ
   const segments=6+Math.floor(progress*4)
   for(let i=0;i<segments;i++){
    const t=i/segments
    bx+=(Math.random()-0.5)*30*progress
    by+=size*1.5/segments
    if(t<progress){
     ctx.lineTo(bx,by)
    }
   }
   ctx.stroke()

   // 分岐
   if(progress>0.5&&b===0){
    ctx.lineWidth=1
    ctx.beginPath()
    ctx.moveTo(bx,by-size*0.3)
    ctx.lineTo(bx+20*(Math.random()-0.5),by+10)
    ctx.lineTo(bx+30*(Math.random()-0.5),by+25)
    ctx.stroke()
   }
  }

  // 着弾点の光
  if(progress>0.3){
   const impactRadius=size*0.4*(1-(progress-0.3)/0.7)
   const gradient=ctx.createRadialGradient(x,y,0,x,y,impactRadius)
   gradient.addColorStop(0,'rgba(255,255,200,0.8)')
   gradient.addColorStop(0.5,'rgba(255,240,100,0.4)')
   gradient.addColorStop(1,'rgba(255,240,100,0)')
   ctx.fillStyle=gradient
   ctx.beginPath()
   ctx.arc(x,y,impactRadius,0,Math.PI*2)
   ctx.fill()
  }

  ctx.restore()
 },[])

 // ワープゲートエフェクト（Worker用）
 const drawWarpGate=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,y:number,
  progress:number,
  frame:number,
  size:number
 )=>{
  ctx.save()
  ctx.translate(x,y)

  const gateHeight=size*1.2
  const gateWidth=size*0.8
  const openProgress=Math.min(1,progress*2)

  // ゲートの枠（楕円形のポータル）
  ctx.strokeStyle=NIER_COLORS.warpGate
  ctx.lineWidth=3
  ctx.globalAlpha=openProgress*0.8

  ctx.beginPath()
  ctx.ellipse(0,0,gateWidth/2*openProgress,gateHeight/2,0,0,Math.PI*2)
  ctx.stroke()

  // 内側の渦
  if(openProgress>0.3){
   const spiralAlpha=(openProgress-0.3)/0.7
   for(let i=0;i<5;i++){
    const angle=frame*0.1+i*(Math.PI*2/5)
    const r=(gateWidth/2-5)*openProgress*(0.3+i*0.15)
    ctx.strokeStyle=`rgba(128,192,224,${spiralAlpha*(0.8-i*0.15)})`
    ctx.lineWidth=2
    ctx.beginPath()
    ctx.arc(Math.cos(angle)*r*0.3,Math.sin(angle)*r*0.5,r*0.2,0,Math.PI*2)
    ctx.stroke()
   }
  }

  // 中央のエネルギー
  if(progress>0.5){
   const energyProgress=(progress-0.5)/0.5
   const gradient=ctx.createRadialGradient(0,0,0,0,0,gateWidth/3)
   gradient.addColorStop(0,`rgba(200,240,255,${energyProgress*0.7})`)
   gradient.addColorStop(1,'rgba(128,192,224,0)')
   ctx.fillStyle=gradient
   ctx.beginPath()
   ctx.ellipse(0,0,gateWidth/3*energyProgress,gateHeight/3*energyProgress,0,0,Math.PI*2)
   ctx.fill()
  }

  ctx.restore()
 },[])

 // 分裂結合エフェクト（特殊Worker用）
 const drawMergeEffect=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,y:number,
  progress:number,
  frame:number,
  size:number
 )=>{
  ctx.save()

  const fragmentCount=5
  const mergeProgress=Math.min(1,progress*1.5)

  for(let i=0;i<fragmentCount;i++){
   const angle=(i/fragmentCount)*Math.PI*2+frame*0.02
   const distance=size*(1-mergeProgress)*1.5
   const fx=x+Math.cos(angle)*distance
   const fy=y+Math.sin(angle)*distance
   const fragSize=size*0.15*(0.5+mergeProgress*0.5)

   // フラグメントの軌跡
   if(mergeProgress<0.8){
    ctx.strokeStyle=`rgba(180,160,120,${(1-mergeProgress)*0.5})`
    ctx.lineWidth=1
    ctx.beginPath()
    ctx.moveTo(fx,fy)
    const trailX=x+Math.cos(angle)*distance*1.3
    const trailY=y+Math.sin(angle)*distance*1.3
    ctx.lineTo(trailX,trailY)
    ctx.stroke()
   }

   // フラグメント本体
   ctx.fillStyle=`rgba(200,180,140,${0.5+mergeProgress*0.5})`
   ctx.beginPath()
   ctx.arc(fx,fy,fragSize,0,Math.PI*2)
   ctx.fill()
  }

  // 結合時の光
  if(progress>0.6){
   const burstProgress=(progress-0.6)/0.4
   const gradient=ctx.createRadialGradient(x,y,0,x,y,size*0.5*burstProgress)
   gradient.addColorStop(0,`rgba(255,240,200,${(1-burstProgress)*0.8})`)
   gradient.addColorStop(1,'rgba(255,240,200,0)')
   ctx.fillStyle=gradient
   ctx.beginPath()
   ctx.arc(x,y,size*0.5*burstProgress,0,Math.PI*2)
   ctx.fill()
  }

  ctx.restore()
 },[])

 // 道路を描画
 const drawRoads=useCallback((ctx:CanvasRenderingContext2D)=>{
  const segments=roadSegmentsRef.current

  ctx.save()
  segments.forEach(seg=>{
   // 道路の背景
   ctx.strokeStyle=NIER_COLORS.roadLine
   ctx.lineWidth=seg.width
   ctx.lineCap='round'
   ctx.beginPath()
   ctx.moveTo(seg.from.x,seg.from.y)
   ctx.lineTo(seg.to.x,seg.to.y)
   ctx.stroke()

   // 中央線（破線）
   ctx.strokeStyle='rgba(100,90,70,0.2)'
   ctx.lineWidth=1
   ctx.setLineDash([8,8])
   ctx.beginPath()
   ctx.moveTo(seg.from.x,seg.from.y)
   ctx.lineTo(seg.to.x,seg.to.y)
   ctx.stroke()
   ctx.setLineDash([])
  })
  ctx.restore()
 },[])

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

  const isActive=orchestrator?.status==='working'
  if(isActive){
   ctx.shadowColor=NIER_COLORS.activeGlow
   ctx.shadowBlur=15+Math.sin(frame*0.08)*5
  }
  ctx.fillStyle=NIER_COLORS.orchestraBg
  ctx.fillRect(centerX-width/2,y,width,height)
  ctx.shadowBlur=0

  ctx.strokeStyle=NIER_COLORS.orchestraBorder
  ctx.lineWidth=2
  ctx.strokeRect(centerX-width/2,y,width,height)

  const cs=12
  ctx.fillStyle=NIER_COLORS.primary
  ;[[centerX-width/2,y],[centerX+width/2-cs,y],[centerX-width/2,y+height-cs],[centerX+width/2-cs,y+height-cs]]
   .forEach(([cx,cy])=>{
    ctx.fillRect(cx,cy,cs,2)
    ctx.fillRect(cx,cy,2,cs)
   })

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

  if(isActive){
   ctx.shadowColor=NIER_COLORS.summonGlow
   ctx.shadowBlur=10+Math.sin(frame*0.1)*5
  }
  ctx.fillStyle=NIER_COLORS.divisionBg
  ctx.fillRect(x,y,width,height)
  ctx.shadowBlur=0

  ctx.strokeStyle=isActive?NIER_COLORS.accent:NIER_COLORS.divisionBorder
  ctx.lineWidth=isActive?2:1
  ctx.strokeRect(x,y,width,height)

  const cs=8
  ctx.fillStyle=isActive?NIER_COLORS.accent:NIER_COLORS.primaryDim
  ;[[x,y],[x+width-cs,y],[x,y+height-cs],[x+width-cs,y+height-cs]].forEach(([cx,cy])=>{
   ctx.fillRect(cx,cy,cs,2)
   ctx.fillRect(cx,cy,2,cs)
  })

  ctx.fillStyle=NIER_COLORS.textDim
  ctx.font='10px "Courier New", monospace'
  ctx.textAlign='center'
  ctx.fillText(`[ ${hierarchy?.groupLabel||agentType} ]`,x+width/2,y+height-6)

  if(workers.length>MAX_VISIBLE_WORKERS){
   const extraCount=workers.length-MAX_VISIBLE_WORKERS
   ctx.fillStyle=NIER_COLORS.accent
   ctx.font='bold 11px "Courier New", monospace'
   ctx.textAlign='right'
   ctx.fillText(`+${extraCount}`,x+width-8,y+height-6)

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
  x:number,y:number,
  text:string,
  scale:number
 )=>{
  ctx.font=`${11*scale}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`

  const padding=6*scale
  const lineHeight=14*scale
  const maxLineWidth=160*scale

  let lines:string[]=[]
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

  if(lines.length>3){
   lines=lines.slice(0,3)
   lines[2]=lines[2].slice(0,-3)+'...'
  }

  const actualWidth=Math.max(...lines.map(l=>ctx.measureText(l).width))
  const bubbleWidth=actualWidth+padding*2+4
  const bubbleHeight=lines.length*lineHeight+padding*2

  const bubbleX=Math.round(x+40*scale)
  const bubbleY=Math.round(y-bubbleHeight/2)

  ctx.fillStyle='#e8e4d8'
  ctx.fillRect(bubbleX,bubbleY,bubbleWidth,bubbleHeight)
  ctx.strokeStyle='#8a8070'
  ctx.lineWidth=1
  ctx.strokeRect(bubbleX+0.5,bubbleY+0.5,bubbleWidth-1,bubbleHeight-1)

  ctx.fillStyle='#e8e4d8'
  ctx.beginPath()
  ctx.moveTo(bubbleX,y-5*scale)
  ctx.lineTo(bubbleX-8*scale,y)
  ctx.lineTo(bubbleX,y+5*scale)
  ctx.closePath()
  ctx.fill()

  ctx.fillStyle='#3a3530'
  ctx.textAlign='left'
  lines.forEach((line,i)=>{
   ctx.fillText(line,bubbleX+padding,bubbleY+padding+(i+1)*lineHeight-3*scale)
  })
 },[])

 // Draw connection line
 const drawConnectionLine=useCallback((
  ctx:CanvasRenderingContext2D,
  fromX:number,fromY:number,
  toX:number,toY:number,
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

  if(isActive){
   const dx=toX-fromX
   const dy=toY-fromY
   for(let i=0;i<3;i++){
    const t=((frame*0.02+i/3)%1)
    ctx.fillStyle=`rgba(200,180,120,${0.8-t*0.6})`
    ctx.beginPath()
    ctx.arc(fromX+dx*t,fromY+dy*t,3,0,Math.PI*2)
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

   ctx.fillStyle=NIER_COLORS.background
   ctx.fillRect(0,0,dimensions.width,dimensions.height)

   const{orchestrator,divisions}=groupCharacters()
   const layouts=calculateDivisionLayouts(divisions)
   const positions=positionsRef.current
   const spriteSize=48*characterScale

   // 道路を描画
   drawRoads(ctx)

   // Draw orchestrator area and division boxes
   drawOrchestraArea(ctx,orchestrator,frame)
   layouts.forEach(layout=>drawDivisionBox(ctx,layout,frame))

   // Draw connection lines
   if(orchestrator){
    const orchPos=positions.get(orchestrator.agentId)
    if(orchPos){
     layouts.forEach(layout=>{
      const isActive=layout.divisionChar?.status==='working'||layout.workers.some(w=>w.status==='working')
      drawConnectionLine(
       ctx,
       orchPos.x,orchPos.y+spriteSize*orchPos.scale/2+10,
       layout.x+layout.width/2,layout.y,
       isActive,frame
      )
     })
    }
   }

   // Update and draw all characters
   characters.forEach(char=>{
    const pos=positions.get(char.agentId)
    if(!pos)return

    // 道路に沿った移動
    if(pos.pathPoints.length>0&&pos.pathIndex<pos.pathPoints.length-1){
     const target=pos.pathPoints[pos.pathIndex+1]
     const dx=target.x-pos.x
     const dy=target.y-pos.y
     const dist=Math.hypot(dx,dy)
     const speed=2.5 // 移動速度

     if(dist<speed){
      pos.x=target.x
      pos.y=target.y
      pos.pathIndex++
     }else{
      pos.x+=dx/dist*speed
      pos.y+=dy/dist*speed
     }
    }else{
     // パスがない場合は直接移動
     const easeSpeed=0.06
     pos.x+=(pos.targetX-pos.x)*easeSpeed
     pos.y+=(pos.targetY-pos.y)*easeSpeed
    }

    pos.scale+=(pos.targetScale-pos.scale)*0.08
    pos.opacity+=(pos.targetOpacity-pos.opacity)*0.08

    // Summon animation
    if(!pos.summoned){
     pos.summonProgress++
     if(pos.summonProgress>=SUMMON_DURATION){
      pos.summoned=true
     }
    }

    if(pos.opacity<0.01||pos.scale<0.01)return

    const isWorking=char.status==='working'
    const isActive=char.isActive??isWorking
    const config=getAgentDisplayConfig(char.agentType)
    const progress=pos.summonProgress/SUMMON_DURATION

    // 召喚エフェクトを描画
    if(!pos.summoned){
     const effectSize=spriteSize*pos.targetScale
     switch(pos.summonEffect){
      case'magic_circle':
       drawMagicCircle(ctx,pos.x,pos.y,progress,frame,effectSize)
       break
      case'lightning':
       drawLightning(ctx,pos.x,pos.y,progress,frame,effectSize)
       break
      case'warp_gate':
       drawWarpGate(ctx,pos.x,pos.y,progress,frame,effectSize)
       break
      case'merge':
       drawMergeEffect(ctx,pos.x,pos.y,progress,frame,effectSize)
       break
     }
    }

    // キャラクター本体（召喚完了後or途中から表示）
    let alpha=pos.opacity
    if(!isActive)alpha*=0.5
    if(!pos.summoned){
     // エフェクトに応じて表示タイミングを調整
     const showThreshold=pos.summonEffect==='magic_circle'?0.7:
      pos.summonEffect==='lightning'?0.4:0.5
     if(progress<showThreshold)alpha=0
     else alpha*=(progress-showThreshold)/(1-showThreshold)
    }

    if(alpha>0.01){
     ctx.globalAlpha=alpha
     drawPixelCharacter(ctx,pos.x,pos.y,char.agentType,isWorking,frame,pos.scale*characterScale)
     ctx.globalAlpha=1.0

     ctx.font=`${10*pos.scale}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
     ctx.fillStyle=isActive?NIER_COLORS.textMain:NIER_COLORS.textDim
     ctx.textAlign='center'
     ctx.fillText(config.label,pos.x,pos.y+spriteSize*pos.scale/2+12*pos.scale)

     if(isWorking&&char.request){
      drawSpeechBubble(ctx,pos.x,pos.y,char.request.input,pos.scale)
     }
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
 },[characters,dimensions,characterScale,groupCharacters,calculateDivisionLayouts,
  drawOrchestraArea,drawDivisionBox,drawSpeechBubble,drawConnectionLine,drawRoads,
  drawMagicCircle,drawLightning,drawWarpGate,drawMergeEffect])

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
   const dist=Math.hypot(x-pos.x,y-pos.y)
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
