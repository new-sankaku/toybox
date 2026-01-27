import{ReactNode,useRef,useState,useCallback,useEffect}from'react'
import{createPortal}from'react-dom'
import{X,GripHorizontal}from'lucide-react'
import{cn}from'@/lib/utils'
import{Button}from'./Button'

export interface FloatingPanelProps{
 isOpen:boolean
 onClose:()=>void
 title?:string
 children:ReactNode
 footer?:ReactNode
 size?:'sm'|'md'|'lg'|'xl'
 panelId:string
}

const sizeClasses={
 sm:'w-[320px]',
 md:'w-[400px]',
 lg:'w-[600px]',
 xl:'w-[800px]'
}

const panelPositions:Record<string,{x:number,y:number}>={}

export function FloatingPanel({
 isOpen,
 onClose,
 title,
 children,
 footer,
 size='md',
 panelId
}:FloatingPanelProps){
 const panelRef=useRef<HTMLDivElement>(null)
 const[isDragging,setIsDragging]=useState(false)
 const[position,setPosition]=useState<{x:number,y:number}>(()=>{
  if(panelPositions[panelId])return panelPositions[panelId]
  return{x:-1,y:-1}
 })
 const dragStart=useRef({x:0,y:0})
 const posStart=useRef({x:0,y:0})

 useEffect(()=>{
  if(isOpen&&position.x===-1&&position.y===-1){
   const centerX=Math.max(0,(window.innerWidth-400)/2)
   const centerY=Math.max(0,(window.innerHeight-300)/2)
   const newPos={x:centerX,y:centerY}
   setPosition(newPos)
   panelPositions[panelId]=newPos
  }
 },[isOpen,panelId,position])

 const handleMouseDown=useCallback((e:React.MouseEvent)=>{
  if((e.target as HTMLElement).closest('button'))return
  setIsDragging(true)
  dragStart.current={x:e.clientX,y:e.clientY}
  posStart.current={...position}
 },[position])

 const handleMouseMove=useCallback((e:MouseEvent)=>{
  if(!isDragging)return
  const dx=e.clientX-dragStart.current.x
  const dy=e.clientY-dragStart.current.y
  const newX=Math.max(0,Math.min(window.innerWidth-100,posStart.current.x+dx))
  const newY=Math.max(0,Math.min(window.innerHeight-50,posStart.current.y+dy))
  const newPos={x:newX,y:newY}
  setPosition(newPos)
  panelPositions[panelId]=newPos
 },[isDragging,panelId])

 const handleMouseUp=useCallback(()=>{
  setIsDragging(false)
 },[])

 useEffect(()=>{
  if(isDragging){
   document.addEventListener('mousemove',handleMouseMove)
   document.addEventListener('mouseup',handleMouseUp)
  }
  return()=>{
   document.removeEventListener('mousemove',handleMouseMove)
   document.removeEventListener('mouseup',handleMouseUp)
  }
 },[isDragging,handleMouseMove,handleMouseUp])

 if(!isOpen)return null

 return createPortal(
  <div
   ref={panelRef}
   className={cn(
    'fixed bg-nier-bg-panel border border-nier-border-dark shadow-lg z-[150] max-h-[80vh]',
    sizeClasses[size],
    isDragging&&'cursor-grabbing select-none'
)}
   style={{left:`${position.x}px`,top:`${position.y}px`}}
  >
   {title&&(
    <div
     className={cn(
      'flex items-center justify-between bg-nier-bg-header text-nier-text-header px-4 py-2',
      'cursor-grab active:cursor-grabbing'
)}
     onMouseDown={handleMouseDown}
    >
     <div className="flex items-center gap-2">
      <GripHorizontal size={14} className="opacity-50"/>
      <h2 className="text-nier-body tracking-nier-wide">{title}</h2>
     </div>
     <Button
      variant="ghost"
      size="icon"
      onClick={onClose}
      className="text-nier-text-header hover:bg-white/10 h-6 w-6"
     >
      <X size={14}/>
     </Button>
    </div>
)}
   <div className="p-4 max-h-[60vh] overflow-y-auto">
    {children}
   </div>
   {footer&&(
    <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-nier-border-light bg-nier-bg-selected/50">
     {footer}
    </div>
)}
  </div>,
  document.body
)
}
