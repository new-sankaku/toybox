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
 roadLine:'rgba(120,110,90,0.25)',
 roadCenter:'rgba(100,90,70,0.15)',
 intersection:'rgba(140,120,80,0.3)'
}

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
 pathPoints:Array<{x:number,y:number}>
 pathIndex:number
 lane:number
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

interface RoadNode{
 x:number
 y:number
 id:string
 isIntersection?:boolean
}

interface RoadSegment{
 from:RoadNode
 to:RoadNode
 width:number
}

// 動的に計算されるレイアウト設定
interface LayoutConfig{
 orchestraHeight:number
 orchestraY:number
 padding:number
 roadWidth:number
 laneOffset:number
 nodeRadius:number
 spriteSize:number
}

const MAX_VISIBLE_WORKERS=3
const SUMMON_DURATION=90

function getSummonEffect(agentType:AgentType):SummonEffectType{
 const level=getAgentLevel(agentType)
 if(level==='orchestrator')return'magic_circle'
 if(level==='division')return'lightning'
 const hash=agentType.split('').reduce((a,c)=>a+c.charCodeAt(0),0)
 return hash%3===0?'merge':'warp_gate'
}

// 2つの線分の交点を計算
function getLineIntersection(
 p1:{x:number,y:number},p2:{x:number,y:number},
 p3:{x:number,y:number},p4:{x:number,y:number}
):{x:number,y:number}|null{
 const d=(p1.x-p2.x)*(p3.y-p4.y)-(p1.y-p2.y)*(p3.x-p4.x)
 if(Math.abs(d)<0.0001)return null

 const t=((p1.x-p3.x)*(p3.y-p4.y)-(p1.y-p3.y)*(p3.x-p4.x))/d
 const u=-((p1.x-p2.x)*(p1.y-p3.y)-(p1.y-p2.y)*(p1.x-p3.x))/d

 if(t>0.05&&t<0.95&&u>0.05&&u<0.95){
  return{
   x:p1.x+t*(p2.x-p1.x),
   y:p1.y+t*(p2.y-p1.y)
  }
 }
 return null
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
 const layoutConfigRef=useRef<LayoutConfig|null>(null)

 // レイアウト設定を動的に計算
 const calculateLayoutConfig=useCallback(():LayoutConfig=>{
  const minDim=Math.min(dimensions.width,dimensions.height)
  const spriteSize=48*characterScale

  return{
   orchestraHeight:dimensions.height*0.20,
   orchestraY:dimensions.height*0.02,
   padding:minDim*0.03,
   roadWidth:minDim*0.05,
   laneOffset:minDim*0.012,
   nodeRadius:minDim*0.015,
   spriteSize
  }
 },[dimensions,characterScale])

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

 const calculateDivisionLayouts=useCallback((
  divisions:Map<AgentType,{division?:CharacterState,workers:CharacterState[]}>
 ):DivisionLayout[]=>{
  const layouts:DivisionLayout[]=[]
  const activeDivisions=Array.from(divisions.entries()).filter(([_,v])=>v.division||v.workers.length>0)
  const count=activeDivisions.length
  if(count===0)return layouts

  const config=calculateLayoutConfig()
  const padding=config.padding
  const orchestraBottom=config.orchestraY+config.orchestraHeight
  const availableHeight=dimensions.height-orchestraBottom-padding*2
  const availableWidth=dimensions.width-padding*2

  const cols=count<=2?count:2
  const rows=Math.ceil(count/cols)
  const divWidth=(availableWidth-padding*(cols-1))/cols
  const divHeight=(availableHeight-padding*(rows-1))/rows
  const minDivSize=Math.min(divWidth,divHeight,dimensions.width*0.25)

  activeDivisions.forEach(([agentType,data],index)=>{
   const col=index%cols
   const row=Math.floor(index/cols)
   const itemsInRow=row===rows-1?(count-row*cols):cols
   const rowStartX=padding+(availableWidth-itemsInRow*(minDivSize+padding)+padding)/2

   layouts.push({
    x:rowStartX+col*(minDivSize+padding),
    y:orchestraBottom+padding+row*(minDivSize+padding),
    width:minDivSize,
    height:minDivSize,
    agentType,
    workers:data.workers,
    divisionChar:data.division
   })
  })

  return layouts
 },[dimensions,calculateLayoutConfig])

 // 道路ネットワークを動的に構築（Division box間を通る道路）
 const buildRoadNetwork=useCallback((layouts:DivisionLayout[])=>{
  const config=calculateLayoutConfig()
  layoutConfigRef.current=config

  const nodes:RoadNode[]=[]
  const segments:RoadSegment[]=[]

  if(layouts.length===0){
   roadNodesRef.current=nodes
   roadSegmentsRef.current=segments
   return
  }

  // オーケストラ位置
  const orchX=dimensions.width/2
  const orchExitY=config.orchestraY+config.orchestraHeight+config.padding*0.3

  const orchNode:RoadNode={x:orchX,y:orchExitY,id:'orch'}
  nodes.push(orchNode)

  // レイアウト情報を分析
  const rowThreshold=layouts[0].height*0.3
  const rowsMap=new Map<number,DivisionLayout[]>()
  layouts.forEach(l=>{
   let foundRow=-1
   for(const[rowY]of rowsMap){
    if(Math.abs(l.y-rowY)<rowThreshold){
     foundRow=rowY
     break
    }
   }
   if(foundRow>=0){
    rowsMap.get(foundRow)!.push(l)
   }else{
    rowsMap.set(l.y,[l])
   }
  })
  const rows=Array.from(rowsMap.entries())
   .sort((a,b)=>a[0]-b[0])
   .map(([_,items])=>items.sort((a,b)=>a.x-b.x))

  // 外周道路の座標
  const outerPadding=config.padding*0.5
  const outerLeft=outerPadding
  const outerRight=dimensions.width-outerPadding
  const outerTop=orchExitY+config.padding*0.3
  const outerBottom=dimensions.height-config.padding*1.5

  // 外周ノードを作成
  const perimeterTopLeft:RoadNode={x:outerLeft,y:outerTop,id:'perimeter_tl'}
  const perimeterTopRight:RoadNode={x:outerRight,y:outerTop,id:'perimeter_tr'}
  const perimeterBottomLeft:RoadNode={x:outerLeft,y:outerBottom,id:'perimeter_bl'}
  const perimeterBottomRight:RoadNode={x:outerRight,y:outerBottom,id:'perimeter_br'}
  nodes.push(perimeterTopLeft,perimeterTopRight,perimeterBottomLeft,perimeterBottomRight)

  // 外周道路を接続
  segments.push({from:perimeterTopLeft,to:perimeterTopRight,width:config.roadWidth*0.6})
  segments.push({from:perimeterTopLeft,to:perimeterBottomLeft,width:config.roadWidth*0.6})
  segments.push({from:perimeterTopRight,to:perimeterBottomRight,width:config.roadWidth*0.6})
  segments.push({from:perimeterBottomLeft,to:perimeterBottomRight,width:config.roadWidth*0.6})

  // オーケストラを外周上部中央に接続
  const orchConnection:RoadNode={x:orchX,y:outerTop,id:'orch_conn'}
  nodes.push(orchConnection)
  segments.push({from:orchNode,to:orchConnection,width:config.roadWidth})

  // orchConnectionを外周トップラインに統合
  segments.push({from:perimeterTopLeft,to:orchConnection,width:config.roadWidth*0.6})
  segments.push({from:orchConnection,to:perimeterTopRight,width:config.roadWidth*0.6})
  // 元のトップライン接続を削除する代わりに、分割されたセグメントを使用
  const topLineIdx=segments.findIndex(s=>s.from.id==='perimeter_tl'&&s.to.id==='perimeter_tr')
  if(topLineIdx>=0)segments.splice(topLineIdx,1)

  // 各行の間にギャップ道路を作成
  const gapNodes:RoadNode[][]=[]

  rows.forEach((rowLayouts,rowIndex)=>{
   const rowGapNodes:RoadNode[]=[]

   // この行のY座標（Division box上部のすぐ上）
   const rowY=rowLayouts[0].y-config.padding*0.3

   // 左側ギャップノード
   const leftGap:RoadNode={
    x:outerLeft,
    y:rowY,
    id:`gap_row${rowIndex}_left`
   }
   nodes.push(leftGap)
   rowGapNodes.push(leftGap)

   // Division box間のギャップノード
   for(let i=0;i<rowLayouts.length-1;i++){
    const current=rowLayouts[i]
    const next=rowLayouts[i+1]
    const gapX=(current.x+current.width+next.x)/2

    const gapNode:RoadNode={
     x:gapX,
     y:rowY,
     id:`gap_row${rowIndex}_col${i}`
    }
    nodes.push(gapNode)
    rowGapNodes.push(gapNode)
   }

   // 右側ギャップノード
   const rightGap:RoadNode={
    x:outerRight,
    y:rowY,
    id:`gap_row${rowIndex}_right`
   }
   nodes.push(rightGap)
   rowGapNodes.push(rightGap)

   // 横方向の道路を接続
   for(let i=0;i<rowGapNodes.length-1;i++){
    segments.push({from:rowGapNodes[i],to:rowGapNodes[i+1],width:config.roadWidth*0.7})
   }

   gapNodes.push(rowGapNodes)
  })

  // 縦方向のギャップ道路を作成（外周と各行を接続）
  // 左側外周を各行の左端に接続
  if(gapNodes.length>0){
   segments.push({from:perimeterTopLeft,to:gapNodes[0][0],width:config.roadWidth*0.6})
   for(let i=0;i<gapNodes.length-1;i++){
    segments.push({from:gapNodes[i][0],to:gapNodes[i+1][0],width:config.roadWidth*0.6})
   }
   segments.push({from:gapNodes[gapNodes.length-1][0],to:perimeterBottomLeft,width:config.roadWidth*0.6})

   // 右側外周を各行の右端に接続
   const lastColIdx=(n:RoadNode[])=>n.length-1
   segments.push({from:perimeterTopRight,to:gapNodes[0][lastColIdx(gapNodes[0])],width:config.roadWidth*0.6})
   for(let i=0;i<gapNodes.length-1;i++){
    segments.push({
     from:gapNodes[i][lastColIdx(gapNodes[i])],
     to:gapNodes[i+1][lastColIdx(gapNodes[i+1])],
     width:config.roadWidth*0.6
    })
   }
   segments.push({
    from:gapNodes[gapNodes.length-1][lastColIdx(gapNodes[gapNodes.length-1])],
    to:perimeterBottomRight,
    width:config.roadWidth*0.6
   })

   // Division box間の縦方向道路を接続
   for(let rowIdx=0;rowIdx<gapNodes.length-1;rowIdx++){
    const currentRow=gapNodes[rowIdx]
    const nextRow=gapNodes[rowIdx+1]

    // 内部ギャップノード同士を接続
    const minLen=Math.min(currentRow.length,nextRow.length)
    for(let colIdx=1;colIdx<minLen-1;colIdx++){
     segments.push({from:currentRow[colIdx],to:nextRow[colIdx],width:config.roadWidth*0.5})
    }
   }
  }

  // 各Division boxのエントリーノードを作成し、最寄りのギャップノードに接続
  layouts.forEach((layout,i)=>{
   const entryPadding=layout.height*0.05
   const entryNode:RoadNode={
    x:layout.x+layout.width/2,
    y:layout.y-entryPadding,
    id:`div_entry_${i}`
   }
   const innerNode:RoadNode={
    x:layout.x+layout.width/2,
    y:layout.y+layout.height*0.5,
    id:`div_inner_${i}`
   }
   nodes.push(entryNode,innerNode)

   // Division入口から内部への道路
   segments.push({from:entryNode,to:innerNode,width:config.roadWidth*0.7})

   // 最寄りのギャップノードを見つけて接続
   let nearestGap:RoadNode|null=null
   let minDist=Infinity
   gapNodes.flat().forEach(gapNode=>{
    const dist=Math.hypot(gapNode.x-entryNode.x,gapNode.y-entryNode.y)
    if(dist<minDist){
     minDist=dist
     nearestGap=gapNode
    }
   })
   if(nearestGap){
    segments.push({from:nearestGap,to:entryNode,width:config.roadWidth*0.6})
   }
  })

  // 交差点を検出して追加
  const intersections:RoadNode[]=[]
  for(let i=0;i<segments.length;i++){
   for(let j=i+1;j<segments.length;j++){
    const seg1=segments[i]
    const seg2=segments[j]

    // 同じノードを共有している場合はスキップ
    if(seg1.from.id===seg2.from.id||seg1.from.id===seg2.to.id||
       seg1.to.id===seg2.from.id||seg1.to.id===seg2.to.id)continue

    const intersection=getLineIntersection(seg1.from,seg1.to,seg2.from,seg2.to)
    if(intersection){
     // 既存のノードや交差点と近すぎないかチェック
     const tooClose=[...nodes,...intersections].some(n=>
      Math.hypot(n.x-intersection.x,n.y-intersection.y)<config.nodeRadius*3
     )
     if(!tooClose){
      const intNode:RoadNode={
       x:intersection.x,
       y:intersection.y,
       id:`intersection_${intersections.length}`,
       isIntersection:true
      }
      intersections.push(intNode)
     }
    }
   }
  }

  // 交差点をノードに追加し、セグメントを分割
  intersections.forEach(intNode=>{
   nodes.push(intNode)

   const newSegments:RoadSegment[]=[]
   const toRemove:number[]=[]

   segments.forEach((seg,idx)=>{
    const onSegment=isPointOnSegment(intNode,seg.from,seg.to,config.nodeRadius*2)
    if(onSegment){
     toRemove.push(idx)
     newSegments.push({from:seg.from,to:intNode,width:seg.width})
     newSegments.push({from:intNode,to:seg.to,width:seg.width})
    }
   })

   for(let i=toRemove.length-1;i>=0;i--){
    segments.splice(toRemove[i],1)
   }
   segments.push(...newSegments)
  })

  roadNodesRef.current=nodes
  roadSegmentsRef.current=segments
 },[dimensions,calculateLayoutConfig])

 // 点がセグメント上にあるかチェック
 function isPointOnSegment(
  p:{x:number,y:number},
  a:{x:number,y:number},
  b:{x:number,y:number},
  tolerance:number
 ):boolean{
  const d1=Math.hypot(p.x-a.x,p.y-a.y)
  const d2=Math.hypot(p.x-b.x,p.y-b.y)
  const lineLen=Math.hypot(b.x-a.x,b.y-a.y)
  return Math.abs(d1+d2-lineLen)<tolerance
 }

 // A*による経路探索
 const findPath=useCallback((
  fromX:number,fromY:number,
  toX:number,toY:number,
  lane:number
 ):Array<{x:number,y:number}>=>{
  const nodes=roadNodesRef.current
  const segments=roadSegmentsRef.current
  const config=layoutConfigRef.current

  if(nodes.length===0||segments.length===0||!config){
   return[{x:fromX,y:fromY},{x:toX,y:toY}]
  }

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

  if(startNode.id===endNode.id){
   return[{x:fromX,y:fromY},{x:toX,y:toY}]
  }

  const getNeighbors=(node:RoadNode):RoadNode[]=>{
   const neighbors:RoadNode[]=[]
   for(const seg of segments){
    if(seg.from.id===node.id){
     const n=nodes.find(n=>n.id===seg.to.id)
     if(n)neighbors.push(n)
    }
    if(seg.to.id===node.id){
     const n=nodes.find(n=>n.id===seg.from.id)
     if(n)neighbors.push(n)
    }
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

  let iterations=0
  const maxIterations=nodes.length*10

  while(openSet.size>0&&iterations++<maxIterations){
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
    const path:Array<{x:number,y:number}>=[]
    let curr:RoadNode|undefined=current
    while(curr){
     // 車線オフセットを適用（進行方向に垂直）
     const prev=cameFrom.get(curr.id)
     let laneOffX=0,laneOffY=0
     if(prev){
      const dx=curr.x-prev.x
      const dy=curr.y-prev.y
      const len=Math.hypot(dx,dy)
      if(len>0){
       // 垂直方向にオフセット
       laneOffX=(-dy/len)*config.laneOffset*(lane===0?-1:1)
       laneOffY=(dx/len)*config.laneOffset*(lane===0?-1:1)
      }
     }
     path.unshift({x:curr.x+laneOffX,y:curr.y+laneOffY})
     curr=cameFrom.get(curr.id)
    }
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

  return[{x:fromX,y:fromY},{x:toX,y:toY}]
 },[])

 // Update character positions
 useEffect(()=>{
  const positions=positionsRef.current
  const{orchestrator,divisions}=groupCharacters()
  const layouts=calculateDivisionLayouts(divisions)
  const config=calculateLayoutConfig()

  buildRoadNetwork(layouts)

  const currentIds=new Set(characters.map(c=>c.agentId))
  for(const id of positions.keys()){
   if(!currentIds.has(id)){
    positions.delete(id)
   }
  }

  let laneCounter=0

  if(orchestrator){
   const x=dimensions.width/2
   const y=config.orchestraY+config.orchestraHeight*0.5
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

  layouts.forEach(layout=>{
   if(layout.divisionChar){
    const x=layout.x+layout.width/2
    const y=layout.y+config.spriteSize/2+layout.height*0.08
    const existing=positions.get(layout.divisionChar.agentId)
    if(existing){
     if(Math.hypot(existing.targetX-x,existing.targetY-y)>5){
      existing.pathPoints=findPath(existing.x,existing.y,x,y,existing.lane)
      existing.pathIndex=0
     }
     existing.targetX=x
     existing.targetY=y
     existing.targetScale=1.0
     existing.targetOpacity=1
    }else{
     const lane=laneCounter++%2
     const startY=config.orchestraY+config.orchestraHeight+config.padding*0.5
     positions.set(layout.divisionChar.agentId,{
      x:dimensions.width/2,y:startY,
      targetX:x,targetY:y,
      scale:0,targetScale:1.0,
      opacity:0,targetOpacity:1,
      summoned:false,summonProgress:0,
      summonEffect:getSummonEffect(layout.divisionChar.agentType),
      pathPoints:findPath(dimensions.width/2,startY,x,y,lane),
      pathIndex:0,lane
     })
    }
   }

   const visibleWorkers=layout.workers.slice(0,MAX_VISIBLE_WORKERS)
   const workerCount=Math.min(visibleWorkers.length,MAX_VISIBLE_WORKERS)
   const workerAreaY=layout.y+config.spriteSize+layout.height*0.2
   const workerAreaHeight=layout.height-config.spriteSize-layout.height*0.25
   const workerSpacing=Math.min(config.spriteSize+layout.height*0.05,workerAreaHeight/Math.max(workerCount,1))

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
     const spawnY=layout.y+config.spriteSize/2+layout.height*0.08
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
 },[characters,dimensions,characterScale,groupCharacters,calculateDivisionLayouts,calculateLayoutConfig,buildRoadNetwork,findPath])

 // 召喚エフェクト描画関数
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

  ctx.strokeStyle=NIER_COLORS.magicCircle
  ctx.lineWidth=2
  ctx.globalAlpha=progress*0.8
  ctx.beginPath()
  ctx.arc(0,0,radius,0,Math.PI*2)
  ctx.stroke()

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

  ctx.rotate(-rotation*2)
  ctx.beginPath()
  ctx.arc(0,0,radius*0.4,0,Math.PI*2)
  ctx.stroke()

  const runeCount=8
  for(let i=0;i<runeCount;i++){
   const angle=(i/runeCount)*Math.PI*2+rotation*0.5
   const rx=Math.cos(angle)*radius*0.85
   const ry=Math.sin(angle)*radius*0.85
   ctx.fillStyle=NIER_COLORS.magicCircle
   ctx.globalAlpha=progress*(0.5+Math.sin(frame*0.1+i)*0.3)
   ctx.fillRect(rx-2,ry-4,4,8)
  }

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

  const boltCount=3
  for(let b=0;b<boltCount;b++){
   const seed=frame*0.3+b*100
   ctx.strokeStyle=b===0?NIER_COLORS.lightning:'rgba(255,255,200,0.5)'
   ctx.lineWidth=b===0?3:1

   ctx.beginPath()
   let bx=x+(Math.sin(seed+b)*size*0.4)
   let by=y-size*1.5
   ctx.moveTo(bx,by)

   const segments=6+Math.floor(progress*4)
   for(let i=0;i<segments;i++){
    const t=i/segments
    bx+=(Math.random()-0.5)*size*0.6*progress
    by+=size*1.5/segments
    if(t<progress)ctx.lineTo(bx,by)
   }
   ctx.stroke()

   if(progress>0.5&&b===0){
    ctx.lineWidth=1
    ctx.beginPath()
    ctx.moveTo(bx,by-size*0.3)
    ctx.lineTo(bx+size*0.4*(Math.random()-0.5),by+10)
    ctx.lineTo(bx+size*0.6*(Math.random()-0.5),by+25)
    ctx.stroke()
   }
  }

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

  ctx.strokeStyle=NIER_COLORS.warpGate
  ctx.lineWidth=3
  ctx.globalAlpha=openProgress*0.8

  ctx.beginPath()
  ctx.ellipse(0,0,gateWidth/2*openProgress,gateHeight/2,0,0,Math.PI*2)
  ctx.stroke()

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

   if(mergeProgress<0.8){
    ctx.strokeStyle=`rgba(180,160,120,${(1-mergeProgress)*0.5})`
    ctx.lineWidth=1
    ctx.beginPath()
    ctx.moveTo(fx,fy)
    ctx.lineTo(x+Math.cos(angle)*distance*1.3,y+Math.sin(angle)*distance*1.3)
    ctx.stroke()
   }

   ctx.fillStyle=`rgba(200,180,140,${0.5+mergeProgress*0.5})`
   ctx.beginPath()
   ctx.arc(fx,fy,fragSize,0,Math.PI*2)
   ctx.fill()
  }

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

 // 道路と交差点を描画
 const drawRoads=useCallback((ctx:CanvasRenderingContext2D)=>{
  const segments=roadSegmentsRef.current
  const nodes=roadNodesRef.current

  ctx.save()

  // 道路セグメントを描画
  segments.forEach(seg=>{
   ctx.strokeStyle=NIER_COLORS.roadLine
   ctx.lineWidth=seg.width
   ctx.lineCap='round'
   ctx.beginPath()
   ctx.moveTo(seg.from.x,seg.from.y)
   ctx.lineTo(seg.to.x,seg.to.y)
   ctx.stroke()

   // 中央線
   ctx.strokeStyle=NIER_COLORS.roadCenter
   ctx.lineWidth=1
   ctx.setLineDash([seg.width*0.2,seg.width*0.2])
   ctx.beginPath()
   ctx.moveTo(seg.from.x,seg.from.y)
   ctx.lineTo(seg.to.x,seg.to.y)
   ctx.stroke()
   ctx.setLineDash([])
  })

  // 交差点を描画
  nodes.filter(n=>n.isIntersection).forEach(node=>{
   const config=layoutConfigRef.current
   if(!config)return

   // 交差点マーカー
   ctx.fillStyle=NIER_COLORS.intersection
   ctx.beginPath()
   ctx.arc(node.x,node.y,config.nodeRadius*1.5,0,Math.PI*2)
   ctx.fill()

   // 交差点の枠
   ctx.strokeStyle=NIER_COLORS.primaryDim
   ctx.lineWidth=1
   ctx.beginPath()
   ctx.arc(node.x,node.y,config.nodeRadius*1.5,0,Math.PI*2)
   ctx.stroke()
  })

  ctx.restore()
 },[])

 const drawOrchestraArea=useCallback((
  ctx:CanvasRenderingContext2D,
  orchestrator:CharacterState|undefined,
  frame:number
 )=>{
  const config=layoutConfigRef.current
  if(!config)return

  const centerX=dimensions.width/2
  const y=config.orchestraY
  const width=Math.min(dimensions.width*0.5,dimensions.width-config.padding*4)
  const height=config.orchestraHeight

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

  const cs=width*0.04
  ctx.fillStyle=NIER_COLORS.primary
  ;[[centerX-width/2,y],[centerX+width/2-cs,y],[centerX-width/2,y+height-cs],[centerX+width/2-cs,y+height-cs]]
   .forEach(([cx,cy])=>{
    ctx.fillRect(cx,cy,cs,2)
    ctx.fillRect(cx,cy,2,cs)
   })

  ctx.fillStyle=NIER_COLORS.textMain
  ctx.font=`bold ${Math.max(10,width*0.04)}px "Courier New", monospace`
  ctx.textAlign='center'
  ctx.fillText('[ ORCHESTRATOR ]',centerX,y+height-height*0.08)
 },[dimensions])

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

  const cs=width*0.04
  ctx.fillStyle=isActive?NIER_COLORS.accent:NIER_COLORS.primaryDim
  ;[[x,y],[x+width-cs,y],[x,y+height-cs],[x+width-cs,y+height-cs]].forEach(([cx,cy])=>{
   ctx.fillRect(cx,cy,cs,2)
   ctx.fillRect(cx,cy,2,cs)
  })

  ctx.fillStyle=NIER_COLORS.textDim
  ctx.font=`${Math.max(8,width*0.05)}px "Courier New", monospace`
  ctx.textAlign='center'
  ctx.fillText(`[ ${hierarchy?.groupLabel||agentType} ]`,x+width/2,y+height-height*0.04)

  if(workers.length>MAX_VISIBLE_WORKERS){
   const extraCount=workers.length-MAX_VISIBLE_WORKERS
   ctx.fillStyle=NIER_COLORS.accent
   ctx.font=`bold ${Math.max(9,width*0.055)}px "Courier New", monospace`
   ctx.textAlign='right'
   ctx.fillText(`+${extraCount}`,x+width-width*0.04,y+height-height*0.04)

   const indicatorX=x+width-width*0.1
   const indicatorY=y+height-height*0.15
   for(let i=0;i<Math.min(extraCount,3);i++){
    ctx.strokeStyle=`rgba(180,160,120,${0.6-i*0.15})`
    ctx.lineWidth=1
    ctx.beginPath()
    ctx.arc(indicatorX,indicatorY,width*0.03+i*width*0.02+Math.sin(frame*0.1+i)*1,0,Math.PI*2)
    ctx.stroke()
   }
  }
 },[])

 const drawSpeechBubble=useCallback((
  ctx:CanvasRenderingContext2D,
  x:number,y:number,
  text:string,
  scale:number
 )=>{
  const config=layoutConfigRef.current
  if(!config)return

  const fontSize=Math.max(9,config.spriteSize*0.22*scale)
  ctx.font=`${fontSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`

  const padding=fontSize*0.5
  const lineHeight=fontSize*1.3
  const maxLineWidth=config.spriteSize*3*scale

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

  const bubbleX=Math.round(x+config.spriteSize*scale*0.8)
  const bubbleY=Math.round(y-bubbleHeight/2)

  ctx.fillStyle='#e8e4d8'
  ctx.fillRect(bubbleX,bubbleY,bubbleWidth,bubbleHeight)
  ctx.strokeStyle='#8a8070'
  ctx.lineWidth=1
  ctx.strokeRect(bubbleX+0.5,bubbleY+0.5,bubbleWidth-1,bubbleHeight-1)

  ctx.fillStyle='#e8e4d8'
  ctx.beginPath()
  ctx.moveTo(bubbleX,y-fontSize*0.4)
  ctx.lineTo(bubbleX-fontSize*0.7,y)
  ctx.lineTo(bubbleX,y+fontSize*0.4)
  ctx.closePath()
  ctx.fill()

  ctx.fillStyle='#3a3530'
  ctx.textAlign='left'
  lines.forEach((line,i)=>{
   ctx.fillText(line,bubbleX+padding,bubbleY+padding+(i+1)*lineHeight-fontSize*0.25)
  })
 },[])

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
   const config=layoutConfigRef.current

   if(!config){
    animationRef.current=requestAnimationFrame(render)
    return
   }

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
       orchPos.x,orchPos.y+config.spriteSize*orchPos.scale/2+config.padding*0.5,
       layout.x+layout.width/2,layout.y,
       isActive,frame
      )
     })
    }
   }

   // Update and draw all characters
   const moveSpeed=dimensions.width*0.004

   characters.forEach(char=>{
    const pos=positions.get(char.agentId)
    if(!pos)return

    // 道路に沿った移動
    if(pos.pathPoints.length>0&&pos.pathIndex<pos.pathPoints.length-1){
     const target=pos.pathPoints[pos.pathIndex+1]
     const dx=target.x-pos.x
     const dy=target.y-pos.y
     const dist=Math.hypot(dx,dy)

     if(dist<moveSpeed){
      pos.x=target.x
      pos.y=target.y
      pos.pathIndex++
     }else{
      pos.x+=dx/dist*moveSpeed
      pos.y+=dy/dist*moveSpeed
     }
    }else{
     const easeSpeed=0.06
     pos.x+=(pos.targetX-pos.x)*easeSpeed
     pos.y+=(pos.targetY-pos.y)*easeSpeed
    }

    pos.scale+=(pos.targetScale-pos.scale)*0.08
    pos.opacity+=(pos.targetOpacity-pos.opacity)*0.08

    if(!pos.summoned){
     pos.summonProgress++
     if(pos.summonProgress>=SUMMON_DURATION){
      pos.summoned=true
     }
    }

    if(pos.opacity<0.01||pos.scale<0.01)return

    const isWorking=char.status==='working'
    const isActive=char.isActive??isWorking
    const charConfig=getAgentDisplayConfig(char.agentType)
    const progress=pos.summonProgress/SUMMON_DURATION

    if(!pos.summoned){
     const effectSize=config.spriteSize*pos.targetScale
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

    let alpha=pos.opacity
    if(!isActive)alpha*=0.5
    if(!pos.summoned){
     const showThreshold=pos.summonEffect==='magic_circle'?0.7:
      pos.summonEffect==='lightning'?0.4:0.5
     if(progress<showThreshold)alpha=0
     else alpha*=(progress-showThreshold)/(1-showThreshold)
    }

    if(alpha>0.01){
     ctx.globalAlpha=alpha
     drawPixelCharacter(ctx,pos.x,pos.y,char.agentType,isWorking,frame,pos.scale*characterScale)
     ctx.globalAlpha=1.0

     const labelSize=Math.max(8,config.spriteSize*0.2*pos.scale)
     ctx.font=`${labelSize}px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif`
     ctx.fillStyle=isActive?NIER_COLORS.textMain:NIER_COLORS.textDim
     ctx.textAlign='center'
     ctx.fillText(charConfig.label,pos.x,pos.y+config.spriteSize*pos.scale/2+labelSize*1.2)

     if(isWorking&&char.request){
      drawSpeechBubble(ctx,pos.x,pos.y,char.request.input,pos.scale)
     }
    }
   })

   // Status display
   const activeCount=characters.filter(c=>c.status==='working').length
   const statusFontSize=Math.max(9,dimensions.width*0.012)
   ctx.fillStyle=NIER_COLORS.textDim
   ctx.font=`${statusFontSize}px "Courier New", monospace`
   ctx.textAlign='left'
   ctx.fillText(`AGENTS: ${characters.length}`,config.padding,dimensions.height-config.padding*0.5)
   ctx.fillText(`ACTIVE: ${activeCount}`,config.padding+dimensions.width*0.12,dimensions.height-config.padding*0.5)

   animationRef.current=requestAnimationFrame(render)
  }

  render()

  return()=>{
   if(animationRef.current)cancelAnimationFrame(animationRef.current)
  }
 },[characters,dimensions,characterScale,groupCharacters,calculateDivisionLayouts,
  drawOrchestraArea,drawDivisionBox,drawSpeechBubble,drawConnectionLine,drawRoads,
  drawMagicCircle,drawLightning,drawWarpGate,drawMergeEffect])

 const handleClick=useCallback((e:React.MouseEvent<HTMLCanvasElement>)=>{
  if(!onCharacterClick)return

  const canvas=canvasRef.current
  if(!canvas)return

  const rect=canvas.getBoundingClientRect()
  const x=e.clientX-rect.left
  const y=e.clientY-rect.top
  const positions=positionsRef.current
  const config=layoutConfigRef.current

  if(!config)return

  for(const char of characters){
   const pos=positions.get(char.agentId)
   if(!pos)continue

   const spriteSize=config.spriteSize*pos.scale
   const dist=Math.hypot(x-pos.x,y-pos.y)
   if(dist<spriteSize/2+spriteSize*0.25){
    onCharacterClick(char)
    return
   }
  }
 },[characters,onCharacterClick])

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
