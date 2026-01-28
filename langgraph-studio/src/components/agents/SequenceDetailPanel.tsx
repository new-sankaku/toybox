import{useEffect,useCallback,useState}from'react'
import{FloatingPanel}from'@/components/ui/FloatingPanel'
import{traceApi,llmJobApi,agentApi}from'@/services/apiService'
import type{ApiAgentTrace,ApiLlmJob,ApiAgent}from'@/services/apiService'
import type{SequenceMessage}from'@/types/agent'

interface SequenceDetailPanelProps{
 isOpen:boolean
 onClose:()=>void
 selectedMessage:SequenceMessage|null
}

function ExpandedSection({title,content}:{title:string;content:string|null}){
 if(!content)return null
 return(
  <div className="border border-nier-border-light">
   <div className="px-2 py-1 text-nier-caption text-nier-text-main bg-nier-bg-panel border-b border-nier-border-light">
    {title}
   </div>
   <div className="px-2 py-1 bg-nier-bg-selected overflow-y-auto" style={{maxHeight:'40vh'}}>
    <pre className="text-[10px] text-nier-text-light whitespace-pre-wrap break-all font-mono leading-relaxed">{content}</pre>
   </div>
  </div>
)
}

export function SequenceDetailPanel({isOpen,onClose,selectedMessage}:SequenceDetailPanelProps){
 const[traceDetail,setTraceDetail]=useState<ApiAgentTrace|null>(null)
 const[jobDetail,setJobDetail]=useState<ApiLlmJob|null>(null)
 const[agentDetail,setAgentDetail]=useState<ApiAgent|null>(null)
 const[loading,setLoading]=useState(false)
 const[error,setError]=useState<string|null>(null)

 const fetchDetail=useCallback(async(msg:SequenceMessage)=>{
  if(!msg.sourceId||!msg.sourceType)return
  setLoading(true)
  setError(null)
  setTraceDetail(null)
  setJobDetail(null)
  setAgentDetail(null)
  try{
   if(msg.sourceType==='trace'){
    const data=await traceApi.get(msg.sourceId)
    setTraceDetail(data)
   }else if(msg.sourceType==='job'){
    const data=await llmJobApi.get(msg.sourceId)
    setJobDetail(data)
   }else if(msg.sourceType==='agent'){
    const data=await agentApi.get(msg.sourceId)
    setAgentDetail(data)
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
  (selectedMessage.sourceType==='trace'?'トレース詳細':
   selectedMessage.sourceType==='job'?'LLMジョブ詳細':
   selectedMessage.sourceType==='agent'?'エージェント詳細':'詳細')
  :'詳細'

 return(
  <FloatingPanel
   isOpen={isOpen}
   onClose={onClose}
   title={title}
   size="lg"
   panelId="sequence-detail"
   resizable
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
     {traceDetail.errorMessage&&(
      <div className="px-2 py-1 text-nier-caption text-nier-accent-red border border-nier-accent-red bg-nier-bg-selected">
       {traceDetail.errorMessage}
      </div>
     )}
     <ExpandedSection title="プロンプト送信内容" content={traceDetail.promptSent}/>
     <ExpandedSection title="LLM応答内容" content={traceDetail.llmResponse}/>
    </div>
)}
   {!loading&&!error&&jobDetail&&(
    <div className="space-y-2">
     {jobDetail.errorMessage&&(
      <div className="px-2 py-1 text-nier-caption text-nier-accent-red border border-nier-accent-red bg-nier-bg-selected">
       {jobDetail.errorMessage}
      </div>
     )}
     {jobDetail.systemPrompt&&(
      <ExpandedSection title="システムプロンプト" content={jobDetail.systemPrompt}/>
     )}
     <ExpandedSection title="プロンプト" content={jobDetail.prompt}/>
     <ExpandedSection title="レスポンス" content={jobDetail.responseContent}/>
    </div>
)}
   {!loading&&!error&&agentDetail&&(
    <div className="space-y-2">
     {agentDetail.error&&(
      <div className="px-2 py-1 text-nier-caption text-nier-accent-red border border-nier-accent-red bg-nier-bg-selected">
       {agentDetail.error}
      </div>
     )}
     {agentDetail.currentTask&&(
      <ExpandedSection title="現在のタスク" content={agentDetail.currentTask}/>
     )}
     {agentDetail.metadata&&(
      <ExpandedSection title="メタデータ" content={JSON.stringify(agentDetail.metadata,null,2)}/>
     )}
    </div>
)}
   {!loading&&!error&&!traceDetail&&!jobDetail&&!agentDetail&&(
    <div className="flex items-center justify-center py-8 text-nier-text-light text-nier-caption">
     メッセージを選択してください
    </div>
)}
  </FloatingPanel>
)
}
