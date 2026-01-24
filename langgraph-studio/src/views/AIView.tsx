import{useState,useMemo,useCallback}from'react'
import{Card,CardContent}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentStore}from'@/stores/agentStore'
import{AIField2D}from'@/components/ai-game'
import type{CharacterState,AIServiceType,AIRequest,CharacterEmotion}from'@/components/ai-game/types'
import{FolderOpen,Pause}from'lucide-react'
import{Button}from'@/components/ui/Button'
import type{AgentType}from'@/types/agent'

const AGENT_SERVICE_MAP:Record<AgentType,AIServiceType>={
 concept:'llm',
 task_split_1:'llm',
 concept_detail:'llm',
 scenario:'llm',
 world:'llm',
 game_design:'llm',
 tech_spec:'llm',
 task_split_2:'llm',
 task_split_3:'llm',
 task_split_4:'llm',
 code:'llm',
 event:'llm',
 ui_integration:'llm',
 asset_integration:'llm',
 unit_test:'llm',
 integration_test:'llm',
 asset_character:'image',
 asset_background:'image',
 asset_ui:'image',
 asset_effect:'image',
 asset_bgm:'music',
 asset_voice:'audio',
 asset_sfx:'audio'
}

export default function AIView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{agents}=useAgentStore()
 const[selectedCharacter,setSelectedCharacter]=useState<CharacterState|null>(null)

 const projectAgents=useMemo(()=>{
  if(!currentProject)return[]
  return agents.filter(a=>a.projectId===currentProject.id)
 },[agents,currentProject?.id])

 const characters=useMemo(():CharacterState[]=>{
  return projectAgents.map((agent)=>{
   const agentType=agent.type as AgentType
   const serviceType=AGENT_SERVICE_MAP[agentType]||'llm'

   let status:CharacterState['status']='idle'
   let emotion:CharacterEmotion='idle'
   let targetService:AIServiceType|undefined=undefined

   if(agent.status==='running'){
    status='working'
    emotion='working'
    targetService=serviceType
   }else if(agent.status==='completed'){
    emotion='happy'
   }else if(agent.status==='failed'){
    emotion='sad'
   }

   const request:AIRequest|undefined=agent.status==='running'?{
    id:`req-${agent.id}`,
    serviceType,
    serviceName:serviceType.toUpperCase(),
    agentId:agent.id,
    agentType,
    input:agent.currentTask||'処理中',
    status:'processing',
    createdAt:agent.startedAt||new Date().toISOString()
   }:undefined

   return{
    agentId:agent.id,
    agentType,
    status,
    emotion,
    targetService,
    request,
    position:{x:0,y:0}
   }
  })
 },[projectAgents])

 const handleCharacterClick=useCallback((character:CharacterState)=>{
  setSelectedCharacter(character)
 },[])

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <div className="nier-page-header-row">
     <div className="nier-page-header-left">
      <h1 className="nier-page-title">AI</h1>
      <span className="nier-page-subtitle">-外部AI連携</span>
     </div>
     <div className="nier-page-header-right"/>
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

 return(
  <div className="p-4 animate-nier-fade-in">
   <div className="nier-page-header-row">
    <div className="nier-page-header-left">
     <h1 className="nier-page-title">AI</h1>
     <span className="nier-page-subtitle">-外部AI連携</span>
    </div>
    <div className="nier-page-header-right"/>
   </div>

   <Card className="mb-4">
    <CardContent className="p-0">
     <div className="h-[500px] rounded-lg overflow-hidden">
      <AIField2D
       characters={characters}
       onCharacterClick={handleCharacterClick}
      />
     </div>
    </CardContent>
   </Card>

   {selectedCharacter&&(
    <Card className="mt-4">
     <CardContent>
      <div className="flex items-start justify-between">
       <div>
        <h3 className="text-nier-body font-medium text-nier-text-main">
         {selectedCharacter.agentType.toUpperCase().replace(/_/g,' ')}
        </h3>
        <p className="text-nier-small text-nier-text-light mt-1">
         ステータス: {selectedCharacter.status==='idle'?'待機中' :
          selectedCharacter.status==='working'?'作業中' :
           selectedCharacter.status==='departing'?'移動中' : '帰還中'}
        </p>
        {selectedCharacter.targetService&&(
         <p className="text-nier-small text-nier-text-light">
          サービス: {selectedCharacter.targetService.toUpperCase()}
         </p>
)}
        {selectedCharacter.request&&(
         <p className="text-nier-small text-nier-text-light mt-1 truncate max-w-md">
          タスク: {selectedCharacter.request.input}
         </p>
)}
       </div>
       <div className="flex gap-2 items-center">
        {selectedCharacter.status==='working'&&(
         <span className="text-nier-small text-nier-accent-orange flex items-center">
          <Pause size={14} className="mr-1 animate-pulse"/>
          処理中...
         </span>
)}
        {selectedCharacter.status==='idle'&&(
         <span className="text-nier-small text-nier-text-light">
          待機中
         </span>
)}
        <Button
         size="sm"
         variant="ghost"
         onClick={()=>setSelectedCharacter(null)}
        >
         閉じる
        </Button>
       </div>
      </div>
     </CardContent>
    </Card>
)}
  </div>
)
}
