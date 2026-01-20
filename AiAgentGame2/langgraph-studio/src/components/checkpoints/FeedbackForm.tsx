import{useState}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{cn}from'@/lib/utils'
import{Send,X}from'lucide-react'

interface FeedbackFormProps{
 onSubmit:(feedback:string)=>void
 onCancel:()=>void
 placeholder?:string
 submitLabel?:string
 title?:string
 initialValue?:string
 required?:boolean
}

const quickFeedbackOptions=[
 {label:'品質向上が必要',value:'品質が基準に達していません。改善をお願いします。'},
 {label:'詳細が不足',value:'詳細な説明が不足しています。より具体的な内容を追加してください。'},
 {label:'方向性の修正',value:'コンセプトの方向性を修正する必要があります。'},
 {label:'整合性の確認',value:'他の要素との整合性を確認してください。'}
]

export function FeedbackForm({
 onSubmit,
 onCancel,
 placeholder='フィードバックを入力してください...',
 submitLabel='送信',
 title='フィードバック',
 initialValue='',
 required=false
}:FeedbackFormProps):JSX.Element{
 const[feedback,setFeedback]=useState(initialValue)

 const handleSubmit=()=>{
  if(required&&!feedback.trim()){
   return
  }
  onSubmit(feedback)
 }

 const handleQuickSelect=(value:string)=>{
  setFeedback((prev)=>(prev?`${prev}\n\n${value}` : value))
 }

 return(
  <Card>
   <CardHeader>
    <DiamondMarker>{title}</DiamondMarker>
   </CardHeader>
   <CardContent className="space-y-4">
    {/* Quick Feedback Options */}
    <div>
     <p className="text-nier-caption text-nier-text-light mb-2">
      クイック選択:
     </p>
     <div className="flex flex-wrap gap-2">
      {quickFeedbackOptions.map((option)=>(
       <button
        key={option.label}
        className={cn(
         'px-2 py-1 text-nier-caption tracking-nier',
         'border border-nier-border-light',
         'hover:bg-nier-bg-selected transition-colors'
)}
        onClick={()=>handleQuickSelect(option.value)}
       >
        {option.label}
       </button>
))}
     </div>
    </div>

    {/* Textarea */}
    <div>
     <textarea
      className={cn(
       'nier-input min-h-[120px] resize-none',
       required&&!feedback.trim()&&'border-nier-accent-red'
)}
      placeholder={placeholder}
      value={feedback}
      onChange={(e)=>setFeedback(e.target.value)}
     />
     {required&&!feedback.trim()&&(
      <p className="text-nier-caption text-nier-accent-red mt-1">
       フィードバックは必須です
      </p>
)}
    </div>

    {/* Character Count */}
    <div className="flex items-center justify-between text-nier-caption text-nier-text-light">
     <span>{feedback.length} 文字</span>
     {feedback.length>0&&(
      <button
       className="hover:text-nier-text-main"
       onClick={()=>setFeedback('')}
      >
       クリア
      </button>
)}
    </div>

    {/* Action Buttons */}
    <div className="flex items-center justify-end gap-3 pt-2 border-t border-nier-border-light">
     <Button
      variant="ghost"
      onClick={onCancel}
     >
      <X size={14}/>
      <span className="ml-1.5">キャンセル</span>
     </Button>
     <Button
      onClick={handleSubmit}
      disabled={required&&!feedback.trim()}
     >
      <Send size={14}/>
      <span className="ml-1.5">{submitLabel}</span>
     </Button>
    </div>
   </CardContent>
  </Card>
)
}
