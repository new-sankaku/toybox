import{ReactNode,useEffect,useCallback}from'react'
import{createPortal}from'react-dom'
import{X}from'lucide-react'
import{cn}from'@/lib/utils'
import{Button}from'./Button'

export interface ModalProps{
 isOpen:boolean
 onClose:()=>void
 title?:string
 children:ReactNode
 footer?:ReactNode
 size?:'sm'|'md'|'lg'|'xl'
 closeOnOverlay?:boolean
 closeOnEscape?:boolean
}

const sizeClasses={
 sm:'max-w-sm',
 md:'max-w-md',
 lg:'max-w-2xl',
 xl:'max-w-4xl'
}

export function Modal({
 isOpen,
 onClose,
 title,
 children,
 footer,
 size='md',
 closeOnOverlay=true,
 closeOnEscape=true
}:ModalProps){
 const handleEscape=useCallback(
  (e:KeyboardEvent)=>{
   if(closeOnEscape&&e.key==='Escape'){
    onClose()
   }
  },
  [closeOnEscape,onClose]
)

 useEffect(()=>{
  if(isOpen){
   document.addEventListener('keydown',handleEscape)
   document.body.style.overflow='hidden'
  }
  return()=>{
   document.removeEventListener('keydown',handleEscape)
   document.body.style.overflow=''
  }
 },[isOpen,handleEscape])

 if(!isOpen)return null

 return createPortal(
  <div
   className="nier-modal-overlay"
   onClick={closeOnOverlay?onClose : undefined}
  >
   <div
    className={cn('nier-modal',sizeClasses[size],'w-full mx-4')}
    onClick={(e)=>e.stopPropagation()}
   >

    {title&&(
     <div className="flex items-center justify-between nier-surface-header px-4 py-3">
      <h2 className="text-nier-h2 tracking-nier-wide">{title}</h2>
      <Button
       variant="ghost"
       size="icon"
       onClick={onClose}
       className="text-nier-text-header hover:bg-white/10 h-8 w-8"
      >
       <X size={18}/>
      </Button>
     </div>
)}


    <div className="p-6 max-h-[60vh] overflow-y-auto">
     {children}
    </div>


    {footer&&(
     <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-nier-border-light bg-nier-bg-selected/50">
      {footer}
     </div>
)}
   </div>
  </div>,
  document.body
)
}
