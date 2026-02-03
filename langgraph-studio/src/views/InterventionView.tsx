import{useState,useEffect,useRef}from'react'
import{Card,CardContent,CardHeader}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Select}from'@/components/ui/Select'
import{Textarea}from'@/components/ui/Textarea'
import{useProjectStore}from'@/stores/projectStore'
import{useInterventionStore}from'@/stores/interventionStore'
import{interventionApi,agentApi,type ApiIntervention,type ApiAgent}from'@/services/apiService'
import{FolderOpen,AlertTriangle,Send,Users,User,MessageSquare,Bot,UserCircle,Plus,Trash2}from'lucide-react'
import type{InterventionPriority,InterventionTarget,Intervention}from'@/types/intervention'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'

export default function InterventionView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{getLabel}=useAgentDefinitionStore()
 const{interventions:storeInterventions,setInterventions:setStoreInterventions,addIntervention,updateIntervention,removeIntervention}=useInterventionStore()
 const[agents,setAgents]=useState<ApiAgent[]>([])
 const[loading,setLoading]=useState(true)
 const[sending,setSending]=useState(false)
 const[selectedId,setSelectedId]=useState<string|null>(null)
 const chatEndRef=useRef<HTMLDivElement>(null)
 const interventions=storeInterventions.filter(i=>i.projectId===currentProject?.id)

 const[targetType,setTargetType]=useState<InterventionTarget>('all')
 const[targetAgentId,setTargetAgentId]=useState<string>('')
 const[priority,setPriority]=useState<InterventionPriority>('normal')
 const[message,setMessage]=useState('')
 const[showNewForm,setShowNewForm]=useState(false)
 const[showDeleteDialog,setShowDeleteDialog]=useState<string|null>(null)

 useEffect(()=>{
  if(!currentProject)return

  const fetchData=async()=>{
   setLoading(true)
   try{
    const[interventionsData,agentsData]=await Promise.all([
     interventionApi.listByProject(currentProject.id),
     agentApi.listByProject(currentProject.id)
])
    setStoreInterventions(interventionsData as Intervention[])
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
   addIntervention(newIntervention as Intervention)
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
   const updatedIntervention=await interventionApi.respond(selectedId,message.trim())
   updateIntervention(selectedId,updatedIntervention as Intervention)
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
   removeIntervention(interventionId)
   if(selectedId===interventionId){
    setSelectedId(null)
   }
  }catch(error){
   console.error('Failed to delete intervention:',error)
   removeIntervention(interventionId)
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
   case'pending':return<span className="text-nier-caption px-2 py-0.5 rounded nier-surface-selected-muted">送信待ち</span>
   case'delivered':return<span className="text-nier-caption px-2 py-0.5 rounded nier-surface-selected-muted">配信済み</span>
   case'acknowledged':return<span className="text-nier-caption px-2 py-0.5 rounded nier-surface-selected-muted">確認済み</span>
   case'processed':return<span className="text-nier-caption px-2 py-0.5 rounded nier-surface-selected">処理完了</span>
   case'waiting_response':return<span className="text-nier-caption px-2 py-0.5 rounded bg-nier-accent-orange/20 text-nier-accent-orange">返答待ち</span>
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
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
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
             onClick={(e)=>{e.stopPropagation();setShowDeleteDialog(intervention.id)}}
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
        <div className="flex-1 overflow-y-auto p-3">
         <div className="max-w-lg mx-auto space-y-2">
          <div className="border border-nier-border-light px-3 py-2 bg-nier-bg-panel/30">
           <DiamondMarker>送信先</DiamondMarker>
           <div className="grid grid-cols-2 gap-2 mt-2">
            <button
             type="button"
             onClick={()=>setTargetType('all')}
             className={`relative flex items-center gap-2 px-3 py-1.5 border transition-all duration-nier-fast tracking-nier text-nier-small ${
              targetType==='all'
               ?'nier-surface-selected border-nier-border-dark'
               :'nier-surface-panel-muted border-nier-border-light hover:bg-nier-bg-selected hover:text-nier-text-main'
             }`}
            >
             {targetType==='all'&&<span className="absolute left-0 top-0 bottom-0 w-1 bg-nier-text-main"/>}
             <Users size={14}/>
             <span>全エージェント</span>
            </button>
            <button
             type="button"
             onClick={()=>setTargetType('specific')}
             className={`relative flex items-center gap-2 px-3 py-1.5 border transition-all duration-nier-fast tracking-nier text-nier-small ${
              targetType==='specific'
               ?'nier-surface-selected border-nier-border-dark'
               :'nier-surface-panel-muted border-nier-border-light hover:bg-nier-bg-selected hover:text-nier-text-main'
             }`}
            >
             {targetType==='specific'&&<span className="absolute left-0 top-0 bottom-0 w-1 bg-nier-text-main"/>}
             <User size={14}/>
             <span>特定エージェント</span>
            </button>
           </div>

           {targetType==='specific'&&(
            <div className="mt-2">
             <Select
              value={targetAgentId}
              onChange={(e)=>setTargetAgentId(e.target.value)}
              placeholder="エージェントを選択..."
              options={
               (runningAgents.length>0?runningAgents:agents).map(agent=>({
                value:agent.id,
                label:`${getLabel(agent.type)}${runningAgents.length>0?' (実行中)':''}`
               }))
              }
             />
            </div>
)}
          </div>

          <div className="border border-nier-border-light px-3 py-2 bg-nier-bg-panel/30">
           <DiamondMarker>緊急度</DiamondMarker>
           <div className="grid grid-cols-2 gap-2 mt-2">
            <button
             type="button"
             onClick={()=>setPriority('normal')}
             className={`relative flex items-center gap-2 px-3 py-1.5 border transition-all duration-nier-fast tracking-nier text-nier-small ${
              priority==='normal'
               ?'nier-surface-selected border-nier-border-dark'
               :'nier-surface-panel-muted border-nier-border-light hover:bg-nier-bg-selected hover:text-nier-text-main'
             }`}
            >
             {priority==='normal'&&<span className="absolute left-0 top-0 bottom-0 w-1 bg-nier-text-main"/>}
             <MessageSquare size={14}/>
             <span>通常</span>
            </button>
            <button
             type="button"
             onClick={()=>setPriority('urgent')}
             className={`relative flex items-center gap-2 px-3 py-1.5 border transition-all duration-nier-fast tracking-nier text-nier-small ${
              priority==='urgent'
               ?'bg-nier-bg-selected border-nier-accent-red text-nier-accent-red'
               :'bg-nier-bg-panel border-nier-border-light text-nier-accent-red hover:bg-nier-bg-selected'
             }`}
            >
             {priority==='urgent'&&<span className="absolute left-0 top-0 bottom-0 w-1 bg-nier-accent-red"/>}
             <AlertTriangle size={14}/>
             <span>緊急</span>
            </button>
           </div>
          </div>

          <div className="border border-nier-border-light px-3 py-2 bg-nier-bg-panel/30">
           <DiamondMarker>メッセージ</DiamondMarker>
           <div className="mt-2">
            <Textarea
             value={message}
             onChange={(e)=>setMessage(e.target.value)}
             placeholder="エージェントへの指示を入力..."
             className="h-28"
            />
           </div>
          </div>

          <Button
           variant="primary"
           onClick={handleSubmit}
           disabled={sending||!message.trim()||(targetType==='specific'&&!targetAgentId)}
           className="w-full"
          >
           {sending?'送信中...':(
            <>
             <Send size={14}/>
             介入を送信
            </>
)}
          </Button>
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
             {!selectedIntervention.responses?.length&&getStatusBadge(selectedIntervention.status)}
            </div>
           </div>
          </div>

          {selectedIntervention.responses?.map((response,idx)=>(
           <div key={idx} className={`flex ${response.sender==='operator'?'justify-end':'justify-start'}`}>
            <div className="max-w-[70%]">
             <div className={`flex items-center gap-2 mb-1 ${response.sender==='operator'?'justify-end':''}`}>
              {response.sender==='agent'&&<Bot size={14} className="text-nier-accent-blue"/>}
              <span className="text-nier-caption text-nier-text-light">
               {response.sender==='agent'
                ?(response.agentId?getLabel(agents.find(a=>a.id===response.agentId)?.type||''):'Agent')
                :'オペレーター'}
              </span>
              <span className="text-nier-caption text-nier-text-light">
               {formatTime(response.createdAt)}
              </span>
              {response.sender==='operator'&&<UserCircle size={14} className="text-nier-text-light"/>}
             </div>
             <div className={`p-3 rounded-lg ${
              response.sender==='agent'
               ?'bg-nier-bg-panel border border-nier-accent-blue/30'
               :'bg-nier-bg-selected border border-nier-border'
             }`}>
              <p className="text-nier-body text-nier-text-main whitespace-pre-wrap">
               {response.message}
              </p>
             </div>
            </div>
           </div>
))}

          {selectedIntervention.responses?.length>0&&(
           <div className="flex justify-center">
            {getStatusBadge(selectedIntervention.status)}
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

   {/*Delete Confirmation Dialog*/}
   {showDeleteDialog&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-[90vw] md:max-w-sm lg:max-w-md">
      <CardHeader>
       <div className="flex items-center gap-2 text-nier-text-main">
        <AlertTriangle size={18}/>
        <span>削除の確認</span>
       </div>
      </CardHeader>
      <CardContent>
       <p className="text-nier-body mb-4">
        このチャットを削除しますか？
       </p>
       <p className="text-nier-small text-nier-text-main mb-6">
        この操作は取り消せません。
       </p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setShowDeleteDialog(null)}>
         キャンセル
        </Button>
        <Button
         variant="danger"
         onClick={()=>{
          handleDelete(showDeleteDialog)
          setShowDeleteDialog(null)
         }}
        >
         削除する
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>
)}
  </div>
)
}
