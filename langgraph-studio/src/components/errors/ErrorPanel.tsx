import{AlertCircle,RefreshCw,XCircle,ChevronDown,ChevronUp}from'lucide-react'
import{useState}from'react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'

export interface ErrorAction{
 label:string
 action:string
 data?:Record<string,unknown>
}

export interface ErrorDetail{
 code:string
 category:'connection'|'llm'|'agent'|'state'|'user'
 type:string
 message:string
 details?:Record<string,unknown>
 suggestions?:string[]
 actions?:ErrorAction[]
 timestamp:string
 requestId?:string
}

interface ErrorPanelProps{
 error:ErrorDetail
 onAction?:(action:string,data?:Record<string,unknown>)=>void
 onDismiss?:()=>void
 expanded?:boolean
}

const categoryColors={
 connection:'bg-nier-accent-blue',
 llm:'bg-nier-accent-orange',
 agent:'bg-nier-accent-red',
 state:'bg-nier-accent-yellow',
 user:'bg-nier-accent-green'
}

export function ErrorPanel({error,onAction,onDismiss,expanded:initialExpanded=false}:ErrorPanelProps){
 const[expanded,setExpanded]=useState(initialExpanded)

 return(
  <Card className="border-nier-accent-red">
   <CardHeader className="bg-nier-accent-red/10 border-b border-nier-accent-red/30">
    <div className="flex items-center justify-between">
     <div className="flex items-center gap-3">
      <AlertCircle className="text-nier-accent-red" size={20}/>
      <div>
       <div className="text-nier-small font-medium tracking-nier">
        {error.code}
       </div>
       <div className="text-nier-caption text-nier-text-light">
        {error.category.toUpperCase()} ERROR
       </div>
      </div>
     </div>
     <div className="flex items-center gap-2">
      <button
       onClick={()=>setExpanded(!expanded)}
       className="p-1 hover:bg-nier-bg-selected rounded"
      >
       {expanded?<ChevronUp size={16}/>:<ChevronDown size={16}/>}
      </button>
      {onDismiss&&(
       <button
        onClick={onDismiss}
        className="p-1 hover:bg-nier-bg-selected rounded text-nier-text-light"
       >
        <XCircle size={16}/>
       </button>
)}
     </div>
    </div>
   </CardHeader>

   <CardContent className="py-4">
    {/*Error Message*/}
    <p className="text-nier-body mb-4">{error.message}</p>

    {/*Expanded Details*/}
    {expanded&&(
     <div className="space-y-4 mb-4">
      {/*Details*/}
      {error.details&&Object.keys(error.details).length>0&&(
       <div className="bg-nier-bg-main p-3 text-nier-small">
        <div className="text-nier-caption text-nier-text-light mb-2">DETAILS</div>
        <pre className="overflow-x-auto">
         {JSON.stringify(error.details,null,2)}
        </pre>
       </div>
)}

      {/*Suggestions*/}
      {error.suggestions&&error.suggestions.length>0&&(
       <div>
        <div className="text-nier-caption text-nier-text-light mb-2">SUGGESTIONS</div>
        <ul className="space-y-1">
         {error.suggestions.map((suggestion,i)=>(
          <li key={i} className="flex items-start gap-2 text-nier-small">
           <span className="text-nier-accent-blue">◇</span>
           {suggestion}
          </li>
))}
        </ul>
       </div>
)}

      {/*Meta*/}
      <div className="flex items-center gap-4 text-nier-caption text-nier-text-light">
       <span>Time: {new Date(error.timestamp).toLocaleTimeString()}</span>
       {error.requestId&&<span>Request ID: {error.requestId}</span>}
      </div>
     </div>
)}

    {/*Actions*/}
    {error.actions&&error.actions.length>0&&onAction&&(
     <div className="flex items-center gap-2 pt-3 border-t border-nier-border-light">
      {error.actions.map((action)=>(
       <Button
        key={action.action}
        size="sm"
        variant={action.action==='retry'?'primary' : 'default'}
        onClick={()=>onAction(action.action,action.data)}
       >
        {action.action==='retry'&&<RefreshCw size={14}/>}
        {action.label}
       </Button>
))}
     </div>
)}
   </CardContent>
  </Card>
)
}
