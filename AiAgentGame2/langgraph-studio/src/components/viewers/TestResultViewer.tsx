import{useState}from'react'
import{CheckCircle,XCircle,AlertTriangle,ChevronDown,ChevronRight,Clock}from'lucide-react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{Progress}from'@/components/ui/Progress'
import{cn}from'@/lib/utils'

export interface TestCase{
 id:string
 name:string
 status:'passed'|'failed'|'skipped'|'pending'
 duration?:number
 error?:{
  message:string
  stack?:string
  expected?:string
  actual?:string
 }
}

export interface TestSuite{
 id:string
 name:string
 status:'passed'|'failed'|'partial'
 tests:TestCase[]
 duration?:number
}

export interface TestResult{
 totalTests:number
 passed:number
 failed:number
 skipped:number
 duration:number
 suites:TestSuite[]
 timestamp:string
}

interface TestResultViewerProps{
 result:TestResult
 expandedByDefault?:boolean
}

const statusIcons={
 passed:CheckCircle,
 failed:XCircle,
 skipped:AlertTriangle,
 pending:Clock,
 partial:AlertTriangle
}

const statusColors={
 passed:'text-nier-accent-green',
 failed:'text-nier-accent-red',
 skipped:'text-nier-accent-yellow',
 pending:'text-nier-text-light',
 partial:'text-nier-accent-orange'
}

export function TestResultViewer({result,expandedByDefault=false}:TestResultViewerProps){
 const[expandedSuites,setExpandedSuites]=useState<Set<string>>(
  expandedByDefault?new Set(result.suites.map((s)=>s.id)) : new Set()
)

 const passRate=result.totalTests>0
  ?(result.passed/result.totalTests)*100
  : 0

 const toggleSuite=(suiteId:string)=>{
  setExpandedSuites((prev)=>{
   const next=new Set(prev)
   if(next.has(suiteId)){
    next.delete(suiteId)
   }else{
    next.add(suiteId)
   }
   return next
  })
 }

 const formatDuration=(ms:number):string=>{
  if(ms<1000)return`${ms}ms`
  return`${(ms/1000).toFixed(2)}s`
 }

 return(
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between w-full">
     <span className="text-nier-small">TEST RESULTS</span>
     <span className="text-nier-caption text-nier-text-header/70">
      {formatDuration(result.duration)}
     </span>
    </div>
   </CardHeader>

   <CardContent>
    {/*Summary*/}
    <div className="mb-6">
     <div className="flex items-center justify-between mb-2">
      <span className="text-nier-small text-nier-text-light">Pass Rate</span>
      <span className={cn(
       'text-nier-h2 font-medium',
       passRate===100?'text-nier-accent-green' :
        passRate>=80?'text-nier-accent-yellow' :
         'text-nier-accent-red'
)}>
       {Math.round(passRate)}%
      </span>
     </div>
     <Progress
      value={passRate}
      className={cn(
       passRate===100&&'[&>div]:bg-nier-accent-green',
       passRate>=80&&passRate<100&&'[&>div]:bg-nier-accent-yellow',
       passRate<80&&'[&>div]:bg-nier-accent-red'
)}
     />
    </div>

    {/*Stats*/}
    <div className="grid grid-cols-4 gap-2 mb-6">
     <div className="text-center p-2 bg-nier-bg-main">
      <div className="text-nier-h2 font-medium">{result.totalTests}</div>
      <div className="text-nier-caption text-nier-text-light">Total</div>
     </div>
     <div className="text-center p-2 bg-nier-accent-green/10">
      <div className="text-nier-h2 font-medium text-nier-accent-green">{result.passed}</div>
      <div className="text-nier-caption text-nier-text-light">Passed</div>
     </div>
     <div className="text-center p-2 bg-nier-accent-red/10">
      <div className="text-nier-h2 font-medium text-nier-accent-red">{result.failed}</div>
      <div className="text-nier-caption text-nier-text-light">Failed</div>
     </div>
     <div className="text-center p-2 bg-nier-accent-yellow/10">
      <div className="text-nier-h2 font-medium text-nier-accent-yellow">{result.skipped}</div>
      <div className="text-nier-caption text-nier-text-light">Skipped</div>
     </div>
    </div>

    {/*Test Suites*/}
    <div className="space-y-2">
     {result.suites.map((suite)=>{
      const Icon=statusIcons[suite.status]
      const isExpanded=expandedSuites.has(suite.id)

      return(
       <div key={suite.id} className="border border-nier-border-light">
        {/*Suite Header*/}
        <button
         className="w-full flex items-center gap-3 px-3 py-2 hover:bg-nier-bg-selected transition-colors"
         onClick={()=>toggleSuite(suite.id)}
        >
         {isExpanded?(
          <ChevronDown size={16} className="text-nier-text-light"/>
) : (
          <ChevronRight size={16} className="text-nier-text-light"/>
)}
         <Icon size={16} className={statusColors[suite.status]}/>
         <span className="flex-1 text-left text-nier-small font-medium">
          {suite.name}
         </span>
         <span className="text-nier-caption text-nier-text-light">
          {suite.tests.filter((t)=>t.status==='passed').length}/{suite.tests.length}
         </span>
        </button>

        {/*Test Cases*/}
        {isExpanded&&(
         <div className="border-t border-nier-border-light">
          {suite.tests.map((test)=>{
           const TestIcon=statusIcons[test.status]
           return(
            <div key={test.id}>
             <div className="flex items-center gap-3 px-3 py-2 pl-10 bg-nier-bg-main">
              <TestIcon size={14} className={statusColors[test.status]}/>
              <span className="flex-1 text-nier-small">{test.name}</span>
              {test.duration&&(
               <span className="text-nier-caption text-nier-text-light">
                {formatDuration(test.duration)}
               </span>
)}
             </div>

             {/*Error details*/}
             {test.error&&(
              <div className="px-3 py-2 pl-10 bg-nier-accent-red/5 border-t border-nier-border-light">
               <p className="text-nier-small text-nier-accent-red mb-1">
                {test.error.message}
               </p>
               {test.error.expected&&test.error.actual&&(
                <div className="grid grid-cols-2 gap-2 mt-2 text-nier-caption">
                 <div>
                  <span className="text-nier-text-light">Expected:</span>
                  <code className="text-nier-accent-green">{test.error.expected}</code>
                 </div>
                 <div>
                  <span className="text-nier-text-light">Actual:</span>
                  <code className="text-nier-accent-red">{test.error.actual}</code>
                 </div>
                </div>
)}
               {test.error.stack&&(
                <pre className="mt-2 p-2 bg-nier-bg-main text-nier-caption overflow-x-auto">
                 {test.error.stack}
                </pre>
)}
              </div>
)}
            </div>
)
          })}
         </div>
)}
       </div>
)
     })}
    </div>

    {/*Timestamp*/}
    <div className="mt-4 text-nier-caption text-nier-text-light text-right">
     Run at: {new Date(result.timestamp).toLocaleString()}
    </div>
   </CardContent>
  </Card>
)
}
