import{useState,useEffect}from'react'
import{Card,CardContent,CardHeader,CardTitle}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{interventionApi,agentApi,type ApiIntervention,type ApiAgent}from'@/services/apiService'
import{Hand,FolderOpen,AlertTriangle,Send,Users,User,Clock,CheckCircle,MessageSquare}from'lucide-react'
import type{InterventionPriority,InterventionTarget}from'@/types/intervention'

export default function InterventionView():JSX.Element{
 const{currentProject}=useProjectStore()
 const[interventions,setInterventions]=useState<ApiIntervention[]>([])
 const[agents,setAgents]=useState<ApiAgent[]>([])
 const[loading,setLoading]=useState(true)
 const[sending,setSending]=useState(false)

 // Form state
 const[targetType,setTargetType]=useState<InterventionTarget>('all')
 const[targetAgentId,setTargetAgentId]=useState<string>('')
 const[priority,setPriority]=useState<InterventionPriority>('normal')
 const[message,setMessage]=useState('')

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
   }catch(error){
    console.error('Failed to fetch data:',error)
   }finally{
    setLoading(false)
   }
  }

  fetchData()
 },[currentProject?.id])

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
   setInterventions([newIntervention,...interventions])
   setMessage('')
   setTargetType('all')
   setTargetAgentId('')
   setPriority('normal')
  }catch(error){
   console.error('Failed to send intervention:',error)
  }finally{
   setSending(false)
  }
 }

 const runningAgents=agents.filter(a=>a.status==='running')

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <div className="nier-page-header-row">
     <div className="nier-page-header-left">
      <h1 className="nier-page-title">INTERVENTION</h1>
      <span className="nier-page-subtitle">-人間の介入</span>
     </div>
    </div>
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

 const getStatusIcon=(status:string)=>{
  switch(status){
   case'pending':return<Clock size={14} className="text-yellow-500"/>
   case'delivered':return<Send size={14} className="text-blue-500"/>
   case'acknowledged':return<MessageSquare size={14} className="text-purple-500"/>
   case'processed':return<CheckCircle size={14} className="text-green-500"/>
   default:return null
  }
 }

 const getStatusLabel=(status:string)=>{
  switch(status){
   case'pending':return'送信待ち'
   case'delivered':return'配信済み'
   case'acknowledged':return'確認済み'
   case'processed':return'処理完了'
   default:return status
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

 return(
  <div className="p-4 animate-nier-fade-in">
   <div className="nier-page-header-row">
    <div className="nier-page-header-left">
     <h1 className="nier-page-title">INTERVENTION</h1>
     <span className="nier-page-subtitle">-人間の介入</span>
    </div>
    <div className="nier-page-header-right">
     <div className="flex items-center gap-2 text-nier-caption text-nier-text-light">
      <Hand size={14}/>
      <span>いつでもエージェントに指示を送信できます</span>
     </div>
    </div>
   </div>

   <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
    {/* Send Intervention Form */}
    <Card>
     <CardHeader>
      <CardTitle className="flex items-center gap-2">
       <Send size={18}/>
       新規介入メッセージ
      </CardTitle>
     </CardHeader>
     <CardContent>
      <form onSubmit={handleSubmit} className="space-y-4">
       {/* Target Selection */}
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-2">
         送信先
        </label>
        <div className="flex gap-2">
         <button
          type="button"
          onClick={()=>setTargetType('all')}
          className={`nier-button flex-1 flex items-center justify-center gap-2 ${
           targetType==='all'?'bg-nier-light':'bg-nier-dark'
          }`}
         >
          <Users size={16}/>
          全エージェント
         </button>
         <button
          type="button"
          onClick={()=>setTargetType('specific')}
          className={`nier-button flex-1 flex items-center justify-center gap-2 ${
           targetType==='specific'?'bg-nier-light':'bg-nier-dark'
          }`}
         >
          <User size={16}/>
          特定エージェント
         </button>
        </div>
       </div>

       {/* Agent Selection (if specific) */}
       {targetType==='specific'&&(
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-2">
          対象エージェント
         </label>
         <select
          value={targetAgentId}
          onChange={(e)=>setTargetAgentId(e.target.value)}
          className="nier-input w-full"
          required={targetType==='specific'}
         >
          <option value="">選択してください</option>
          {runningAgents.length>0?(
           runningAgents.map(agent=>(
            <option key={agent.id} value={agent.id}>
             {agent.metadata?.displayName||agent.type}(実行中)
            </option>
           ))
          ):(
           agents.map(agent=>(
            <option key={agent.id} value={agent.id}>
             {agent.metadata?.displayName||agent.type}
            </option>
           ))
          )}
         </select>
         {runningAgents.length===0&&agents.length>0&&(
          <p className="text-nier-caption text-yellow-600 mt-1">
           実行中のエージェントがありません
          </p>
         )}
        </div>
       )}

       {/* Priority Selection */}
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-2">
         緊急度
        </label>
        <div className="flex gap-2">
         <button
          type="button"
          onClick={()=>setPriority('normal')}
          className={`nier-button flex-1 flex items-center justify-center gap-2 ${
           priority==='normal'?'bg-nier-light':'bg-nier-dark'
          }`}
         >
          <MessageSquare size={16}/>
          通常
         </button>
         <button
          type="button"
          onClick={()=>setPriority('urgent')}
          className={`nier-button flex-1 flex items-center justify-center gap-2 ${
           priority==='urgent'?'bg-red-100 border-red-500 text-red-700':'bg-nier-dark'
          }`}
         >
          <AlertTriangle size={16}/>
          緊急
         </button>
        </div>
        {priority==='urgent'&&(
         <p className="text-nier-caption text-red-600 mt-1">
          緊急メッセージはプロジェクトを一時停止します
         </p>
        )}
       </div>

       {/* Message */}
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-2">
         メッセージ
        </label>
        <textarea
         value={message}
         onChange={(e)=>setMessage(e.target.value)}
         placeholder="エージェントへの指示を入力..."
         className="nier-input w-full h-32 resize-none"
         required
        />
       </div>

       {/* Submit Button */}
       <button
        type="submit"
        disabled={sending||!message.trim()||(targetType==='specific'&&!targetAgentId)}
        className="nier-button w-full bg-nier-accent text-white hover:bg-nier-accent-hover disabled:opacity-50 flex items-center justify-center gap-2"
       >
        {sending?(
         <>送信中...</>
        ):(
         <>
          <Send size={16}/>
          介入メッセージを送信
         </>
        )}
       </button>
      </form>
     </CardContent>
    </Card>

    {/* Intervention History */}
    <Card>
     <CardHeader>
      <CardTitle className="flex items-center gap-2">
       <Clock size={18}/>
       介入履歴
       {interventions.length>0&&(
        <span className="text-nier-caption text-nier-text-light ml-2">
         ({interventions.length}件)
        </span>
       )}
      </CardTitle>
     </CardHeader>
     <CardContent>
      {loading?(
       <div className="text-center py-8 text-nier-text-light">
        読み込み中...
       </div>
      ):interventions.length===0?(
       <div className="text-center py-8 text-nier-text-light">
        <Hand size={32} className="mx-auto mb-2 opacity-50"/>
        <p>まだ介入履歴がありません</p>
       </div>
      ):(
       <div className="space-y-3 max-h-[400px] overflow-y-auto">
        {interventions.map(intervention=>(
         <div
          key={intervention.id}
          className={`p-3 border rounded ${
           intervention.priority==='urgent'
            ?'border-red-300 bg-red-50'
            :'border-nier-border bg-nier-dark'
          }`}
         >
          <div className="flex items-center justify-between mb-2">
           <div className="flex items-center gap-2">
            {intervention.priority==='urgent'&&(
             <AlertTriangle size={14} className="text-red-500"/>
            )}
            <span className="text-nier-caption">
             {intervention.targetType==='all'?'全エージェント':
              agents.find(a=>a.id===intervention.targetAgentId)?.metadata?.displayName||
              intervention.targetAgentId}
            </span>
           </div>
           <div className="flex items-center gap-1 text-nier-caption">
            {getStatusIcon(intervention.status)}
            <span>{getStatusLabel(intervention.status)}</span>
           </div>
          </div>
          <p className="text-nier-body text-nier-text mb-2 line-clamp-2">
           {intervention.message}
          </p>
          <div className="text-nier-caption text-nier-text-light">
           {formatTime(intervention.createdAt)}
          </div>
         </div>
        ))}
       </div>
      )}
     </CardContent>
    </Card>
   </div>
  </div>
 )
}
