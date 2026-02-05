import{useNavigatorStore}from'@/stores/navigatorStore'
import{cn}from'@/lib/utils'

export default function OperatorPanel():JSX.Element{
 const{isVisible,currentMessage,showMessage}=useNavigatorStore()

 const isActive=isVisible&&currentMessage!==null

 const handleIdleClick=()=>{
  if(!isActive){
   showMessage('オペレーター','システム状態は正常です。全エージェントが稼働中。何かあればお知らせください。')
  }
 }

 return(
  <div className="operator-panel">
   <div
    className={cn(
     'operator-frame',
     !isActive&&'operator-idle',
     !isActive&&'cursor-pointer'
)}
    onClick={handleIdleClick}
    title={!isActive?'クリックでオペレーター呼び出し':undefined}
   >
    <div className="operator-header nier-surface-header">
     <span className="operator-diamond">◇</span>
     <span className="operator-title">OPERATOR</span>
     <div className="operator-status">
      <span className={cn(
       'operator-status-dot',
       isActive?'operator-status-online':'operator-status-offline'
)}/>
      <span className="operator-status-text">
       {isActive?'通信中':'待機中'}
      </span>
     </div>
    </div>

    <div className="operator-portrait">
     <div className="operator-portrait-inner">
      {isActive?(
       <svg viewBox="0 0 100 100" className="operator-icon">
        <circle cx="50" cy="35" r="20" fill="none" stroke="currentColor" strokeWidth="2"/>
        <circle cx="43" cy="32" r="3" fill="currentColor"/>
        <circle cx="57" cy="32" r="3" fill="currentColor"/>
        <path d="M25 35 Q25 15,50 15 Q75 15,75 35" fill="none" stroke="currentColor" strokeWidth="2"/>
        <rect x="20" y="30" width="8" height="12" rx="2" fill="currentColor" opacity="0.7"/>
        <rect x="72" y="30" width="8" height="12" rx="2" fill="currentColor" opacity="0.7"/>
        <path d="M28 42 Q15 45,20 55 L25 53" fill="none" stroke="currentColor" strokeWidth="2"/>
        <circle cx="20" cy="55" r="4" fill="currentColor" opacity="0.7"/>
        <path d="M30 55 Q50 65,70 55 L75 75 Q50 85,25 75 Z" fill="currentColor" opacity="0.3" stroke="currentColor" strokeWidth="1.5"/>
        <path d="M40 58 L50 68 L60 58" fill="none" stroke="currentColor" strokeWidth="1.5"/>
       </svg>
):(
       <svg viewBox="0 0 100 100" className="operator-icon-idle">
        <circle cx="50" cy="50" r="25" fill="none" stroke="currentColor" strokeWidth="1" strokeDasharray="4 4"/>
        <circle cx="50" cy="50" r="8" fill="none" stroke="currentColor" strokeWidth="1"/>
       </svg>
)}
     </div>
     {isActive&&<div className="operator-scanline"/>}
    </div>

    <div className="operator-footer">
     <div className="operator-line"/>
     <span className="operator-label">
      {isActive?'送信中':'待機'}
     </span>
     <div className="operator-line"/>
    </div>
   </div>
  </div>
)
}
