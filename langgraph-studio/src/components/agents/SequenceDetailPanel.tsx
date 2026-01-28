import{useState,useEffect,useCallback}from'react'
import{ChevronDown,ChevronRight}from'lucide-react'
import{cn}from'@/lib/utils'
import{FloatingPanel}from'@/components/ui/FloatingPanel'
import{traceApi,llmJobApi}from'@/services/apiService'
import type{ApiAgentTrace,ApiLlmJob}from'@/services/apiService'
import type{SequenceMessage}from'@/types/agent'

interface SequenceDetailPanelProps{
 isOpen:boolean
 onClose:()=>void
 selectedMessage:SequenceMessage|null
}

function CollapsibleSection({title,content}:{title:string;content:string|null}){
 const[open,setOpen]=useState(false)
 if(!content)return null
 return(
  <div className="border border-nier-border-light">
   <button
    className="flex items-center gap-1 w-full px-2 py-1 text-left text-nier-caption text-nier-text-main hover:bg-nier-bg-main/40 transition-colors"
    onClick={()=>setOpen(!open)}
   >
    {open?<ChevronDown size={12}/>:<ChevronRight size={12}/>}
    {title}
   </button>
   {open&&(
    <div className="px-2 py-1 border-t border-nier-border-light bg-nier-bg-selected max-h-[300px] overflow-y-auto">
     <pre className="text-[10px] text-nier-text-light whitespace-pre-wrap break-all font-mono leading-relaxed">{content}</pre>
    </div>
)}
  </div>
)
}

function InfoRow({label,value}:{label:string;value:string|number|null|undefined}){
 if(value===null||value===undefined||value==='')return null
 return(
  <div className="flex gap-2 text-nier-caption">
   <span className="text-nier-text-light flex-shrink-0 w-24">{label}</span>
   <span className="text-nier-text-main">{value}</span>
  </div>
)
}

function durationStr(startedAt:string|null|undefined,completedAt:string|null|undefined):string|null{
 if(!startedAt||!completedAt)return null
 const ms=new Date(completedAt).getTime()-new Date(startedAt).getTime()
 if(ms<1000)return`${ms}ms`
 return`${(ms/1000).toFixed(1)}s`
}

export function SequenceDetailPanel({isOpen,onClose,selectedMessage}:SequenceDetailPanelProps){
 const[traceDetail,setTraceDetail]=useState<ApiAgentTrace|null>(null)
 const[jobDetail,setJobDetail]=useState<ApiLlmJob|null>(null)
 const[loading,setLoading]=useState(false)
 const[error,setError]=useState<string|null>(null)

 const fetchDetail=useCallback(async(msg:SequenceMessage)=>{
  if(!msg.sourceId||!msg.sourceType)return
  setLoading(true)
  setError(null)
  setTraceDetail(null)
  setJobDetail(null)
  try{
   if(msg.sourceType==='trace'){
    const data=await traceApi.get(msg.sourceId)
    setTraceDetail(data)
   }else if(msg.sourceType==='job'){
    const data=await llmJobApi.get(msg.sourceId)
    setJobDetail(data)
   }
  }catch{
   setError('詳細データの取得に失敗しました')
  }finally{
   setLoading(false)
  }
 },[])

 useEffect(()=>{
  if(isOpen&&selectedMessage?.sourceId){
   fetchDetail(selectedMessage)
  }
 },[isOpen,selectedMessage?.sourceId,selectedMessage?.sourceType,fetchDetail])

 const title=selectedMessage?
  (selectedMessage.sourceType==='trace'?'トレース詳細':'LLMジョブ詳細')
  :'詳細'

 return(
  <FloatingPanel
   isOpen={isOpen}
   onClose={onClose}
   title={title}
   size="lg"
   panelId="sequence-detail"
  >
   {loading&&(
    <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
     読み込み中...
    </div>
)}
   {error&&(
    <div className="flex items-center justify-center py-8 text-nier-accent-red text-nier-caption">
     {error}
    </div>
)}
   {!loading&&!error&&traceDetail&&(
    <div className="space-y-2">
     <InfoRow label="モデル" value={traceDetail.modelUsed}/>
     <InfoRow label="ステータス" value={traceDetail.status}/>
     <InfoRow label="入力トークン" value={traceDetail.tokensInput?.toLocaleString()}/>
     <InfoRow label="出力トークン" value={traceDetail.tokensOutput?.toLocaleString()}/>
     <InfoRow label="所要時間" value={durationStr(traceDetail.startedAt,traceDetail.completedAt)}/>
     {traceDetail.errorMessage&&(
      <InfoRow label="エラー" value={traceDetail.errorMessage}/>
)}
     <div className="pt-1 space-y-1">
      <CollapsibleSection title="プロンプト送信内容" content={traceDetail.promptSent}/>
      <CollapsibleSection title="LLM応答内容" content={traceDetail.llmResponse}/>
     </div>
    </div>
)}
   {!loading&&!error&&jobDetail&&(
    <div className="space-y-2">
     <InfoRow label="モデル" value={jobDetail.model}/>
     <InfoRow label="ステータス" value={jobDetail.status}/>
     <InfoRow label="入力トークン" value={jobDetail.tokensInput?.toLocaleString()}/>
     <InfoRow label="出力トークン" value={jobDetail.tokensOutput?.toLocaleString()}/>
     <InfoRow label="所要時間" value={durationStr(jobDetail.createdAt,jobDetail.completedAt)}/>
     {jobDetail.errorMessage&&(
      <InfoRow label="エラー" value={jobDetail.errorMessage}/>
)}
     <div className="pt-1 space-y-1">
      {jobDetail.systemPrompt&&(
       <CollapsibleSection title="システムプロンプト" content={jobDetail.systemPrompt}/>
)}
      <CollapsibleSection title="プロンプト" content={jobDetail.prompt}/>
      <CollapsibleSection title="レスポンス" content={jobDetail.responseContent}/>
     </div>
    </div>
)}
   {!loading&&!error&&!traceDetail&&!jobDetail&&(
    <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
     メッセージを選択してください
    </div>
)}
  </FloatingPanel>
)
}
