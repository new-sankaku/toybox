import{useState,useEffect,useRef}from'react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{useProjectStore}from'@/stores/projectStore'
import{interventionApi,agentApi,type ApiIntervention,type ApiAgent}from'@/services/apiService'
import{FolderOpen,AlertTriangle,Send,Users,User,MessageSquare,Bot,UserCircle,Plus,Trash2}from'lucide-react'
import type{InterventionPriority,InterventionTarget}from'@/types/intervention'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'

export default function InterventionView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{getLabel}=useAgentDefinitionStore()
 const[interventions,setInterventions]=useState<ApiIntervention[]>([])
 const[agents,setAgents]=useState<ApiAgent[]>([])
 const[loading,setLoading]=useState(true)
 const[sending,setSending]=useState(false)
 const[selectedId,setSelectedId]=useState<string|null>(null)
 const chatEndRef=useRef<HTMLDivElement>(null)

 const[targetType,setTargetType]=useState<InterventionTarget>('all')
 const[targetAgentId,setTargetAgentId]=useState<string>('')
 const[priority,setPriority]=useState<InterventionPriority>('normal')
 const[message,setMessage]=useState('')
 const[showNewForm,setShowNewForm]=useState(false)

 useEffect(()=>{
  if(!currentProject)return

  const fetchData=async()=>{
   setLoading(true)
   try{
    const[interventionsData,agentsData]=await Promise.all([
     interventionApi.listByProject(currentProject.id),
     agentApi.listByProject(currentProject.id)
])
    setInterventions(interventionsData)
    setAgents(agentsData)
    if(interventionsData.length>0&&!selectedId){
     setSelectedId(interventionsData[0].id)
    }
   }catch(error){
    console.error('Failed to fetch data:',error)
   }finally{
    setLoading(false)
   }
  }

  fetchData()
 },[currentProject?.id])

 useEffect(()=>{
  chatEndRef.current?.scrollIntoView({behavior:'smooth'})
 },[selectedId,interventions])

 const handleSubmit=async(e:React.FormEvent)=>{
  e.preventDefault()
  if(!currentProject||!message.trim())return

  setSending(true)
  try{
   const newIntervention=await interventionApi.create(currentProject.id,{
    targetType,
    targetAgentId:targetType==='specific'?targetAgentId:undefined,
    priority,
    message:message.trim()
   })
   setInterventions([...interventions,newIntervention])
   setSelectedId(newIntervention.id)
   setMessage('')
   setShowNewForm(false)
  }catch(error){
   console.error('Failed to send intervention:',error)
  }finally{
   setSending(false)
  }
 }

 const handleReply=async(e:React.FormEvent)=>{
  e.preventDefault()
  if(!currentProject||!message.trim()||!selectedId)return

  const selected=interventions.find(i=>i.id===selectedId)
  if(!selected)return

  setSending(true)
  try{
   const newIntervention=await interventionApi.create(currentProject.id,{
    targetType:selected.targetType,
    targetAgentId:selected.targetAgentId||undefined,
    priority:selected.priority,
    message:message.trim()
   })
   setInterventions([...interventions,newIntervention])
   setMessage('')
  }catch(error){
   console.error('Failed to send reply:',error)
  }finally{
   setSending(false)
  }
 }

 const runningAgents=agents.filter(a=>a.status==='running')

 const handleDelete=async(interventionId:string)=>{
  try{
   await interventionApi.delete(interventionId)
   setInterventions(interventions.filter(i=>i.id!==interventionId))
   if(selectedId===interventionId){
    setSelectedId(null)
   }
  }catch(error){
   console.error('Failed to delete intervention:',error)
   setInterventions(interventions.filter(i=>i.id!==interventionId))
   if(selectedId===interventionId){
    setSelectedId(null)
   }
  }
 }

 const formatTime=(isoString:string)=>{
  const date=new Date(isoString)
  return date.toLocaleString('ja-JP',{
   month:'2-digit',
   day:'2-digit',
   hour:'2-digit',
   minute:'2-digit'
  })
 }

 const getTargetLabel=(intervention:ApiIntervention)=>{
  if(intervention.targetType==='all')return'全エージェント'
  const agent=agents.find(a=>a.id===intervention.targetAgentId)
  if(agent)return getLabel(agent.type)
  return intervention.targetAgentId||'不明'
 }

 const getStatusBadge=(status:string)=>{
  switch(status){
   case'pending':return<span className="text-nier-caption px-2 py-0.5 rounded bg-nier-bg-selected text-nier-text-light">送信待ち</span>
   case'delivered':return<span className="text-nier-caption px-2 py-0.5 rounded bg-nier-bg-selected text-nier-text-light">配信済み</span>
   case'acknowledged':return<span className="text-nier-caption px-2 py-0.5 rounded bg-nier-bg-selected text-nier-text-light">確認済み</span>
   case'processed':return<span className="text-nier-caption px-2 py-0.5 rounded bg-nier-bg-selected text-nier-text-main">処理完了</span>
   default:return null
  }
 }

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <Card>
     <CardContent>
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
       <p className="text-nier-body">プロジェクトを選択してください</p>
      </div>
     </CardContent>
    </Card>
   </div>
)
 }

 const sortedInterventions=[...interventions].sort((a,b)=>
  new Date(b.createdAt).getTime()-new Date(a.createdAt).getTime()
)

 const selectedIntervention=interventions.find(i=>i.id===selectedId)

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col">
   <div className="grid grid-cols-1 lg:grid-cols-4 gap-3 flex-1 overflow-hidden">
    {/*Left: Chat Room List*/}
    <Card className="flex flex-col overflow-hidden">
     <CardHeader className="flex-shrink-0">
      <DiamondMarker>チャット部屋</DiamondMarker>
      <span className="text-nier-caption text-nier-text-light ml-2">
       ({interventions.length}件)
      </span>
     </CardHeader>
     <CardContent className="flex-1 overflow-y-auto p-0">
      <div className="divide-y divide-nier-border">
       {/*New Chat Room Button*/}
       <button
        onClick={()=>{setShowNewForm(true);setSelectedId(null)}}
        className={`w-full p-3 text-left hover:bg-nier-bg-hover transition-colors flex items-center gap-2 ${
         showNewForm&&!selectedId?'bg-nier-bg-selected':''
        }`}
       >
        <Plus size={16} className="text-nier-text-light"/>
        <span className="text-nier-small text-nier-text-main">新規チャット</span>
       </button>

       {loading?(
        <div className="p-4 text-center text-nier-text-light text-nier-small">
         読み込み中...
        </div>
):sortedInterventions.length===0?(
        <div className="p-4 text-center text-nier-text-light text-nier-small">
         履歴なし
        </div>
):(
        sortedInterventions.map(intervention=>(
         <div
          key={intervention.id}
          onClick={()=>{setSelectedId(intervention.id);setShowNewForm(false)}}
          className={`w-full p-3 text-left hover:bg-nier-bg-hover transition-colors cursor-pointer ${
           selectedId===intervention.id?'bg-nier-bg-selected':''
          }`}
         >
          <div className="flex items-center justify-between mb-1">
           <span className="text-nier-small text-nier-text-main flex items-center gap-1">
            {intervention.targetType==='all'?(
             <Users size={12} className="text-nier-text-light"/>
):(
             <User size={12} className="text-nier-text-light"/>
)}
            {getTargetLabel(intervention)}
           </span>
           <div className="flex items-center gap-1">
            {intervention.priority==='urgent'&&(
             <AlertTriangle size={12} className="text-nier-accent-orange"/>
)}
            <button
             onClick={(e)=>{e.stopPropagation();handleDelete(intervention.id)}}
             className="p-1 hover:bg-nier-bg-main transition-colors text-nier-text-light hover:text-nier-text-main"
             title="削除"
            >
             <Trash2 size={12}/>
            </button>
           </div>
          </div>
          <p className="text-nier-caption text-nier-text-light line-clamp-1">
           {intervention.message}
          </p>
          <div className="flex items-center justify-between mt-1">
           <span className="text-nier-caption text-nier-text-light">
            {formatTime(intervention.createdAt)}
           </span>
           {getStatusBadge(intervention.status)}
          </div>
         </div>
))
)}
      </div>
     </CardContent>
    </Card>

    {/*Right: Chat Conversation*/}
    <div className="lg:col-span-3">
     <Card className="h-full flex flex-col">
      <CardHeader className="flex-shrink-0">
       <DiamondMarker>
        {showNewForm&&!selectedId?'新規介入':(
         selectedIntervention?`${getTargetLabel(selectedIntervention)} への介入`:'チャット'
)}
       </DiamondMarker>
      </CardHeader>
      <CardContent className="flex-1 flex flex-col overflow-hidden p-0">
       {showNewForm&&!selectedId?(
        <div className="flex-1 overflow-y-auto p-4">
         <div className="max-w-lg mx-auto space-y-4">
          <div>
           <label className="block text-nier-small text-nier-text-light mb-2">
            送信先
           </label>
           <div className="flex gap-2">
            <button
             type="button"
             onClick={()=>setTargetType('all')}
             className={`nier-button flex-1 flex items-center justify-center gap-2 ${
              targetType==='all'?'bg-nier-bg-selected border-nier-accent':'bg-nier-bg-panel'
             }`}
            >
             <Users size={14}/>
             全エージェント
            </button>
            <button
             type="button"
             onClick={()=>setTargetType('specific')}
             className={`nier-button flex-1 flex items-center justify-center gap-2 ${
              targetType==='specific'?'bg-nier-bg-selected border-nier-accent':'bg-nier-bg-panel'
             }`}
            >
             <User size={14}/>
             特定エージェント
            </button>
           </div>
          </div>

          {targetType==='specific'&&(
           <div>
            <label className="block text-nier-small text-nier-text-light mb-2">
             対象エージェント
            </label>
            <select
             value={targetAgentId}
             onChange={(e)=>setTargetAgentId(e.target.value)}
             className="nier-input w-full"
            >
             <option value="">選択...</option>
             {runningAgents.length>0?(
              runningAgents.map(agent=>(
               <option key={agent.id} value={agent.id}>
                {getLabel(agent.type)} (実行中)
               </option>
))
):(
              agents.map(agent=>(
               <option key={agent.id} value={agent.id}>
                {getLabel(agent.type)}
               </option>
))
)}
            </select>
           </div>
)}

          <div>
           <label className="block text-nier-small text-nier-text-light mb-2">
            緊急度
           </label>
           <div className="flex gap-2">
            <button
             type="button"
             onClick={()=>setPriority('normal')}
             className={`nier-button flex-1 flex items-center justify-center gap-2 ${
              priority==='normal'?'bg-nier-bg-selected border-nier-accent':'bg-nier-bg-panel'
             }`}
            >
             <MessageSquare size={14}/>
             通常
            </button>
            <button
             type="button"
             onClick={()=>setPriority('urgent')}
             className={`nier-button flex-1 flex items-center justify-center gap-2 ${
              priority==='urgent'?'bg-nier-bg-selected border-nier-accent-orange text-nier-accent-orange':'bg-nier-bg-panel'
             }`}
            >
             <AlertTriangle size={14}/>
             緊急
            </button>
           </div>
          </div>

          <div>
           <label className="block text-nier-small text-nier-text-light mb-2">
            メッセージ
           </label>
           <textarea
            value={message}
            onChange={(e)=>setMessage(e.target.value)}
            placeholder="エージェントへの指示を入力..."
            className="nier-input w-full h-32 resize-none"
           />
          </div>

          <button
           onClick={handleSubmit}
           disabled={sending||!message.trim()||(targetType==='specific'&&!targetAgentId)}
           className="nier-button w-full bg-nier-bg-panel border-nier-border hover:bg-nier-bg-selected disabled:opacity-50 flex items-center justify-center gap-2"
          >
           {sending?'送信中...':(
            <>
             <Send size={14}/>
             送信
            </>
)}
          </button>
         </div>
        </div>
):selectedIntervention?(
        <>
         <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <div className="flex justify-end">
           <div className="max-w-[70%]">
            <div className="flex items-center justify-end gap-2 mb-1">
             <span className="text-nier-caption text-nier-text-light">
              {formatTime(selectedIntervention.createdAt)}
             </span>
             {selectedIntervention.priority==='urgent'&&(
              <AlertTriangle size={12} className="text-nier-accent-orange"/>
)}
             <UserCircle size={14} className="text-nier-text-light"/>
            </div>
            <div className={`p-3 rounded-lg ${
             selectedIntervention.priority==='urgent'
              ?'bg-nier-bg-selected border border-nier-accent-orange'
              :'bg-nier-bg-selected border border-nier-border'
            }`}>
             <p className="text-nier-body text-nier-text-main whitespace-pre-wrap">
              {selectedIntervention.message}
             </p>
            </div>
            <div className="flex justify-end mt-1">
             {getStatusBadge(selectedIntervention.status)}
            </div>
           </div>
          </div>

          {(selectedIntervention as any).response&&(
           <div className="flex justify-start">
            <div className="max-w-[70%]">
             <div className="flex items-center gap-2 mb-1">
              <Bot size={14} className="text-nier-text-light"/>
              <span className="text-nier-caption text-nier-text-light">
               {(selectedIntervention as any).respondedBy||'AI'}
              </span>
              {(selectedIntervention as any).respondedAt&&(
               <span className="text-nier-caption text-nier-text-light">
                {formatTime((selectedIntervention as any).respondedAt)}
               </span>
)}
             </div>
             <div className="p-3 rounded-lg bg-nier-bg-panel border border-nier-border">
              <p className="text-nier-body text-nier-text-main whitespace-pre-wrap">
               {(selectedIntervention as any).response}
              </p>
             </div>
            </div>
           </div>
)}
          <div ref={chatEndRef}/>
         </div>

         <div className="border-t border-nier-border p-4 flex-shrink-0">
          <form onSubmit={handleReply} className="flex gap-2">
           <input
            type="text"
            value={message}
            onChange={(e)=>setMessage(e.target.value)}
            placeholder="返信を入力..."
            className="nier-input flex-1"
           />
           <button
            type="submit"
            disabled={sending||!message.trim()}
            className="nier-button px-4 bg-nier-bg-panel border-nier-border hover:bg-nier-bg-selected disabled:opacity-50"
           >
            <Send size={16}/>
           </button>
          </form>
         </div>
        </>
):(
        <div className="flex-1 flex items-center justify-center text-nier-text-light">
         <div className="text-center">
          <MessageSquare size={48} className="mx-auto mb-4 opacity-50"/>
          <p className="text-nier-body">チャットを選択してください</p>
          <p className="text-nier-caption mt-2">左側のリストから選択するか、新規チャットを作成</p>
         </div>
        </div>
)}
      </CardContent>
     </Card>
    </div>
   </div>
  </div>
)
}
