import{useEffect}from'react'
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
 onClose:()=>void
}

function ToastItemComponent({toast,onClose}:ToastItemProps){
 const Icon=iconMap[toast.type]

 useEffect(()=>{
  if(toast.duration>0){
   const timer=setTimeout(onClose,toast.duration)
   return()=>clearTimeout(timer)
  }
 },[toast.duration,onClose])

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
    onClick={onClose}
    className="text-nier-text-light hover:text-nier-text-main transition-colors"
   >
    <X size={16}/>
   </button>
  </div>
)
}

export function ToastContainer(){
 const{toasts,removeToast}=useToastStore()

 if(toasts.length===0)return null

 return createPortal(
  <div className="fixed bottom-4 right-4 z-[300] flex flex-col gap-2">
   {toasts.map((toast)=>(
    <ToastItemComponent key={toast.id} toast={toast} onClose={()=>removeToast(toast.id)}/>
))}
  </div>,
  document.body
)
}
