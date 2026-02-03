import{useMemo}from'react'
import{cn}from'@/lib/utils'
import type{SequenceData,SequenceMessage}from'@/types/agent'

interface SequenceDiagramProps{
 data:SequenceData
 onMessageClick?:(msg:SequenceMessage)=>void
}

function formatTokens(n:number):string{
 if(n>=1_000_000)return`${(n/1_000_000).toFixed(2)}m`
 if(n>=1_000)return`${(n/1_000).toFixed(1)}k`
 return String(n)
}

function formatDuration(ms:number|null):string{
 if(!ms)return''
 if(ms<1000)return`${ms}msec`
 return`${(ms/1000).toFixed(1)}sec`
}

function formatCost(cost:number|null):string{
 if(cost===null||cost===undefined)return''
 if(cost<0.01)return`${cost.toFixed(4)}`
 return`${cost.toFixed(2)}`
}

function formatTimeOnly(timestamp:string|null):string{
 if(!timestamp)return''
 const d=new Date(timestamp)
 const hh=String(d.getHours()).padStart(2,'0')
 const mm=String(d.getMinutes()).padStart(2,'0')
 const ss=String(d.getSeconds()).padStart(2,'0')
 return`${hh}:${mm}:${ss}`
}

function getDateKey(timestamp:string|null):string{
 if(!timestamp)return''
 const d=new Date(timestamp)
 const mo=String(d.getMonth()+1).padStart(2,'0')
 const dd=String(d.getDate()).padStart(2,'0')
 return`${mo}/${dd}`
}

interface CallEntry{
 request:SequenceMessage
 response:SequenceMessage|null
 agentRole:string
 agentLabel:string
 dateKey:string
}

function buildCallEntries(
 messages:SequenceMessage[],
 labelMap:Map<string,string>,
 roleMap:Map<string,string>
):CallEntry[]{
 const responseMap=new Map<string,SequenceMessage>()
 for(const msg of messages){
  if((msg.type==='response'||msg.type==='error')&&msg.pairId){
   responseMap.set(msg.pairId,msg)
  }
 }
 const entries:CallEntry[]=[]
 for(const msg of messages){
  if(msg.type!=='request')continue
  const response=msg.pairId?responseMap.get(msg.pairId)??null:null
  const agentId=msg.from
  const agentLabel=labelMap.get(agentId)||agentId
  const agentRole=roleMap.get(agentId)||''
  const dateKey=getDateKey(msg.timestamp)
  entries.push({request:msg,response,agentRole,agentLabel,dateKey})
 }
 return entries
}

interface DateGroup{
 dateKey:string
 workerCount:number
 entries:CallEntry[]
}

function groupByDate(entries:CallEntry[],workerIds:Set<string>):DateGroup[]{
 const grouped=new Map<string,CallEntry[]>()
 for(const e of entries){
  const arr=grouped.get(e.dateKey)||[]
  arr.push(e)
  grouped.set(e.dateKey,arr)
 }
 const result:DateGroup[]=[]
 for(const[dateKey,ents] of grouped){
  const workersInGroup=new Set<string>()
  for(const e of ents){
   if(workerIds.has(e.request.from)){
    workersInGroup.add(e.request.from)
   }
  }
  result.push({dateKey,workerCount:workersInGroup.size,entries:ents})
 }
 return result
}

function CallEntryRow({
 entry,
 callIndex,
 onClick
}:{
 entry:CallEntry
 callIndex:number
 onClick?:(msg:SequenceMessage)=>void
}){
 const{request,response,agentRole}=entry
 const timeStr=formatTimeOnly(request.timestamp)
 const model=response?.model||request.model||'Unknown'
 const durationStr=formatDuration(response?.durationMs||null)
 const tokensIn=request.tokens?.input||0
 const tokensOut=response?.tokens?.output||0
 const cost=response?.cost||null
 const label=response?.label||request.label||''
 const isError=response?.type==='error'
 const clickable=!!(response?.sourceId||request.sourceId)&&!!onClick
 const handleClick=()=>{
  if(clickable&&onClick){
   onClick(response||request)
  }
 }
 return(
  <div
   className={cn(
    'py-1.5 border-b border-nier-border-light',
    clickable&&'cursor-pointer hover:bg-nier-bg-main/40 transition-colors'
)}
   onClick={clickable?handleClick:undefined}
  >
   {label&&(
    <div className={cn('text-[11px] font-mono truncate',isError?'text-nier-accent-red':'text-nier-text-main')}>
     {label}
    </div>
)}
   <div className="flex items-center gap-1.5 text-[10px] font-mono text-nier-text-light">
    <span>{timeStr}</span>
    <span>|</span>
    <span>{model}</span>
    <span>|</span>
    <span className={cn(isError&&'text-nier-accent-red')}>{agentRole}</span>
    <span>|</span>
    {durationStr&&<><span>{durationStr}</span><span>|</span></>}
    <span>Call {callIndex}回</span>
    <span>|</span>
    <span>In {formatTokens(tokensIn)}/Out {formatTokens(tokensOut)}</span>
    {cost!==null&&<><span>/</span><span>{formatCost(cost)}</span></>}
   </div>
  </div>
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
 const roleMap=useMemo(()=>{
  const m=new Map<string,string>()
  for(const p of participants){
   m.set(p.id,p.role)
  }
  return m
 },[participants])
 const workerIds=useMemo(()=>{
  const s=new Set<string>()
  for(const p of participants){
   if(p.type==='worker')s.add(p.id)
  }
  return s
 },[participants])
 const entries=useMemo(()=>buildCallEntries(messages,labelMap,roleMap),[messages,labelMap,roleMap])
 const dateGroups=useMemo(()=>groupByDate(entries,workerIds),[entries,workerIds])
 if(!messages.length){
  return(
   <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
    シーケンスデータがありません
   </div>
)
 }
 const totalIn=data.totalTokens?.input??0
 const totalOut=data.totalTokens?.output??0
 const totalDur=data.totalDurationMs?formatDuration(data.totalDurationMs):''
 let runningCallIndex=0
 return(
  <div className="w-full bg-nier-bg-panel border border-nier-border-light font-mono">
   {(totalIn>0||totalOut>0||totalDur)&&(
    <div className="border-b border-nier-border-light px-3 py-1.5 text-[10px] nier-surface-selected-muted">
     Total: Token In {formatTokens(totalIn)}/Out {formatTokens(totalOut)}
     {totalDur?` / ${totalDur}`:''}
    </div>
)}
   <div className="max-h-sequence-panel overflow-y-auto">
    {dateGroups.map((group)=>(
     <div key={group.dateKey}>
      <div className="px-3 py-1 text-[11px] nier-surface-selected border-b border-nier-border-light">
       {group.dateKey} {group.workerCount>0&&`Worker ${group.workerCount}体`}
      </div>
      <div className="px-3">
       {group.entries.map((entry)=>{
        runningCallIndex++
        return(
         <CallEntryRow
          key={entry.request.id}
          entry={entry}
          callIndex={runningCallIndex}
          onClick={onMessageClick}
         />
)
       })}
      </div>
     </div>
))}
   </div>
  </div>
)
}
