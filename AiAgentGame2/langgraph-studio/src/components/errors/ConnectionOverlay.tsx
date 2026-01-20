import{WifiOff,RefreshCw,Loader2}from'lucide-react'
import{Button}from'@/components/ui/Button'
import type{ConnectionStatus}from'@/stores/connectionStore'

interface ConnectionOverlayProps{
 status:ConnectionStatus
 reconnectAttempts:number
 maxAttempts?:number
 onManualReconnect:()=>void
}

export function ConnectionOverlay({
 status,
 reconnectAttempts,
 maxAttempts=5,
 onManualReconnect
}:ConnectionOverlayProps){
 if(status==='connected'||status==='connecting'){
  return null
 }

 const isReconnecting=status==='reconnecting'
 const canRetry=!isReconnecting

 return(
  <div className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[250] flex items-center justify-center animate-nier-fade-in">
   <div className="bg-nier-bg-panel border border-nier-border-dark p-8 max-w-md w-full mx-4 text-center">
    {/* Icon */}
    <div className="flex justify-center mb-6">
     {isReconnecting?(
      <div className="w-16 h-16 rounded-full bg-nier-accent-orange/20 flex items-center justify-center">
       <Loader2 size={32} className="text-nier-accent-orange animate-spin"/>
      </div>
) : (
      <div className="w-16 h-16 rounded-full bg-nier-accent-red/20 flex items-center justify-center">
       <WifiOff size={32} className="text-nier-accent-red"/>
      </div>
)}
    </div>

    {/* Title */}
    <h2 className="text-nier-h1 font-medium tracking-nier-wide mb-2">
     {isReconnecting?'RECONNECTING...' : 'CONNECTION LOST'}
    </h2>

    {/* Message */}
    <p className="text-nier-small text-nier-text-light mb-6">
     {isReconnecting
      ?`Attempting to restore connection (${reconnectAttempts}/${maxAttempts})...`
      : 'Unable to connect to the backend server. Please check your connection and try again.'}
    </p>

    {/* Progress indicator for reconnecting */}
    {isReconnecting&&(
     <div className="mb-6">
      <div className="flex justify-center gap-1">
       {Array.from({length:maxAttempts}).map((_,i)=>(
        <div
         key={i}
         className={`w-2 h-2 rounded-full transition-colors ${
          i<reconnectAttempts
           ?'bg-nier-accent-orange'
           : 'bg-nier-border-dark'
         }`}
        />
))}
      </div>
     </div>
)}

    {/* Actions */}
    {canRetry&&(
     <Button
      variant="primary"
      onClick={onManualReconnect}
      className="w-full"
     >
      <RefreshCw size={16}/>
      Reconnect
     </Button>
)}

    {/* Additional info */}
    <p className="text-nier-caption text-nier-text-light mt-4">
     Your progress has been saved locally.
    </p>
   </div>
  </div>
)
}
