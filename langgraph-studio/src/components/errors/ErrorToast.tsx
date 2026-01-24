import{AlertCircle,X,RefreshCw}from'lucide-react'

interface ErrorToastProps{
 message:string
 code?:string
 onRetry?:()=>void
 onDismiss:()=>void
 canRetry?:boolean
}

export function ErrorToast({message,code,onRetry,onDismiss,canRetry=false}:ErrorToastProps){
 return(
  <div className="nier-toast border-l-4 border-nier-accent-red min-w-[280px] md:min-w-[320px] max-w-[90vw] animate-nier-slide-in">
   <AlertCircle size={18} className="text-nier-accent-red flex-shrink-0"/>

   <div className="flex-1 min-w-0">
    {code&&(
     <div className="text-nier-caption text-nier-accent-red mb-0.5">
      {code}
     </div>
)}
    <p className="text-nier-small text-nier-text-main truncate">
     {message}
    </p>
   </div>

   <div className="flex items-center gap-1 flex-shrink-0">
    {canRetry&&onRetry&&(
     <button
      onClick={onRetry}
      className="p-1.5 hover:bg-nier-bg-selected rounded transition-colors"
      title="Retry"
     >
      <RefreshCw size={14} className="text-nier-text-light"/>
     </button>
)}
    <button
     onClick={onDismiss}
     className="p-1.5 hover:bg-nier-bg-selected rounded transition-colors"
     title="Dismiss"
    >
     <X size={14} className="text-nier-text-light"/>
    </button>
   </div>
  </div>
)
}
