import{useNavigatorStore}from'@/stores/navigatorStore'

export default function DialogueBar():JSX.Element|null{
 const{isActive,currentMessage,dismissMessage}=useNavigatorStore()

 if(!isActive||!currentMessage){
  return null
 }

 return(
  <div className="dialogue-overlay" onClick={dismissMessage}>
   <div className="dialogue-bar">
    <div className="dialogue-content">
     <span className="dialogue-speaker">
      <span className="dialogue-diamond">◇</span>
      {currentMessage.speaker}
     </span>
     <p className="dialogue-text">{currentMessage.text}</p>
    </div>
    <div className="dialogue-hint">Click to continue...</div>
   </div>
  </div>
 )
}
