import{useEffect,useRef}from'react'
import type{AgentStatus}from'@/types/agent'

interface MenuItem{
 label:string
 onClick:()=>void
}

interface WorkflowContextMenuProps{
 x:number
 y:number
 agentId:string
 status:AgentStatus
 onClose:()=>void
 onPause:(agentId:string)=>void
 onResume:(agentId:string)=>void
 onFreeze:(agentId:string)=>void
 onUnfreeze:(agentId:string)=>void
 onContact:(agentId:string)=>void
}

export function WorkflowContextMenu({
 x,y,agentId,status,onClose,onPause,onResume,onFreeze,onUnfreeze,onContact
}:WorkflowContextMenuProps):JSX.Element{
 const menuRef=useRef<HTMLDivElement>(null)

 useEffect(()=>{
  const handleClickOutside=(e:MouseEvent)=>{
   if(menuRef.current&&!menuRef.current.contains(e.target as Node)){
    onClose()
   }
  }
  const handleEscape=(e:KeyboardEvent)=>{
   if(e.key==='Escape')onClose()
  }
  document.addEventListener('mousedown',handleClickOutside)
  document.addEventListener('keydown',handleEscape)
  return()=>{
   document.removeEventListener('mousedown',handleClickOutside)
   document.removeEventListener('keydown',handleEscape)
  }
 },[onClose])

 const items:MenuItem[]=[]

 if(status==='running'||status==='waiting_approval'){
  items.push({label:'一時停止',onClick:()=>{onPause(agentId);onClose()}})
  items.push({label:'連絡',onClick:()=>{onContact(agentId);onClose()}})
 }else if(status==='paused'){
  items.push({label:'再開',onClick:()=>{onResume(agentId);onClose()}})
  items.push({label:'連絡',onClick:()=>{onContact(agentId);onClose()}})
 }else if(status==='pending'){
  items.push({label:'凍結',onClick:()=>{onFreeze(agentId);onClose()}})
  items.push({label:'連絡',onClick:()=>{onContact(agentId);onClose()}})
 }else if(status==='frozen'){
  items.push({label:'凍結解除',onClick:()=>{onUnfreeze(agentId);onClose()}})
  items.push({label:'連絡',onClick:()=>{onContact(agentId);onClose()}})
 }else{
  items.push({label:'連絡',onClick:()=>{onContact(agentId);onClose()}})
 }

 if(items.length===0)return<></>

 const menuStyle:{left?:number;right?:number;top?:number;bottom?:number}={}
 const menuWidth=140
 const menuHeight=items.length*32+8
 if(x+menuWidth>window.innerWidth){
  menuStyle.right=window.innerWidth-x
 }else{
  menuStyle.left=x
 }
 if(y+menuHeight>window.innerHeight){
  menuStyle.bottom=window.innerHeight-y
 }else{
  menuStyle.top=y
 }

 return(
  <div
   ref={menuRef}
   className="fixed z-50 nier-surface-panel border border-nier-border shadow-lg py-1"
   style={{...menuStyle,minWidth:menuWidth}}
  >
   {items.map((item,idx)=>(
    <button
     key={idx}
     onClick={item.onClick}
     className="w-full px-3 py-1.5 text-left text-nier-small text-nier-text-main hover:bg-nier-bg-selected transition-colors"
    >
     {item.label}
    </button>
))}
  </div>
)
}
