import{useRef,useEffect}from'react'
import*as d3 from'd3'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'

interface GraphNodeInput{
 id:string
 label:string
 type:'agent'|'checkpoint'|'output'
 status:'pending'|'running'|'completed'|'failed'
 phase:number
}

interface GraphLinkInput{
 source:string
 target:string
 type:'dependency'|'output'|'checkpoint'
}

interface DependencyGraphProps{
 nodes:GraphNodeInput[]
 links:GraphLinkInput[]
 selectedNodeId?:string
 onNodeClick?:(nodeId:string)=>void
 width?:number
 height?:number
}

const statusColors:Record<string,string>={
 pending:'#8A857A',
 running:'#C4956C',
 completed:'#7AAA7A',
 failed:'#B85C5C'
}

export default function DependencyGraph({
 nodes,
 links,
 selectedNodeId,
 onNodeClick,
 width=800,
 height=500
}:DependencyGraphProps):JSX.Element{
 const svgRef=useRef<SVGSVGElement>(null)

 useEffect(()=>{
  if(!svgRef.current||nodes.length===0)return

  const svg=d3.select(svgRef.current)
  svg.selectAll('*').remove()

  type SimNode=GraphNodeInput&d3.SimulationNodeDatum
  type SimLink=d3.SimulationLinkDatum<SimNode>&{type:string}

  const simNodes:SimNode[]=nodes.map((n)=>({...n}))
  const simLinks:SimLink[]=links.map((l)=>({
   source:l.source,
   target:l.target,
   type:l.type
  }))

  svg.append('defs').append('marker')
   .attr('id','arrowhead')
   .attr('viewBox','0 -5 10 10')
   .attr('refX',25)
   .attr('refY',0)
   .attr('markerWidth',6)
   .attr('markerHeight',6)
   .attr('orient','auto')
   .append('path')
   .attr('d','M0,-5L10,0L0,5')
   .attr('fill','#7A756A')

  const g=svg.append('g')

  const link=g.append('g')
   .selectAll('line')
   .data(simLinks)
   .join('line')
   .attr('stroke','#CCC7B5')
   .attr('stroke-width',1.5)
   .attr('marker-end','url(#arrowhead)')

  const node=g.append('g')
   .selectAll<SVGGElement,SimNode>('g')
   .data(simNodes)
   .join('g')
   .attr('cursor','pointer')
   .on('click',(event,d)=>{
    event.stopPropagation()
    onNodeClick?.(d.id)
   })

  node.each(function(d){
   const el=d3.select(this)
   const isSelected=d.id===selectedNodeId

   if(d.type==='agent'){
    el.append('circle')
     .attr('r',20)
     .attr('fill',statusColors[d.status])
     .attr('stroke',isSelected?'#6B8FAA' : '#454138')
     .attr('stroke-width',isSelected?3 : 1.5)
   }else if(d.type==='checkpoint'){
    el.append('rect')
     .attr('width',28)
     .attr('height',28)
     .attr('x',-14)
     .attr('y',-14)
     .attr('transform','rotate(45)')
     .attr('fill',statusColors[d.status])
     .attr('stroke',isSelected?'#6B8FAA' : '#454138')
     .attr('stroke-width',isSelected?3 : 1.5)
   }else{
    el.append('rect')
     .attr('width',40)
     .attr('height',25)
     .attr('x',-20)
     .attr('y',-12.5)
     .attr('fill',statusColors[d.status])
     .attr('stroke',isSelected?'#6B8FAA' : '#454138')
     .attr('stroke-width',isSelected?3 : 1.5)
   }

   el.append('text')
    .attr('dy',d.type==='agent'?35 : 30)
    .attr('text-anchor','middle')
    .attr('fill','#454138')
    .attr('font-size','11px')
    .attr('font-family','"Noto Sans JP", sans-serif')
    .text(d.label)
  })

  const drag=d3.drag<SVGGElement,SimNode>()
   .on('start',function(event,d){
    if(!event.active) simulation.alphaTarget(0.3).restart()
    d.fx=d.x
    d.fy=d.y
   })
   .on('drag',function(event,d){
    d.fx=event.x
    d.fy=event.y
   })
   .on('end',function(event,d){
    if(!event.active) simulation.alphaTarget(0)
    d.fx=null
    d.fy=null
   })

  node.call(drag)

  const simulation=d3.forceSimulation(simNodes)
   .force('link',d3.forceLink<SimNode,SimLink>(simLinks).id((d)=>d.id).distance(100))
   .force('charge',d3.forceManyBody().strength(-300))
   .force('center',d3.forceCenter(width/2,height/2))
   .force('collision',d3.forceCollide().radius(50))
   .on('tick',()=>{
    link
     .attr('x1',(d)=>(d.source as SimNode).x ?? 0)
     .attr('y1',(d)=>(d.source as SimNode).y ?? 0)
     .attr('x2',(d)=>(d.target as SimNode).x ?? 0)
     .attr('y2',(d)=>(d.target as SimNode).y ?? 0)

    node.attr('transform',(d)=>`translate(${d.x ?? 0},${d.y ?? 0})`)
   })

  const zoom=d3.zoom<SVGSVGElement,unknown>()
   .scaleExtent([0.5,2])
   .on('zoom',(event)=>{
    g.attr('transform',event.transform)
   })

  svg.call(zoom)

  return()=>{
   simulation.stop()
  }
 },[nodes,links,selectedNodeId,onNodeClick,width,height])

 return(
  <Card>
   <CardHeader className="flex flex-row items-center justify-between">
    <DiamondMarker>依存関係グラフ</DiamondMarker>
    <div className="flex items-center gap-4 text-nier-caption">
     <span className="flex items-center gap-2">
      <span className="w-3 h-3 rounded-full bg-nier-accent-green"/>
      完了
     </span>
     <span className="flex items-center gap-2">
      <span className="w-3 h-3 rounded-full bg-nier-accent-orange"/>
      実行中
     </span>
     <span className="flex items-center gap-2">
      <span className="w-3 h-3 rounded-full bg-nier-accent-yellow"/>
      待機中
     </span>
     <span className="flex items-center gap-2">
      <span className="w-3 h-3 rounded-full bg-nier-accent-red"/>
      エラー
     </span>
    </div>
   </CardHeader>
   <CardContent>
    {nodes.length===0?(
     <div className="flex items-center justify-center h-[400px] text-nier-text-light">
      グラフデータがありません
     </div>
) : (
     <svg
      ref={svgRef}
      width={width}
      height={height}
      className="max-w-full h-auto bg-nier-bg-main"
     />
)}
   </CardContent>
  </Card>
)
}
