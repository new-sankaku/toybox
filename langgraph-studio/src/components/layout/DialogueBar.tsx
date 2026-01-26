import{useEffect}from'react'
import{useNavigatorStore}from'@/stores/navigatorStore'

const AUTO_DISMISS_MS=5000

export default function DialogueBar():JSX.Element|null{
 const{isVisible,currentMessage,dismissMessage}=useNavigatorStore()

 useEffect(()=>{
  if(!isVisible||!currentMessage)return
  const timer=setTimeout(dismissMessage,AUTO_DISMISS_MS)
  return()=>clearTimeout(timer)
 },[isVisible,currentMessage,dismissMessage])

 if(!isVisible||!currentMessage){
  return null
 }

 return(
  <div className="dialogue-bar-container" onClick={dismissMessage}>
   <div className="dialogue-content">
    <span className="dialogue-speaker">
     <span className="dialogue-diamond">◇</span>
     {currentMessage.speaker}
    </span>
    <p className="dialogue-text">{currentMessage.text}</p>
   </div>
   <div className="dialogue-hint">クリックで閉じる</div>
  </div>
)
}
