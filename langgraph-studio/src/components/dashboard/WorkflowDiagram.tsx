import{useEffect,useState,useCallback,useMemo,useRef}from'react'
import{
 ReactFlow,
 Node,
 Edge,
 Position,
 MarkerType,
 Background,
 BackgroundVariant,
 Handle,
 useReactFlow,
 ReactFlowProvider,
}from'@xyflow/react'
import'@xyflow/react/dist/style.css'

import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentStore}from'@/stores/agentStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import{agentApi}from'@/services/apiService'
import{convertApiAgents}from'@/services/converters/agentConverter'
import{COLORS}from'@/constants/colors'
import{TIMING}from'@/constants/timing'
import type{Agent,AgentType,AgentStatus}from'@/types/agent'
import type{AssetGenerationOptions}from'@/config/projectOptions'

interface AgentNodeDef{
 id:string
 type:AgentType
 label:string
 uiPhaseIndex:number
 hasLW?:boolean
}

interface LayoutConfig{
 nodeHeight:number
 nodeWidth:number
 phasePadding:number
 nodeGapY:number
 phaseGapX:number
 fontSize:number
}

function calculateLayoutConfig(
 containerWidth:number,
 containerHeight:number,
 numPhases:number,
 maxNodesInPhase:number,
 maxLabelLength:number
):LayoutConfig{
 const NUM_PHASES=numPhases||4
 const MAX_NODES_IN_PHASE=maxNodesInPhase||7
 const MAX_LABEL_LENGTH=maxLabelLength||6
 const MIN_NODE_HEIGHT=28
 const MAX_NODE_HEIGHT=60
 const MIN_FONT_SIZE=9
 const MAX_FONT_SIZE=14
 const NODE_PADDING_X=12

 const availableHeight=containerHeight-40
 const availableWidth=containerWidth-40

 const verticalFactor=MAX_NODES_IN_PHASE+0.2*(MAX_NODES_IN_PHASE-1)+0.6
 let nodeHeight=availableHeight/verticalFactor
 nodeHeight=Math.max(MIN_NODE_HEIGHT,Math.min(MAX_NODE_HEIGHT,nodeHeight))

 const horizontalFactor=NUM_PHASES+0.6*(NUM_PHASES-1)+0.4
 let nodeWidth=availableWidth/horizontalFactor

 const maxFontSizeForWidth=(nodeWidth-NODE_PADDING_X*2)/(MAX_LABEL_LENGTH||6)

 const maxFontSizeForHeight=(nodeHeight-8)/1.5

 let fontSize=Math.min(maxFontSizeForWidth,maxFontSizeForHeight)
 fontSize=Math.max(MIN_FONT_SIZE,Math.min(MAX_FONT_SIZE,fontSize))

 nodeWidth=fontSize*(MAX_LABEL_LENGTH||6)+NODE_PADDING_X*2

 return{
  nodeHeight:Math.round(nodeHeight),
  nodeWidth:Math.round(nodeWidth),
  phasePadding:Math.round(nodeHeight*0.3),
  nodeGapY:Math.round(nodeHeight*0.2),
  phaseGapX:Math.round(nodeWidth*0.6),
  fontSize:Math.round(fontSize),
 }
}

const DEFAULT_LAYOUT_CONFIG:LayoutConfig={
 nodeHeight:36,
 nodeWidth:101,
 phasePadding:11,
 nodeGapY:7,
 phaseGapX:61,
 fontSize:11,
}

function getColumnLayout(
 agentNodes:AgentNodeDef[],
 numPhases:number,
 config:LayoutConfig
):{
 positions:Record<string,{x:number;y:number}>
 widths:Record<string,number>
 heights:Record<string,number>
 width:number
 height:number
}{
 const{nodeHeight,nodeWidth,phasePadding,nodeGapY,phaseGapX}=config
 const positions:Record<string,{x:number;y:number}>={}
 const widths:Record<string,number>={}
 const heights:Record<string,number>={}

 agentNodes.forEach(node=>{
  widths[node.id]=nodeWidth
  heights[node.id]=nodeHeight
 })

 const phaseNodes:AgentNodeDef[][]=[]
 for(let i=0;i<numPhases;i++){
  phaseNodes[i]=agentNodes.filter(n=>n.uiPhaseIndex===i)
 }

 const phaseWidths=phaseNodes.map(nodes=>nodes.length>0?nodeWidth : 0)

 const calcPhaseHeight=(nodes:AgentNodeDef[])=>{
  if(nodes.length===0)return 0
  const totalNodeHeights=nodes.length*nodeHeight
  const totalGaps=(nodes.length-1)*nodeGapY
  return totalNodeHeights+totalGaps
 }

 const phaseHeights=phaseNodes.map(calcPhaseHeight)
 const maxHeight=Math.max(...phaseHeights,0)

 const phaseX:number[]=[]
 phaseX[0]=phasePadding
 for(let i=1;i<numPhases;i++){
  phaseX[i]=phaseX[i-1]+(phaseWidths[i-1]>0?phaseWidths[i-1]+phaseGapX : 0)
 }

 const positionPhaseNodes=(nodes:AgentNodeDef[],x:number)=>{
  let currentY=phasePadding
  nodes.forEach((node)=>{
   positions[node.id]={
    x:x,
    y:currentY,
   }
   currentY+=nodeHeight+nodeGapY
  })
 }

 for(let i=0;i<numPhases;i++){
  if(phaseNodes[i].length>0){
   positionPhaseNodes(phaseNodes[i],phaseX[i])
  }
 }

 const lastPhaseIdx=numPhases-1
 const totalWidth=(phaseX[lastPhaseIdx]||0)+(phaseWidths[lastPhaseIdx]||0)+phasePadding
 const totalHeight=maxHeight+phasePadding*2

 return{positions,widths,heights,width:totalWidth,height:totalHeight}
}

function calculatePhaseBounds(
 phaseIndex:number,
 agentNodes:AgentNodeDef[],
 positions:Record<string,{x:number;y:number}>,
 widths:Record<string,number>,
 heights:Record<string,number>,
 config:LayoutConfig
):{x:number;y:number;width:number;height:number}{
 const phaseNodes=agentNodes.filter(n=>n.uiPhaseIndex===phaseIndex)
 if(phaseNodes.length===0){
  return{x:0,y:0,width:0,height:0}
 }

 const nodePositions=phaseNodes.map(n=>positions[n.id]).filter(Boolean)
 if(nodePositions.length===0)return{x:0,y:0,width:0,height:0}

 const nodeWidths=phaseNodes.map(n=>widths[n.id]||0)
 const nodeHeights=phaseNodes.map(n=>heights[n.id]||0)

 const minX=Math.min(...nodePositions.map(p=>p.x))
 const maxX=Math.max(...nodePositions.map((p,i)=>p.x+nodeWidths[i]))
 const minY=Math.min(...nodePositions.map(p=>p.y))
 const maxY=Math.max(...nodePositions.map((p,i)=>p.y+nodeHeights[i]))

 return{
  x:minX-config.phasePadding,
  y:minY-config.phasePadding,
  width:(maxX-minX)+config.phasePadding*2,
  height:(maxY-minY)+config.phasePadding*2+20,
 }
}

function getStatusStyle(status:AgentStatus|undefined):{
 background:string
 border:string
 color:string
}{
 switch(status){
  case'completed':
   return{background:COLORS.status.completed.bg,border:COLORS.status.completed.border,color:COLORS.status.completed.text}
  case'running':
   return{background:COLORS.status.running.bg,border:COLORS.status.running.border,color:COLORS.status.running.text}
  case'waiting_approval':
   return{background:COLORS.status.waitingApproval.bg,border:COLORS.status.waitingApproval.border,color:COLORS.status.waitingApproval.text}
  case'failed':
   return{background:COLORS.status.failed.bg,border:COLORS.status.failed.border,color:COLORS.status.failed.text}
  case'pending':
  default:
   return{background:COLORS.status.pending.bg,border:COLORS.status.pending.border,color:COLORS.status.pending.text}
 }
}

interface AgentNodeData{
 label:string
 status?:AgentStatus
 progress?:number
 hasLW?:boolean
 nodeWidth:number
 nodeHeight:number
 fontSize:number
}

function AgentNode({data }:{data:AgentNodeData}){
 const style=getStatusStyle(data.status)
 const isRunning=data.status==='running'
 const isCompleted=data.status==='completed'
 const isWaitingApproval=data.status==='waiting_approval'
 const progress=data.progress ?? 0
 const{nodeWidth,nodeHeight,fontSize}=data

 return(
  <div
   className={`relative rounded text-center flex flex-col justify-center ${isRunning||isWaitingApproval?'animate-pulse' : ''}`}
   style={{
    background:style.background,
    border:`1.5px solid ${style.border}`,
    color:style.color,
    width:nodeWidth,
    height:nodeHeight,
    boxShadow:isRunning?`0 0 8px ${style.border}` : isWaitingApproval?`0 0 6px ${style.border}` : 'none',
   }}
  >
   {/*Connection handles-invisible but needed for edge connections*/}
   <Handle type="target" position={Position.Left} id="left" style={{opacity:0,width:1,height:1}}/>
   <Handle type="target" position={Position.Top} id="top" style={{opacity:0,width:1,height:1}}/>
   <Handle type="source" position={Position.Right} id="right" style={{opacity:0,width:1,height:1}}/>
   <Handle type="source" position={Position.Bottom} id="bottom" style={{opacity:0,width:1,height:1}}/>

   <div className="font-medium whitespace-nowrap" style={{fontSize}}>{data.label}</div>
   {(isRunning||isCompleted)&&(
    <div className="mt-1 px-2">
     <div className="h-1 bg-black/10 rounded-full overflow-hidden">
      <div
       className="h-full transition-all duration-300"
       style={{
        width:`${progress}%`,
        background:isCompleted?COLORS.progress.completed:COLORS.progress.running,
       }}
      />
     </div>
     {isRunning&&(
      <div className="mt-0.5" style={{fontSize:fontSize*0.8,color:COLORS.progress.running}}>
       {progress}%
      </div>
)}
    </div>
)}
   {isWaitingApproval&&(
    <div className="mt-0.5" style={{fontSize:fontSize*0.8,color:COLORS.badge.waitingApproval,fontWeight:'bold'}}>
     承認待ち
    </div>
)}
   {/*L/W indicator in bottom right*/}
   {data.hasLW&&(
    <div
     className="absolute"
     style={{
      bottom:'2px',
      right:'4px',
      fontSize:fontSize*0.7,
      color:style.color,
      opacity:0.7,
     }}
    >
     L/W
    </div>
)}
   {isCompleted&&(
    <div
     className="absolute -top-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center"
     style={{fontSize:fontSize*0.8,color:'white',fontWeight:'bold',background:COLORS.progress.completed}}
    >
     ✓
    </div>
)}
   {isWaitingApproval&&(
    <div
     className="absolute -top-1 -right-1 w-4 h-4 rounded-full flex items-center justify-center"
     style={{fontSize:fontSize*0.8,color:'white',fontWeight:'bold',background:COLORS.badge.waitingApproval}}
    >
     !
    </div>
)}
  </div>
)
}

function PhaseGroupNode({data }:{data:{label:string;width:number;height:number}}){
 return(
  <div
   style={{
    width:data.width,
    height:data.height,
    background:COLORS.canvas.phaseGroup.bg,
    border:`1px dashed ${COLORS.canvas.phaseGroup.border}`,
    borderRadius:'4px',
    position:'relative',
   }}
  >
   <div
    style={{
     position:'absolute',
     bottom:'4px',
     left:'8px',
     fontSize:'11px',
     color:COLORS.canvas.phaseGroup.text,
     fontWeight:500,
    }}
   >
    {data.label}
   </div>
  </div>
)
}

const nodeTypes={
 agent:AgentNode,
 phaseGroup:PhaseGroupNode,
}

interface FlowCanvasProps{
 nodes:Node[]
 edges:Edge[]
 onContainerResize:(width:number,height:number)=>void
}

function FlowCanvas({nodes,edges,onContainerResize}:FlowCanvasProps){
 const containerRef=useRef<HTMLDivElement>(null)
 const{fitView}=useReactFlow()
 const[containerSize,setContainerSize]=useState({width:0,height:0})

 useEffect(()=>{
  const container=containerRef.current
  if(!container)return

  const resizeObserver=new ResizeObserver((entries)=>{
   for(const entry of entries){
    const{width,height}=entry.contentRect
    setContainerSize({width,height})
    onContainerResize(width,height)
   }
  })

  resizeObserver.observe(container)
  return()=>resizeObserver.disconnect()
 },[onContainerResize])

 useEffect(()=>{
  if(containerSize.width>0&&containerSize.height>0&&nodes.length>0){
   const timer=setTimeout(()=>{
    fitView({padding:0.05,duration:200})
   },TIMING.animation.fitViewDelay)
   return()=>clearTimeout(timer)
  }
 },[containerSize,nodes,fitView])

 return(
  <div
   ref={containerRef}
   className="w-full"
   style={{height:'35vh'}}
  >
   <ReactFlow
    nodes={nodes}
    edges={edges}
    nodeTypes={nodeTypes}
    fitView
    fitViewOptions={{padding:0.05}}
    nodesDraggable={false}
    nodesConnectable={false}
    elementsSelectable={false}
    panOnDrag={false}
    zoomOnScroll={false}
    zoomOnPinch={false}
    zoomOnDoubleClick={false}
    preventScrolling={false}
    proOptions={{hideAttribution:true}}
    defaultEdgeOptions={{type:'straight'}}
   >
    <Background
     variant={BackgroundVariant.Dots}
     gap={16}
     size={0.5}
     color={COLORS.canvas.background}
    />
   </ReactFlow>
  </div>
)
}

export default function WorkflowDiagram():JSX.Element{
 const{currentProject}=useProjectStore()
 const{agents,setAgents}=useAgentStore()
 const{getLabel,getFilteredUIPhases,getWorkflowDependencies,fetchDefinitions,loaded:definitionsLoaded}=useAgentDefinitionStore()
 const{agentRoles}=useUIConfigStore()
 const[containerSize,setContainerSize]=useState({width:0,height:0})

 const handleContainerResize=useCallback((width:number,height:number)=>{
  setContainerSize({width,height})
 },[])

 useEffect(()=>{
  if(!definitionsLoaded)fetchDefinitions()
 },[definitionsLoaded,fetchDefinitions])

 const assetGeneration=currentProject?.config?.assetGeneration as AssetGenerationOptions|undefined
 const uiPhases=useMemo(()=>getFilteredUIPhases(assetGeneration),[assetGeneration,getFilteredUIPhases])
 const workflowDeps=useMemo(()=>getWorkflowDependencies(),[getWorkflowDependencies])

 const agentNodes=useMemo<AgentNodeDef[]>(()=>{
  const nodes:AgentNodeDef[]=[]
  uiPhases.forEach((phase,phaseIndex)=>{
   phase.agents.forEach(agentType=>{
    const role=agentRoles[agentType]||'worker'
    const hasLW=role==='worker'||role==='tester'
    nodes.push({
     id:agentType,
     type:agentType as AgentType,
     label:agentType,
     uiPhaseIndex:phaseIndex,
     hasLW
    })
   })
  })
  return nodes
 },[uiPhases,agentRoles])

 const edgeDefs=useMemo<{source:string;target:string}[]>(()=>{
  const edges:{source:string;target:string}[]=[]
  const agentSet=new Set(agentNodes.map(n=>n.id))
  for(const[target,sources]of Object.entries(workflowDeps)){
   if(!agentSet.has(target))continue
   for(const source of sources){
    if(agentSet.has(source)){
     edges.push({source,target})
    }
   }
  }
  return edges
 },[agentNodes,workflowDeps])

 const maxLabelLength=useMemo(()=>{
  if(agentNodes.length===0)return 6
  return Math.max(...agentNodes.map(n=>getLabel(n.type).length),6)
 },[agentNodes,getLabel])

 const maxNodesInPhase=useMemo(()=>{
  if(uiPhases.length===0)return 7
  return Math.max(...uiPhases.map(p=>p.agents.length),1)
 },[uiPhases])

 const layoutConfig=useMemo(()=>{
  if(containerSize.width>0&&containerSize.height>0){
   return calculateLayoutConfig(containerSize.width,containerSize.height,uiPhases.length,maxNodesInPhase,maxLabelLength)
  }
  return DEFAULT_LAYOUT_CONFIG
 },[containerSize,uiPhases.length,maxNodesInPhase,maxLabelLength])

 useEffect(()=>{
  if(!currentProject)return

  const fetchAgents=async()=>{
   try{
    const agentsData=await agentApi.listByProject(currentProject.id)
    setAgents(convertApiAgents(agentsData))
   }catch(error){
    console.error('Failed to fetch agents:',error)
   }
  }

  fetchAgents()
 },[currentProject?.id,setAgents])

 const getAgentByType=useCallback((type:AgentType):Agent|undefined=>{
  const projectAgents=agents.filter(a=>a.projectId===currentProject?.id)
  let agent=projectAgents.find(a=>a.type===type)
  if(!agent){
   agent=projectAgents.find(a=>a.type===`${type}_leader`)
  }
  if(!agent){
   agent=projectAgents.find(a=>a.type===type.replace('_leader',''))
  }
  return agent
 },[agents,currentProject?.id])

 const layout=useMemo(()=>{
  return getColumnLayout(agentNodes,uiPhases.length,layoutConfig)
 },[agentNodes,uiPhases.length,layoutConfig])

 const phaseGroups=useMemo(()=>{
  return uiPhases.map((phase,idx)=>({
   id:`phase-${idx}`,
   label:`P${idx+1}: ${phase.label}`,
   phaseIndex:idx,
   ...calculatePhaseBounds(idx,agentNodes,layout.positions,layout.widths,layout.heights,layoutConfig),
  }))
 },[uiPhases,agentNodes,layout,layoutConfig])

 const nodes:Node[]=useMemo(()=>{
  const groupNodes:Node[]=phaseGroups.map(group=>({
   id:group.id,
   type:'phaseGroup',
   position:{x:group.x,y:group.y},
   data:{label:group.label,width:group.width,height:group.height},
   draggable:false,
   selectable:false,
   zIndex:-1,
  }))

  const agentNodeList:Node[]=agentNodes.map(nodeDef=>{
   const agent=getAgentByType(nodeDef.type)
   const pos=layout.positions[nodeDef.id]
   return{
    id:nodeDef.id,
    type:'agent',
    position:pos||{x:0,y:0},
    data:{
     label:getLabel(nodeDef.type),
     status:agent?.status,
     progress:agent?.progress ?? 0,
     hasLW:nodeDef.hasLW,
     nodeWidth:layoutConfig.nodeWidth,
     nodeHeight:layoutConfig.nodeHeight,
     fontSize:layoutConfig.fontSize,
    },
    sourcePosition:Position.Right,
    targetPosition:Position.Left,
    draggable:false,
   }
  })

  return[...groupNodes,...agentNodeList]
 },[getAgentByType,layout,phaseGroups,layoutConfig,getLabel,agentNodes])

 const edges:Edge[]=useMemo(()=>{
  const getNodePhase=(nodeId:string):number=>{
   const node=agentNodes.find(n=>n.id===nodeId)
   return node?.uiPhaseIndex ?? 0
  }

  return edgeDefs.map((edgeDef,index)=>{
   const sourceAgent=getAgentByType(edgeDef.source as AgentType)
   const isCompleted=sourceAgent?.status==='completed'
   const isRunning=sourceAgent?.status==='running'

   const sourcePhase=getNodePhase(edgeDef.source)
   const targetPhase=getNodePhase(edgeDef.target)
   const isCrossPhase=sourcePhase!==targetPhase

   const edgeColor=isCompleted?COLORS.edge.completed:isRunning?COLORS.edge.running:COLORS.edge.default
   return{
    id:`e-${index}`,
    source:edgeDef.source,
    target:edgeDef.target,
    sourceHandle:isCrossPhase?'right' : 'bottom',
    targetHandle:isCrossPhase?'left' : 'top',
    type:'straight',
    animated:isRunning,
    style:{
     stroke:edgeColor,
     strokeWidth:isRunning?2 : 1,
    },
    markerEnd:{
     type:MarkerType.ArrowClosed,
     width:10,
     height:10,
     color:edgeColor,
    },
   }
  })
 },[getAgentByType,agentNodes,edgeDefs])

 const projectAgents=agents.filter(a=>a.projectId===currentProject?.id)
 const completedCount=projectAgents.filter(a=>a.status==='completed').length
 const runningCount=projectAgents.filter(a=>a.status==='running').length
 const waitingApprovalCount=projectAgents.filter(a=>a.status==='waiting_approval').length
 const totalCount=agentNodes.length
 const overallProgress=totalCount>0
  ?Math.round((completedCount/totalCount)*100+
        (projectAgents.filter(a=>a.status==='running').reduce((sum,a)=>sum+(a.progress||0),0)/totalCount))
  : 0

 if(!currentProject){
  return(
   <Card>
    <CardHeader>
     <DiamondMarker>ワークフロー全体図</DiamondMarker>
    </CardHeader>
    <CardContent>
     <div className="text-nier-text-light text-center py-4 text-nier-small">
      -
     </div>
    </CardContent>
   </Card>
)
 }

 return(
  <Card>
   <CardHeader>
    <DiamondMarker>ワークフロー全体図</DiamondMarker>
    <div className="ml-auto flex items-center gap-4 text-nier-caption text-nier-text-light">
     <span>全体: {overallProgress}%</span>
     <span>完了: {completedCount}/{totalCount}</span>
     {runningCount>0&&(
      <span className="text-nier-accent-orange animate-pulse">実行中: {runningCount}</span>
)}
     {waitingApprovalCount>0&&(
      <span className="text-[#8B7914] animate-pulse">承認待ち: {waitingApprovalCount}</span>
)}
    </div>
   </CardHeader>
   <CardContent className="p-0 relative">
    <ReactFlowProvider>
     <FlowCanvas nodes={nodes} edges={edges} onContainerResize={handleContainerResize}/>
    </ReactFlowProvider>

    {/*Legend-図の右下に縦並び*/}
    <div className="absolute bottom-3 right-3 flex flex-col gap-1 text-nier-caption nier-surface-main-muted p-2 rounded border border-nier-border-light">
     <div className="flex items-center gap-1">
      <div className="w-3 h-2.5 bg-[#A8A090] border border-[#454138] rounded-sm"/>
      <span>完了</span>
     </div>
     <div className="flex items-center gap-1">
      <div className="w-3 h-2.5 bg-nier-accent-orange border border-[#8B6914] rounded-sm"/>
      <span>実行中</span>
     </div>
     {waitingApprovalCount>0&&(
      <div className="flex items-center gap-1">
       <div className="w-3 h-2.5 bg-[#D4C896] border border-[#8B7914] rounded-sm"/>
       <span>承認待ち</span>
      </div>
)}
     <div className="flex items-center gap-1">
      <div className="w-3 h-2.5 bg-nier-bg-main border border-nier-border-light rounded-sm"/>
      <span>待機</span>
     </div>
     <div className="flex items-center gap-1 mt-1 pt-1 border-t border-nier-border-light">
      <span className="text-[9px] px-1 py-0.5 border border-nier-border-light rounded text-nier-text-light">L/W</span>
      <span>継続ループ</span>
     </div>
    </div>
   </CardContent>
  </Card>
)
}
