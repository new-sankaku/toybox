import{useState}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{DocumentViewer}from'@/components/viewers/DocumentViewer'
import{CodeViewer}from'@/components/viewers/CodeViewer'
import type{Checkpoint}from'@/types/checkpoint'
import{cn}from'@/lib/utils'
import{CheckCircle,XCircle,RotateCcw,MessageSquare,Send,X}from'lucide-react'

interface CheckpointReviewViewProps{
 checkpoint:Checkpoint
 onApprove:()=>void
 onReject:(reason:string)=>void
 onRequestChanges:(feedback:string)=>void
 onClose:()=>void
}

type ViewMode='preview'|'raw'
type FeedbackAction='reject'|'revision'|null

export default function CheckpointReviewView({
 checkpoint,
 onApprove,
 onReject,
 onRequestChanges,
 onClose
}:CheckpointReviewViewProps):JSX.Element{
 const[viewMode,setViewMode]=useState<ViewMode>('preview')
 const[feedback,setFeedback]=useState('')
 const[showFeedbackForm,setShowFeedbackForm]=useState(false)
 const[feedbackAction,setFeedbackAction]=useState<FeedbackAction>(null)

 const getWaitingTime=()=>{
  const created=new Date(checkpoint.createdAt)
  const now=new Date()
  const diffMs=now.getTime()-created.getTime()
  const diffMins=Math.floor(diffMs/60000)

  if(diffMins<60)return`${diffMins}分`
  const hours=Math.floor(diffMins/60)
  const mins=diffMins%60
  return`${hours}時間${mins}分`
 }

 const handleApprove=()=>{
  onApprove()
 }

 const handleReject=()=>{
  if(feedback.trim()){
   onReject(feedback)
  }else{
   setShowFeedbackForm(true)
   setFeedbackAction('reject')
  }
 }

 const handleRequestChanges=()=>{
  if(feedback.trim()){
   onRequestChanges(feedback)
  }else{
   setShowFeedbackForm(true)
   setFeedbackAction('revision')
  }
 }

 const handleSubmitFeedback=()=>{
  if(!feedback.trim())return

  if(feedbackAction==='reject'){
   onReject(feedback)
  }else if(feedbackAction==='revision'){
   onRequestChanges(feedback)
  }
 }

 const handleCancelFeedback=()=>{
  setShowFeedbackForm(false)
  setFeedbackAction(null)
  setFeedback('')
 }

 const getContentString=(content:unknown):string=>{
  if(typeof content==='string'){
   return content
  }
  if(content&&typeof content==='object'){
   const obj=content as Record<string,unknown>
   if(typeof obj.text==='string'){
    return obj.text
   }
  }
  return JSON.stringify(content,null,2)
 }

 const renderOutput=()=>{
  const{output}=checkpoint

  if(viewMode==='raw'){
   const rawContent=typeof output.content==='string'
    ?output.content
    : JSON.stringify(output.content,null,2)
   return(
    <CodeViewer
     code={rawContent||'(no content)'}
     language={typeof output.content==='string'?'markdown' : 'json'}
     filename={typeof output.content==='string'?'output.md' : 'output.json'}
    />
)
  }

  const format=output.format||output.documentType

  if(format==='markdown'||checkpoint.type.includes('review')){
   return(
    <DocumentViewer
     content={getContentString(output.content)}
     title={checkpoint.title}
    />
)
  }

  if(format==='code'||output.type==='code'){
   return(
    <CodeViewer
     code={getContentString(output.content)}
     language="typescript"
     filename="output.ts"
    />
)
  }

  return(
   <DocumentViewer
    content={output.summary||getContentString(output.content)}
    title={checkpoint.title}
   />
)
 }

 return(
  <div className="p-6 animate-nier-fade-in h-full overflow-y-auto">
   {/*Header*/}
   <div className="flex items-center justify-between mb-6">
    <div>
     <div className="flex items-center gap-3 mb-2">
      <div className="w-1.5 h-6 bg-nier-accent-red"/>
      <h1 className="text-nier-h1 font-medium tracking-nier-wide">
       CHECKPOINT
      </h1>
      <span className="text-nier-text-light">-{checkpoint.title}</span>
     </div>
     <div className="flex items-center gap-4 text-nier-small text-nier-text-light ml-4">
      <span>Phase: {checkpoint.type.split('_')[0]}</span>
      <span>|</span>
      <span>待機時間:<span className="text-nier-accent-red">{getWaitingTime()}</span></span>
     </div>
    </div>
    <Button variant="ghost" onClick={onClose}>
     戻る
    </Button>
   </div>

   {/*Main Content*/}
   <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
    {/*Output Preview (3 columns)*/}
    <div className="lg:col-span-3">
     <Card>
      <CardHeader className="flex flex-row items-center justify-between">
       <DiamondMarker>出力プレビュー</DiamondMarker>
       <div className="flex gap-1">
        <button
         className={cn(
          'px-3 py-1 text-nier-caption tracking-nier transition-colors',
          viewMode==='preview'
           ?'bg-nier-bg-selected'
           : 'hover:bg-nier-bg-selected'
)}
         onClick={()=>setViewMode('preview')}
        >
         PREVIEW
        </button>
        <button
         className={cn(
          'px-3 py-1 text-nier-caption tracking-nier transition-colors',
          viewMode==='raw'
           ?'bg-nier-bg-selected'
           : 'hover:bg-nier-bg-selected'
)}
         onClick={()=>setViewMode('raw')}
        >
         RAW
        </button>
       </div>
      </CardHeader>
      <CardContent className="max-h-[50vh] min-h-[200px] overflow-auto">
       {renderOutput()}
      </CardContent>
     </Card>

     {/*Metadata*/}
     <Card className="mt-4">
      <CardContent className="py-3">
       <div className="flex items-center gap-6 text-nier-small text-nier-text-light">
        <span>Tokens: {checkpoint.output.tokensUsed?.toLocaleString() ?? '-'}</span>
        <span>|</span>
        <span>生成時間: {checkpoint.output.generationTimeMs?`${(checkpoint.output.generationTimeMs/1000).toFixed(1)}秒` : '-'}</span>
        <span>|</span>
        <span>作成: {new Date(checkpoint.createdAt).toLocaleString('ja-JP')}</span>
       </div>
      </CardContent>
     </Card>
    </div>

    {/*Actions Panel (1 column)*/}
    <div className="space-y-4">
     {/*Status*/}
     <Card>
      <CardHeader>
       <DiamondMarker>ステータス</DiamondMarker>
      </CardHeader>
      <CardContent>
       <div className="space-y-2">
        <div className="nier-status-row">
         <span className="nier-status-label">種別:</span>
         <span className="nier-status-value">{checkpoint.type}</span>
        </div>
        <div className="nier-status-row">
         <span className="nier-status-label">状態:</span>
         <span className="nier-status-value text-nier-accent-yellow">
          {checkpoint.status==='pending'?'承認待ち' : checkpoint.status}
         </span>
        </div>
       </div>
      </CardContent>
     </Card>

     {/*Feedback Form*/}
     {showFeedbackForm&&(
      <Card>
       <CardHeader>
        <DiamondMarker>
         {feedbackAction==='reject'?'却下理由' : '変更要求内容'}
        </DiamondMarker>
       </CardHeader>
       <CardContent className="space-y-3">
        <textarea
         className="nier-input min-h-[120px] resize-none"
         placeholder="フィードバックを入力..."
         value={feedback}
         onChange={(e)=>setFeedback(e.target.value)}
         autoFocus
        />
        <div className="flex gap-2">
         <Button
          variant={feedbackAction==='reject'?'danger' : 'default'}
          className="flex-1 gap-2"
          onClick={handleSubmitFeedback}
          disabled={!feedback.trim()}
         >
          <Send size={16}/>
          送信
         </Button>
         <Button
          variant="ghost"
          className="gap-2"
          onClick={handleCancelFeedback}
         >
          <X size={16}/>
          キャンセル
         </Button>
        </div>
       </CardContent>
      </Card>
)}

     {/*Action Buttons*/}
     <Card>
      <CardHeader className="bg-nier-accent-red">
       <span className="flex items-center gap-2">
        <span>◈</span>
        <span>アクション</span>
       </span>
      </CardHeader>
      <CardContent className="space-y-3">
       <Button
        variant="success"
        className="w-full justify-start gap-3"
        onClick={handleApprove}
       >
        <CheckCircle size={18}/>
        承認
       </Button>

       <Button
        className="w-full justify-start gap-3"
        onClick={handleRequestChanges}
       >
        <RotateCcw size={18}/>
        変更を要求
       </Button>

       <Button
        variant="danger"
        className="w-full justify-start gap-3"
        onClick={handleReject}
       >
        <XCircle size={18}/>
        却下
       </Button>

       {!showFeedbackForm&&(
        <Button
         variant="ghost"
         className="w-full justify-start gap-3 text-nier-text-light"
         onClick={()=>setShowFeedbackForm(true)}
        >
         <MessageSquare size={18}/>
         コメントを追加
        </Button>
)}
      </CardContent>
     </Card>
    </div>
   </div>
  </div>
)
}
