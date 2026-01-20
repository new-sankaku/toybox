import{AlertTriangle,RefreshCw,SkipForward,Pause,ArrowRight}from'lucide-react'
import{Modal}from'@/components/ui/Modal'
import{Button}from'@/components/ui/Button'
import{Card,CardContent}from'@/components/ui/Card'

interface RecoveryOption{
 action:'retry'|'skip'|'pause'|'rollback'
 label:string
 description:string
 recommended?:boolean
}

interface RecoveryModalProps{
 isOpen:boolean
 onClose:()=>void
 errorType:string
 errorMessage:string
 agentId?:string
 agentName?:string
 taskName?:string
 retryCount?:number
 maxRetries?:number
 onAction:(action:RecoveryOption['action'])=>void
}

const defaultOptions:RecoveryOption[]=[
 {
  action:'retry',
  label:'Retry Task',
  description:'Attempt to run the task again with the same parameters',
  recommended:true
 },
 {
  action:'skip',
  label:'Skip Task',
  description:'Skip this task and continue with the next one'
 },
 {
  action:'pause',
  label:'Pause Project',
  description:'Pause the entire project for manual intervention'
 }
]

const actionIcons={
 retry:RefreshCw,
 skip:SkipForward,
 pause:Pause,
 rollback:ArrowRight
}

export function RecoveryModal({
 isOpen,
 onClose,
 errorType,
 errorMessage,
 agentId,
 agentName,
 taskName,
 retryCount=0,
 maxRetries=3,
 onAction
}:RecoveryModalProps){
 const canRetry=retryCount<maxRetries

 const options=defaultOptions.map((opt)=>({
  ...opt,
  disabled:opt.action==='retry'&&!canRetry
 }))

 return(
  <Modal
   isOpen={isOpen}
   onClose={onClose}
   title="RECOVERY REQUIRED"
   size="lg"
  >
   {/* Error Summary */}
   <div className="mb-6">
    <div className="flex items-start gap-4 p-4 bg-nier-accent-red/10 border border-nier-accent-red/30">
     <AlertTriangle className="text-nier-accent-red flex-shrink-0 mt-0.5" size={24}/>
     <div>
      <div className="text-nier-small font-medium tracking-nier mb-1">
       {errorType}
      </div>
      <p className="text-nier-body text-nier-text-main">
       {errorMessage}
      </p>
     </div>
    </div>
   </div>

   {/* Context */}
   {(agentName||taskName)&&(
    <div className="mb-6 grid grid-cols-2 gap-4 text-nier-small">
     {agentName&&(
      <div>
       <span className="text-nier-text-light">Agent:</span>
       <span className="font-medium">{agentName}</span>
      </div>
)}
     {taskName&&(
      <div>
       <span className="text-nier-text-light">Task:</span>
       <span className="font-medium">{taskName}</span>
      </div>
)}
     <div>
      <span className="text-nier-text-light">Retry attempts:</span>
      <span className="font-medium">{retryCount}/{maxRetries}</span>
     </div>
    </div>
)}

   {/* Recovery Options */}
   <div className="space-y-3">
    <div className="text-nier-small text-nier-text-light mb-2">
     SELECT RECOVERY ACTION
    </div>
    {options.map((option)=>{
     const Icon=actionIcons[option.action]
     const isDisabled='disabled' in option&&option.disabled

     return(
      <Card
       key={option.action}
       className={`cursor-pointer transition-all ${
        isDisabled
         ?'opacity-50 cursor-not-allowed'
         : 'hover:bg-nier-bg-selected'
       } ${option.recommended?'border-nier-accent-green' : ''}`}
       onClick={()=>!isDisabled&&onAction(option.action)}
      >
       <CardContent className="py-3">
        <div className="flex items-center gap-4">
         <div className={`p-2 rounded ${
          option.recommended?'bg-nier-accent-green/20' : 'bg-nier-bg-selected'
         }`}>
          <Icon size={20} className={
           option.recommended?'text-nier-accent-green' : 'text-nier-text-main'
          }/>
         </div>
         <div className="flex-1">
          <div className="flex items-center gap-2">
           <span className="text-nier-body font-medium">{option.label}</span>
           {option.recommended&&(
            <span className="text-nier-caption text-nier-accent-green">
             Recommended
            </span>
)}
           {isDisabled&&(
            <span className="text-nier-caption text-nier-accent-red">
             Max retries reached
            </span>
)}
          </div>
          <p className="text-nier-small text-nier-text-light">
           {option.description}
          </p>
         </div>
        </div>
       </CardContent>
      </Card>
)
    })}
   </div>
  </Modal>
)
}
