import{useState,useEffect,useRef}from'react'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{useNavigatorStore}from'@/stores/navigatorStore'
import{useAgentStore}from'@/stores/agentStore'
import{useCheckpointStore}from'@/stores/checkpointStore'
import{useMetricsStore}from'@/stores/metricsStore'
import{logsApi,metricsApi,agentApi,checkpointApi,assetApi,aiRequestApi,type ApiSystemLog,type ApiAsset}from'@/services/apiService'
import type{Agent}from'@/types/agent'
import type{Checkpoint}from'@/types/checkpoint'
import type{ProjectMetrics}from'@/types/project'
import{cn}from'@/lib/utils'
import{Progress}from'@/components/ui/Progress'
import{ChevronRight,ChevronLeft}from'lucide-react'
import OperatorPanel from'./OperatorPanel'

function formatTime(seconds:number):string{
 if(seconds<60)return`${Math.round(seconds)}秒`
 if(seconds<3600)return`${Math.floor(seconds/60)}分${Math.round(seconds%60)}秒`
 const hours=Math.floor(seconds/3600)
 const mins=Math.floor((seconds%3600)/60)
 return`${hours}時間${mins}分`
}

function formatTokenCount(count:number):string{
 if(count>=1000000)return`${(count/1000000).toFixed(1)}m`
 if(count>=1000)return`${(count/1000).toFixed(1)}k`
 return count.toString()
}

function formatCost(tokens:number):string{
 const cost=tokens*0.00001
 if(cost<0.01)return`${cost.toFixed(4)}`
 if(cost<1)return`${cost.toFixed(2)}`
 return`${cost.toFixed(2)}`
}

function formatFileSize(sizeStr:string):number{
 const match=sizeStr.match(/^([\d.]+)\s*(B|KB|MB|GB)?$/i)
 if(!match)return 0
 const value=parseFloat(match[1])
 const unit=(match[2]||'B').toUpperCase()
 switch(unit){
  case'GB':return value*1024*1024*1024
  case'MB':return value*1024*1024
  case'KB':return value*1024
  default:return value
 }
}

function formatSize(bytes:number):string{
 if(bytes>=1024*1024*1024)return`${(bytes/(1024*1024*1024)).toFixed(1)}GB`
 if(bytes>=1024*1024)return`${(bytes/(1024*1024)).toFixed(1)}MB`
 if(bytes>=1024)return`${(bytes/1024).toFixed(1)}KB`
 return`${bytes}B`
}

export default function ActivitySidebar():JSX.Element{
 const{currentProject}=useProjectStore()
 const{setActiveTab}=useNavigationStore()
 const{showMessage}=useNavigatorStore()
 const agentStore=useAgentStore()
 const checkpointStore=useCheckpointStore()
 const metricsStore=useMetricsStore()
 const[isCollapsed,setIsCollapsed]=useState(false)
 const[assets,setAssets]=useState<ApiAsset[]>([])
 const[logs,setLogs]=useState<ApiSystemLog[]>([])
 const[aiGenerating,setAiGenerating]=useState(0)
 const lastProjectIdRef=useRef<string|null>(null)

 const agents:Agent[]=currentProject
  ?agentStore.agents.filter(a=>a.projectId===currentProject.id)
  :[]
 const checkpoints:Checkpoint[]=currentProject
  ?checkpointStore.checkpoints.filter(cp=>cp.projectId===currentProject.id)
  :[]
 const metrics:ProjectMetrics|null=metricsStore.projectMetrics

 useEffect(()=>{
  if(!currentProject){
   setAssets([])
   setLogs([])
   setAiGenerating(0)
   lastProjectIdRef.current=null
   return
  }

  if(lastProjectIdRef.current===currentProject.id){
   return
  }

  const fetchData=async()=>{
   try{
    const[metricsData,agentsData,checkpointsData,assetsData,logsData,aiStats]=await Promise.all([
     metricsApi.getByProject(currentProject.id),
     agentApi.listByProject(currentProject.id),
     checkpointApi.listByProject(currentProject.id),
     assetApi.listByProject(currentProject.id),
     logsApi.getByProject(currentProject.id),
     aiRequestApi.getStats(currentProject.id)
])

    metricsStore.setProjectMetrics(metricsData as ProjectMetrics)
    agentStore.setAgents(agentsData as Agent[])
    checkpointStore.setCheckpoints(checkpointsData as Checkpoint[])
    setAssets(assetsData)
    setLogs(logsData)
    setAiGenerating(aiStats.processing+aiStats.pending)
    lastProjectIdRef.current=currentProject.id
   }catch(error){
    console.error('Failed to fetch sidebar data:',error)
   }
  }

  fetchData()
 },[currentProject?.id,metricsStore,agentStore,checkpointStore])

 const completedAgents=agents.filter(a=>a.status==='completed').length
 const totalAgents=agents.length

 const pendingCheckpoints=checkpoints.filter(cp=>cp.status==='pending').length

 const errorLogs=logs.filter(l=>l.level==='error').length

 const totalAssets=assets.length
 const pendingAssets=assets.filter(a=>a.approvalStatus==='pending').length

 const generatingCount=aiGenerating

 const totalProjectSize=assets.reduce((acc,asset)=>{
  return acc+formatFileSize(asset.size||'0')
 },0)

 const[highlights,setHighlights]=useState<Record<string,boolean>>({})
 const prevValues=useRef<Record<string,number>>({})

 useEffect(()=>{
  const currentValues:Record<string,number>={
   token:metrics?.totalTokensUsed||0,
   agent:completedAgents,
   checkpoints:pendingCheckpoints,
   assets:pendingAssets,
   logs:logs.length,
   errors:errorLogs,
   generating:generatingCount
  }

  const newHighlights:Record<string,boolean>={}

  Object.keys(currentValues).forEach(key=>{
   if(prevValues.current[key]!==undefined&&prevValues.current[key]!==currentValues[key]){
    newHighlights[key]=true
   }
  })


  if(prevValues.current.checkpoints!==undefined&&pendingCheckpoints>prevValues.current.checkpoints){
   showMessage('オペレーター',`新しい承認が${pendingCheckpoints-prevValues.current.checkpoints}件追加されました。承認をお願いします。`)
  }
  if(prevValues.current.assets!==undefined&&pendingAssets>prevValues.current.assets){
   showMessage('オペレーター',`新しいアセットが${pendingAssets-prevValues.current.assets}件生成されました。確認をお願いします。`)
  }
  if(prevValues.current.errors!==undefined&&errorLogs>prevValues.current.errors){
   showMessage('オペレーター','警告：新しいエラーが検出されました。ログを確認してください。')
  }

  if(Object.keys(newHighlights).length>0){
   setHighlights(prev=>({...prev,...newHighlights}))

   setTimeout(()=>{
    setHighlights(prev=>{
     const updated={...prev}
     Object.keys(newHighlights).forEach(key=>{
      updated[key]=false
     })
     return updated
    })
   },1000)
  }

  prevValues.current=currentValues
 },[metrics?.totalTokensUsed,completedAgents,pendingCheckpoints,pendingAssets,logs.length,errorLogs,generatingCount,showMessage])

 if(!currentProject){
  return(
   <div className={cn(
    'bg-nier-bg-panel border-l border-nier-border-light flex flex-col transition-all duration-200',
    isCollapsed?'w-10' : 'w-64'
)}>
    <button
     onClick={()=>setIsCollapsed(!isCollapsed)}
     className="p-2 hover:bg-nier-bg-hover transition-colors border-b border-nier-border-light"
    >
     {isCollapsed?<ChevronLeft size={16}/>:<ChevronRight size={16}/>}
    </button>

    {!isCollapsed&&(
     <div className="flex-1 flex items-center justify-center text-nier-text-light text-nier-caption p-4 text-center">
      プロジェクト未選択
     </div>
)}
   </div>
)
 }

 return(
  <div className={cn(
   'bg-nier-bg-panel border-l border-nier-border-light flex flex-col transition-all duration-200',
   isCollapsed?'w-10' : 'w-64'
)}>
   {/*Header*/}
   <div className="flex items-center justify-between border-b border-nier-border-light">
    <button
     onClick={()=>setIsCollapsed(!isCollapsed)}
     className="p-2 hover:bg-nier-bg-hover transition-colors"
    >
     {isCollapsed?<ChevronLeft size={16}/>:<ChevronRight size={16}/>}
    </button>
    {!isCollapsed&&(
     <span className="text-nier-caption text-nier-text-light pr-3">SUMMARY</span>
)}
   </div>

   {!isCollapsed&&(
    <>
     {/*Project Status-Compact*/}
     <div className="px-2 py-1.5 border-b border-nier-border-light">
      <div className="flex items-center justify-between">
       <div className="text-[11px] truncate flex-1 font-medium">{currentProject.name}</div>
       <span className="text-[10px] px-1 py-0.5 border ml-1 bg-nier-bg-selected border-nier-border-light text-nier-text-light">
        {currentProject.status==='running'?'実行中' :
         currentProject.status==='paused'?'一時停止' :
          currentProject.status==='completed'?'完了' :
           currentProject.status==='failed'?'エラー' : '下書き'}
       </span>
      </div>
      {metrics&&(
       <div className="mt-1">
        <div className="flex items-center justify-between text-[11px] text-nier-text-light mb-0.5">
         <span className="truncate flex-1 mr-2">{metrics.phaseName}</span>
         <span>{metrics.progressPercent}%</span>
        </div>
        <Progress value={metrics.progressPercent} className="h-1.5"/>
       </div>
)}
     </div>

     {/*Summary List*/}
     <div className="px-2 py-1.5 text-[11px] space-y-1">
      <div className={cn('flex justify-between transition-colors duration-300',highlights.token&&'bg-nier-accent-yellow/30')}>
       <span className="text-nier-text-light">Token</span>
       <span className="text-nier-text-main">{metrics?formatTokenCount(metrics.totalTokensUsed) : 0}</span>
      </div>
      <div className={cn('flex justify-between transition-colors duration-300',highlights.token&&'bg-nier-accent-yellow/30')}>
       <span className="text-nier-text-light">料金</span>
       <span className="text-nier-text-main">${metrics?formatCost(metrics.totalTokensUsed) : '0'}</span>
      </div>
      <div className={cn('flex justify-between transition-colors duration-300',highlights.agent&&'bg-nier-accent-yellow/30')}>
       <span className="text-nier-text-light">Agent</span>
       <span className="text-nier-text-main">{completedAgents}/{totalAgents}</span>
      </div>
      <div className="flex justify-between">
       <span className="text-nier-text-light">経過時間</span>
       <span className="text-nier-text-main">{metrics?formatTime(metrics.elapsedTimeSeconds) : '-'}</span>
      </div>
      <div className="flex justify-between">
       <span className="text-nier-text-light">残り時間</span>
       <span className="text-nier-text-main">{metrics?.estimatedRemainingSeconds?formatTime(metrics.estimatedRemainingSeconds) : '-'}</span>
      </div>
      <button onClick={()=>setActiveTab('checkpoints')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300',highlights.checkpoints&&'bg-nier-accent-yellow/30')}>
       <span className="text-nier-text-light">承認待ち</span>
       <span className="text-nier-text-main">{pendingCheckpoints}件</span>
      </button>
      <button onClick={()=>setActiveTab('data')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300',highlights.assets&&'bg-nier-accent-yellow/30')}>
       <span className="text-nier-text-light">生成素材承認待ち</span>
       <span className="text-nier-text-main">{pendingAssets}件</span>
      </button>
      <button onClick={()=>setActiveTab('logs')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300',highlights.logs&&'bg-nier-accent-yellow/30')}>
       <span className="text-nier-text-light">Log</span>
       <span className="text-nier-text-main">{logs.length}件</span>
      </button>
      <button onClick={()=>setActiveTab('agents')} className={cn('w-full flex justify-between hover:bg-nier-bg-hover px-0.5 -mx-0.5 transition-colors duration-300',highlights.generating&&'bg-nier-accent-yellow/30')}>
       <span className="text-nier-text-light">AI生成中</span>
       <span className="text-nier-text-main">{generatingCount}件</span>
      </button>
     </div>

     {/*Output*/}
     <div className="px-2 py-1.5 text-[11px] border-t border-nier-border-light">
      <div className="text-nier-text-light text-[9px] tracking-wider mb-1">OUTPUT</div>
      <div className="space-y-0.5">
       <div className="flex justify-between">
        <span className="text-nier-text-light">キャラクター</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.characters?.count||0}{metrics?.generationCounts?.characters?.unit||'体'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">背景</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.backgrounds?.count||0}{metrics?.generationCounts?.backgrounds?.unit||'枚'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">UIパーツ</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.ui?.count||0}{metrics?.generationCounts?.ui?.unit||'点'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">エフェクト</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.effects?.count||0}{metrics?.generationCounts?.effects?.unit||'種'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">BGM</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.music?.count||0}{metrics?.generationCounts?.music?.unit||'曲'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">効果音</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.sfx?.count||0}{metrics?.generationCounts?.sfx?.unit||'個'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">ボイス</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.voice?.count||0}{metrics?.generationCounts?.voice?.unit||'件'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">動画</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.video?.count||0}{metrics?.generationCounts?.video?.unit||'本'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">シナリオ</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.scenarios?.count||0}{metrics?.generationCounts?.scenarios?.unit||'本'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">コード</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.code?.count||0}{metrics?.generationCounts?.code?.unit||'行'}</span>
       </div>
       <div className="flex justify-between">
        <span className="text-nier-text-light">ドキュメント</span>
        <span className="text-nier-text-main">{metrics?.generationCounts?.documents?.count||0}{metrics?.generationCounts?.documents?.unit||'件'}</span>
       </div>
       <div className="flex justify-between pt-1 border-t border-nier-border-light mt-1">
        <span className="text-nier-text-light">ファイル合計</span>
        <span className="text-nier-text-main">{totalAssets}件/{formatSize(totalProjectSize)}</span>
       </div>
      </div>
     </div>

     {/*Operator Panel*/}
     <OperatorPanel/>
    </>
)}
  </div>
)
}
