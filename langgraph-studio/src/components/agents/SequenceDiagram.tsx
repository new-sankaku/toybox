import{useState,useMemo}from'react'
import{cn}from'@/lib/utils'
import{ChevronDown,ChevronRight}from'lucide-react'
import type{SequenceData,SequenceMessage}from'@/types/agent'

interface SequenceDiagramProps{
 data:SequenceData
 onMessageClick?:(msg:SequenceMessage)=>void
}

const TIMELINE_MSG_STYLE:Record<string,{text:string;marker:string;dashed?:boolean}>={
 input:{text:'text-nier-text-main',marker:'bg-nier-text-main'},
 output:{text:'text-nier-text-main',marker:'bg-nier-text-main'},
 request:{text:'text-nier-text-main',marker:'bg-nier-text-main'},
 response:{text:'text-nier-text-light',marker:'bg-nier-text-light',dashed:true},
 error:{text:'text-nier-accent-red',marker:'bg-nier-accent-red'},
 delegation:{text:'text-nier-accent-orange',marker:'bg-nier-accent-orange'},
 result:{text:'text-nier-text-light',marker:'bg-nier-text-light',dashed:true},
}

function formatDuration(ms:number|null):string{
 if(!ms)return''
 if(ms<1000)return`${ms}ms`
 return`${(ms/1000).toFixed(1)}s`
}

function formatTimestamp(timestamp:string|null):string{
 if(!timestamp)return''
 const d=new Date(timestamp)
 const mo=String(d.getMonth()+1).padStart(2,'0')
 const dd=String(d.getDate()).padStart(2,'0')
 const hh=String(d.getHours()).padStart(2,'0')
 const mm=String(d.getMinutes()).padStart(2,'0')
 const ss=String(d.getSeconds()).padStart(2,'0')
 return`${mo}/${dd} ${hh}:${mm}:${ss}`
}

interface TimelineNode{
 message:SequenceMessage
 depth:number
 children:TimelineNode[]
 isGroupParent:boolean
 pairedResponse?:SequenceMessage
}

function buildTimelineStructure(messages:SequenceMessage[]):TimelineNode[]{
 const result:TimelineNode[]=[]
 const pairStack:{pairId:string;node:TimelineNode}[]=[]
 const responseMap=new Map<string,SequenceMessage>()
 for(const msg of messages){
  if(msg.type==='response'&&msg.pairId){
   responseMap.set(msg.pairId,msg)
  }
 }
 for(const msg of messages){
  if(msg.type==='response')continue
  const depth=pairStack.length
  const node:TimelineNode={message:msg,depth,children:[],isGroupParent:false}
  if(msg.type==='request'&&msg.pairId){
   node.pairedResponse=responseMap.get(msg.pairId)
  }
  if(msg.type==='delegation'&&msg.pairId){
   node.isGroupParent=true
   if(pairStack.length>0){
    pairStack[pairStack.length-1].node.children.push(node)
   }else{
    result.push(node)
   }
   pairStack.push({pairId:msg.pairId,node})
  }else if(msg.type==='result'&&msg.pairId){
   const stackIdx=pairStack.findIndex(s=>s.pairId===msg.pairId)
   if(stackIdx>=0){
    pairStack[stackIdx].node.children.push(node)
    pairStack.splice(stackIdx,1)
   }else{
    if(pairStack.length>0){
     pairStack[pairStack.length-1].node.children.push(node)
    }else{
     result.push(node)
    }
   }
  }else{
   if(pairStack.length>0){
    pairStack[pairStack.length-1].node.children.push(node)
   }else{
    result.push(node)
   }
  }
 }
 return result
}

function TimelineRow({
 node,
 onMessageClick,
 isLast,
 labelMap
}:{
 node:TimelineNode
 onMessageClick?:(msg:SequenceMessage)=>void
 isLast:boolean
 labelMap:Map<string,string>
}){
 const{message:msg,depth,pairedResponse}=node
 const style=TIMELINE_MSG_STYLE[msg.type]||TIMELINE_MSG_STYLE.request
 const timeStr=formatTimestamp(msg.timestamp)
 const durationStr=formatDuration(msg.durationMs||(pairedResponse?.durationMs??null))
 const indentPx=depth*16
 const clickable=!!msg.sourceId&&!!onMessageClick
 const fromLabel=labelMap.get(msg.from)||msg.from
 const toLabel=labelMap.get(msg.to)||msg.to
 return(
  <div
   className={cn(
    'grid gap-2 py-1.5 px-2',
    'grid-cols-[100px_1fr]',
    clickable&&'cursor-pointer hover:bg-nier-bg-main/40 transition-colors',
    !isLast&&'border-b border-nier-border-light'
)}
   style={{paddingLeft:`${8+indentPx}px`}}
   onClick={clickable?()=>onMessageClick?.(pairedResponse||msg):undefined}
  >
   <div className="flex flex-col items-start">
    <span className="text-[11px] text-nier-text-light font-mono">{timeStr}</span>
    {durationStr&&(
     <span className="text-[9px] text-nier-text-light font-mono opacity-70 whitespace-nowrap">
      {durationStr}
     </span>
)}
   </div>
   <div className="flex flex-col gap-0.5">
    <div className="flex items-center gap-2">
     <div className={cn('w-1 h-4 rounded-sm flex-shrink-0',style.marker,style.dashed&&'opacity-50')}/>
     <span className={cn('text-[11px] font-medium',style.text)}>
      {fromLabel}
      <span className="text-nier-text-light mx-1">→</span>
      {toLabel}
     </span>
    </div>
    {msg.label&&<div className="ml-3 text-[11px] text-nier-text-main">{msg.label}</div>}
    {pairedResponse?.label&&(
     <div className="ml-3 text-[10px] text-nier-text-light opacity-80">
      ← {pairedResponse.label.length>80?pairedResponse.label.slice(0,80)+'...':pairedResponse.label}
     </div>
)}
   </div>
  </div>
)
}

function TimelineGroup({
 node,
 onMessageClick,
 isLast,
 labelMap
}:{
 node:TimelineNode
 onMessageClick?:(msg:SequenceMessage)=>void
 isLast:boolean
 labelMap:Map<string,string>
}){
 const[expanded,setExpanded]=useState(true)
 const{message:msg,depth,children}=node
 const style=TIMELINE_MSG_STYLE[msg.type]||TIMELINE_MSG_STYLE.delegation
 const timeStr=formatTimestamp(msg.timestamp)
 const durationStr=formatDuration(msg.durationMs)
 const indentPx=depth*16
 const hasClickHandler=!!msg.sourceId&&!!onMessageClick
 const fromLabel=labelMap.get(msg.from)||msg.from
 const toLabel=labelMap.get(msg.to)||msg.to
 return(
  <div className={cn(!isLast&&'border-b border-nier-border-light')}>
   <div
    className={cn(
     'grid gap-2 py-1.5 px-2',
     'grid-cols-[100px_1fr]',
     'hover:bg-nier-bg-main/40 transition-colors cursor-pointer'
)}
    style={{paddingLeft:`${8+indentPx}px`}}
    onClick={()=>setExpanded(!expanded)}
   >
    <div className="flex flex-col items-start">
     <span className="text-[11px] text-nier-text-light font-mono">{timeStr}</span>
     {durationStr&&(
      <span className="text-[9px] text-nier-text-light font-mono opacity-70 whitespace-nowrap">
       {durationStr}
      </span>
)}
    </div>
    <div className="flex flex-col gap-0.5">
     <div className="flex items-center gap-2">
      {expanded?
       <ChevronDown className="w-3 h-3 text-nier-text-light flex-shrink-0"/>:
       <ChevronRight className="w-3 h-3 text-nier-text-light flex-shrink-0"/>
      }
      <div className={cn('w-1 h-4 rounded-sm flex-shrink-0',style.marker)}/>
      <span className={cn('text-[11px] font-medium',style.text)}>
       {fromLabel}
       <span className="text-nier-text-light mx-1">→</span>
       {toLabel}
      </span>
      {hasClickHandler&&(
       <button
        className="text-[10px] text-nier-text-light hover:text-nier-text-main underline ml-auto"
        onClick={(e)=>{e.stopPropagation();onMessageClick?.(msg)}}
       >詳細</button>
)}
     </div>
     {msg.label&&<div className="ml-5 text-[11px] text-nier-text-main">{msg.label}</div>}
    </div>
   </div>
   {expanded&&children.length>0&&(
    <div className="border-l-2 border-nier-accent-orange ml-4" style={{marginLeft:`${16+indentPx}px`}}>
     {children.map((child,idx)=>(
      <TimelineNodeRenderer
       key={child.message.id}
       node={child}
       onMessageClick={onMessageClick}
       isLast={idx===children.length-1}
       labelMap={labelMap}
      />
))}
    </div>
)}
  </div>
)
}

function TimelineNodeRenderer({
 node,
 onMessageClick,
 isLast,
 labelMap
}:{
 node:TimelineNode
 onMessageClick?:(msg:SequenceMessage)=>void
 isLast:boolean
 labelMap:Map<string,string>
}){
 if(node.isGroupParent){
  return<TimelineGroup node={node} onMessageClick={onMessageClick} isLast={isLast} labelMap={labelMap}/>
 }
 return(
  <TimelineRow
   node={node}
   onMessageClick={onMessageClick}
   isLast={isLast}
   labelMap={labelMap}
  />
)
}

export function SequenceDiagram({data,onMessageClick}:SequenceDiagramProps):JSX.Element{
 const{messages,participants}=data
 const labelMap=useMemo(()=>{
  const m=new Map<string,string>()
  for(const p of participants){
   m.set(p.id,p.label)
  }
  return m
 },[participants])
 const timeline=useMemo(()=>buildTimelineStructure(messages),[messages])
 if(!messages.length){
  return(
   <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
    シーケンスデータがありません
   </div>
)
 }
 const totalIn=data.totalTokens?.input??0
 const totalOut=data.totalTokens?.output??0
 const totalDur=formatDuration(data.totalDurationMs??null)
 return(
  <div className="w-full bg-nier-bg-panel border border-nier-border-light font-mono">
   {(totalIn>0||totalOut>0||totalDur)&&(
    <div className="border-b border-nier-border-light px-3 py-1.5 text-[10px] text-nier-text-light bg-nier-bg-selected">
     {`Total: in ${totalIn.toLocaleString()} / out ${totalOut.toLocaleString()} tokens`}
     {totalDur?` / ${totalDur}`:''}
    </div>
)}
   <div className="max-h-sequence-panel overflow-y-auto">
    {timeline.map((node,idx)=>(
     <TimelineNodeRenderer
      key={node.message.id}
      node={node}
      onMessageClick={onMessageClick}
      isLast={idx===timeline.length-1}
      labelMap={labelMap}
     />
))}
   </div>
  </div>
)
}
