import{useConnectionStore}from'@/stores/connectionStore'
import{cn}from'@/lib/utils'

export default function ConnectionStatus():JSX.Element{
 const{status} = useConnectionStore()

 const statusConfig = {
  connected:{
   color:'bg-nier-accent-green',
   text:'Connected',
   pulse:false
  },
  connecting:{
   color:'bg-nier-accent-yellow',
   text:'Connecting...',
   pulse:true
  },
  reconnecting:{
   color:'bg-nier-accent-orange',
   text:'Reconnecting...',
   pulse:true
  },
  disconnected:{
   color:'bg-nier-accent-red',
   text:'Disconnected',
   pulse:false
  }
 }

 const config = statusConfig[status]

 return(
  <div className="flex items-center gap-2 text-nier-text-header text-nier-small">
   <span
    className={cn(
     'w-2 h-2 rounded-full',
     config.color,
     config.pulse && 'animate-pulse-slow'
    )}
   />
   <span className="tracking-nier">{config.text}</span>
  </div>
 )
}
