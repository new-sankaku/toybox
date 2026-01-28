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
 resizable?:boolean
}

const sizeDefaults={
 sm:{w:320,h:300},
 md:{w:400,h:400},
 lg:{w:600,h:500},
 xl:{w:800,h:600}
}

const panelPositions:Record<string,{x:number,y:number}>={}
const panelSizes:Record<string,{w:number,h:number}>={}

export function FloatingPanel({
 isOpen,
 onClose,
 title,
 children,
 footer,
 size='md',
 panelId,
 resizable=false
}:FloatingPanelProps){
 const panelRef=useRef<HTMLDivElement>(null)
 const[isDragging,setIsDragging]=useState(false)
 const[isResizing,setIsResizing]=useState(false)
 const[position,setPosition]=useState<{x:number,y:number}>(()=>{
  if(panelPositions[panelId])return panelPositions[panelId]
  return{x:-1,y:-1}
 })
 const[panelSize,setPanelSize]=useState<{w:number,h:number}>(()=>{
  if(panelSizes[panelId])return panelSizes[panelId]
  return sizeDefaults[size]
 })
 const dragStart=useRef({x:0,y:0})
 const posStart=useRef({x:0,y:0})
 const sizeStart=useRef({w:0,h:0})

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
  if(isDragging){
   const dx=e.clientX-dragStart.current.x
   const dy=e.clientY-dragStart.current.y
   const newX=Math.max(0,Math.min(window.innerWidth-100,posStart.current.x+dx))
   const newY=Math.max(0,Math.min(window.innerHeight-50,posStart.current.y+dy))
   const newPos={x:newX,y:newY}
   setPosition(newPos)
   panelPositions[panelId]=newPos
  }else if(isResizing){
   const dx=e.clientX-dragStart.current.x
   const dy=e.clientY-dragStart.current.y
   const newW=Math.max(280,Math.min(window.innerWidth-position.x-20,sizeStart.current.w+dx))
   const newH=Math.max(200,Math.min(window.innerHeight-position.y-20,sizeStart.current.h+dy))
   const newSize={w:newW,h:newH}
   setPanelSize(newSize)
   panelSizes[panelId]=newSize
  }
 },[isDragging,isResizing,panelId,position.x,position.y])

 const handleMouseUp=useCallback(()=>{
  setIsDragging(false)
  setIsResizing(false)
 },[])

 const handleResizeStart=useCallback((e:React.MouseEvent)=>{
  e.stopPropagation()
  setIsResizing(true)
  dragStart.current={x:e.clientX,y:e.clientY}
  sizeStart.current={...panelSize}
 },[panelSize])

 useEffect(()=>{
  if(isDragging||isResizing){
   document.addEventListener('mousemove',handleMouseMove)
   document.addEventListener('mouseup',handleMouseUp)
  }
  return()=>{
   document.removeEventListener('mousemove',handleMouseMove)
   document.removeEventListener('mouseup',handleMouseUp)
  }
 },[isDragging,isResizing,handleMouseMove,handleMouseUp])

 if(!isOpen)return null

 const contentMaxH=resizable?panelSize.h-80:undefined

 return createPortal(
  <div
   ref={panelRef}
   className={cn(
    'fixed bg-nier-bg-panel border border-nier-border-dark shadow-lg z-[150] flex flex-col',
    (isDragging||isResizing)&&'select-none',
    isDragging&&'cursor-grabbing',
    isResizing&&'cursor-se-resize'
)}
   style={{
    left:`${position.x}px`,
    top:`${position.y}px`,
    width:resizable?`${panelSize.w}px`:`${sizeDefaults[size].w}px`,
    height:resizable?`${panelSize.h}px`:undefined,
    maxHeight:resizable?'none':'80vh'
   }}
  >
   {title&&(
    <div
     className={cn(
      'flex items-center justify-between bg-nier-bg-header text-nier-text-header px-4 py-2 flex-shrink-0',
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
   <div className="p-4 overflow-y-auto flex-1" style={{maxHeight:contentMaxH?`${contentMaxH}px`:'60vh'}}>
    {children}
   </div>
   {footer&&(
    <div className="flex items-center justify-end gap-3 px-4 py-3 border-t border-nier-border-light bg-nier-bg-selected/50 flex-shrink-0">
     {footer}
    </div>
)}
   {resizable&&(
    <div
     className="absolute bottom-0 right-0 w-4 h-4 cursor-se-resize"
     onMouseDown={handleResizeStart}
    >
     <svg viewBox="0 0 16 16" className="w-full h-full text-nier-text-light opacity-50">
      <path d="M14 14L14 8M14 14L8 14M10 14L14 10" stroke="currentColor" strokeWidth="1.5" fill="none"/>
     </svg>
    </div>
)}
  </div>,
  document.body
)
}
