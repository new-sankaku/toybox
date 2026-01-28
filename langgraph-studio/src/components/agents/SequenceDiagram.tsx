import{useMemo}from'react'
import{cn}from'@/lib/utils'
import type{SequenceData,SequenceMessage,SequenceParticipant}from'@/types/agent'

interface SequenceDiagramProps{
 data:SequenceData
 onMessageClick?:(msg:SequenceMessage)=>void
}

const PARTICIPANT_BORDER:Record<string,string>={
 external:'border-nier-text-light',
 leader:'border-nier-text-main',
 agent:'border-nier-text-main',
 api:'border-nier-text-light',
 worker:'border-nier-text-light',
}

const MSG_STYLE:Record<string,{text:string;border:string;dashed?:boolean}>={
 input:{text:'text-nier-text-main',border:'border-nier-text-main'},
 output:{text:'text-nier-text-main',border:'border-nier-text-main'},
 request:{text:'text-nier-text-main',border:'border-nier-text-main'},
 response:{text:'text-nier-text-light',border:'border-nier-text-light',dashed:true},
 error:{text:'text-nier-accent-red',border:'border-nier-accent-red'},
 delegation:{text:'text-nier-accent-orange',border:'border-nier-accent-orange'},
 result:{text:'text-nier-text-light',border:'border-nier-text-light',dashed:true},
}

function formatTokens(tokens:SequenceMessage['tokens']):string{
 if(!tokens)return''
 const parts:string[]=[]
 if(tokens.input)parts.push(`in:${tokens.input.toLocaleString()}`)
 if(tokens.output)parts.push(`out:${tokens.output.toLocaleString()}`)
 return parts.join(' ')
}

function formatDuration(ms:number|null):string{
 if(!ms)return''
 if(ms<1000)return`${ms}ms`
 return`${(ms/1000).toFixed(1)}s`
}

interface MessageGroup{
 pairId:string|null
 messages:SequenceMessage[]
}

function groupMessages(messages:SequenceMessage[]):MessageGroup[]{
 const groups:MessageGroup[]=[]
 let i=0
 while(i<messages.length){
  const msg=messages[i]
  if(msg.pairId){
   const group:SequenceMessage[]=[msg]
   let j=i+1
   while(j<messages.length&&messages[j].pairId===msg.pairId){
    group.push(messages[j])
    j++
   }
   groups.push({pairId:msg.pairId,messages:group})
   i=j
  }else{
   groups.push({pairId:null,messages:[msg]})
   i++
  }
 }
 return groups
}

function colCenter(idx:number,total:number):number{
 return((idx+0.5)/total)*100
}

function ArrowRow({
 msg,
 participantCount,
 pMap,
 clickable,
 onClick
}:{
 msg:SequenceMessage
 participantCount:number
 pMap:Record<string,number>
 clickable:boolean
 onClick?:()=>void
}){
 const fromIdx=pMap[msg.from]
 const toIdx=pMap[msg.to]
 if(fromIdx===undefined||toIdx===undefined)return null
 const isLeft=fromIdx>toIdx
 const minIdx=Math.min(fromIdx,toIdx)
 const maxIdx=Math.max(fromIdx,toIdx)
 const style=MSG_STYLE[msg.type]||MSG_STYLE.request
 const tokenStr=formatTokens(msg.tokens)
 const durationStr=formatDuration(msg.durationMs)
 const subLabel=[tokenStr,durationStr].filter(Boolean).join(' / ')
 const fromPct=colCenter(fromIdx,participantCount)
 const toPct=colCenter(toIdx,participantCount)
 const leftPct=Math.min(fromPct,toPct)
 const widthPct=Math.abs(fromPct-toPct)
 const isSelf=fromIdx===toIdx
 return(
  <div
   className={cn(
    'relative',
    clickable&&'cursor-pointer hover:bg-nier-bg-main/40 transition-colors'
)}
   style={{minHeight:'32px'}}
   onClick={clickable?onClick:undefined}
  >
   {isSelf?(
    <div className="flex flex-col items-center justify-center h-full py-1" style={{paddingLeft:`${fromPct-10}%`,paddingRight:`${100-fromPct-10}%`}}>
     <span className={cn('text-[10px] leading-tight whitespace-nowrap',style.text)}>{msg.label}</span>
     {subLabel&&<span className="text-[9px] text-nier-text-light opacity-80 whitespace-nowrap">{subLabel}</span>}
    </div>
):(
    <>
     <div
      className="absolute flex flex-col items-center justify-center"
      style={{left:`${leftPct}%`,width:`${widthPct}%`,top:'2px'}}
     >
      <span className={cn('text-[10px] leading-tight whitespace-nowrap',style.text)}>{msg.label}</span>
      {subLabel&&<span className="text-[9px] text-nier-text-light opacity-80 whitespace-nowrap">{subLabel}</span>}
     </div>
     <div
      className="absolute flex items-center"
      style={{left:`${leftPct}%`,width:`${widthPct}%`,bottom:'4px',height:'1px'}}
     >
      {isLeft&&<span className={cn('text-xs leading-none -ml-1',style.text)}>{'◁'}</span>}
      <div className={cn('flex-1 border-t',style.border,style.dashed&&'border-dashed')}/>
      {!isLeft&&<span className={cn('text-xs leading-none -mr-1',style.text)}>{'▷'}</span>}
     </div>
    </>
)}
  </div>
)
}

function Lifelines({count}:{count:number}){
 return(
  <div className="absolute inset-0 pointer-events-none" aria-hidden="true">
   {Array.from({length:count},(_,i)=>(
    <div
     key={i}
     className="absolute top-0 bottom-0 w-px border-l border-dashed border-nier-border-light"
     style={{left:`${colCenter(i,count)}%`}}
    />
))}
  </div>
)
}

export function SequenceDiagram({data,onMessageClick}:SequenceDiagramProps):JSX.Element{
 const{participants,messages}=data

 const pMap=useMemo(()=>{
  const m:Record<string,number>={}
  participants.forEach((p,i)=>{m[p.id]=i})
  return m
 },[participants])

 const groups=useMemo(()=>groupMessages(messages),[messages])

 if(!messages.length){
  return(
   <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
    シーケンスデータがありません
   </div>
)
 }

 return(
  <div className="w-full overflow-x-auto bg-nier-bg-panel border border-nier-border-light font-mono text-[11px]">
   <div style={{minWidth:`${participants.length*120}px`}}>
    <div
     className="grid border-b border-nier-border-light bg-nier-bg-selected"
     style={{gridTemplateColumns:`repeat(${participants.length},1fr)`}}
    >
     {participants.map(p=>(
      <div
       key={p.id}
       className={cn(
        'flex items-center justify-center py-2 px-1',
        'border-b-2',
        PARTICIPANT_BORDER[p.type]||'border-nier-text-main'
)}
      >
       <span className={cn(
        'text-[11px] truncate max-w-full',
        p.type==='api'?'font-bold text-nier-text-main':'text-nier-text-main'
)}>
        {p.label}
       </span>
      </div>
))}
    </div>

    <div className="relative py-1">
     <Lifelines count={participants.length}/>
     {groups.map((group,gIdx)=>{
      const isPair=group.pairId!==null&&group.messages.length>1
      return(
       <div
        key={group.pairId||`single-${gIdx}`}
        className={cn(
         isPair&&'border-l-2 border-nier-accent-orange ml-1 bg-nier-bg-main/20 my-0.5'
)}
       >
        {group.messages.map(msg=>(
         <ArrowRow
          key={msg.id}
          msg={msg}
          participantCount={participants.length}
          pMap={pMap}
          clickable={!!msg.sourceId&&!!onMessageClick}
          onClick={()=>onMessageClick?.(msg)}
         />
))}
       </div>
)
     })}
    </div>

    {data.totalTokens&&(
     <div className="border-t border-nier-border-light px-3 py-1.5 text-[10px] text-nier-text-light">
      {`Total: in ${data.totalTokens.input.toLocaleString()} / out ${data.totalTokens.output.toLocaleString()} tokens`}
      {data.totalDurationMs?` / ${formatDuration(data.totalDurationMs)}`:''}
     </div>
)}
   </div>
  </div>
)
}
