import{useEffect,useCallback}from'react'
import{createPortal}from'react-dom'
import{X,CheckCircle,AlertCircle,AlertTriangle,Info}from'lucide-react'
import{cn}from'@/lib/utils'
import{useToastStore,type ToastItem}from'@/stores/toastStore'

const iconMap={
 success:CheckCircle,
 error:AlertCircle,
 warning:AlertTriangle,
 info:Info
}

const colorMap={
 success:'text-nier-accent-green border-nier-accent-green',
 error:'text-nier-accent-red border-nier-accent-red',
 warning:'text-nier-accent-orange border-nier-accent-orange',
 info:'text-nier-accent-blue border-nier-accent-blue'
}

interface ToastItemProps{
 toast:ToastItem
}

function ToastItemComponent({toast}:ToastItemProps){
 const Icon=iconMap[toast.type]
 const removeToast=useToastStore(s=>s.removeToast)
 const handleClose=useCallback(()=>removeToast(toast.id),[removeToast,toast.id])

 useEffect(()=>{
  if(toast.duration>0){
   const timer=setTimeout(handleClose,toast.duration)
   return()=>clearTimeout(timer)
  }
 },[toast.duration,handleClose])

 return(
  <div
   className={cn(
    'nier-toast min-w-[260px] md:min-w-[300px] max-w-[90vw] animate-nier-slide-in border-l-4',
    colorMap[toast.type]
)}
  >
   <Icon size={18} className={colorMap[toast.type].split(' ')[0]}/>
   <span className="flex-1 text-nier-small text-nier-text-main">{toast.message}</span>
   <button
    onClick={handleClose}
    className="text-nier-text-light hover:text-nier-text-main transition-colors"
   >
    <X size={16}/>
   </button>
  </div>
)
}

export function ToastContainer(){
 const toasts=useToastStore(s=>s.toasts)

 if(toasts.length===0)return null

 return createPortal(
  <div className="fixed bottom-4 right-4 z-[300] flex flex-col gap-2">
   {toasts.map((toast)=>(
    <ToastItemComponent key={toast.id} toast={toast}/>
))}
  </div>,
  document.body
)
}
