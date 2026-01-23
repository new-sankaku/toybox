import{useMemo,useCallback,useState}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentStore}from'@/stores/agentStore'
import{AIField2D}from'@/components/ai-game'
import type{CharacterState,AIServiceType,CharacterEmotion}from'@/components/ai-game/types'
import{getAgentDisplayConfig}from'@/components/ai-game/pixelCharacters'
import{Pause}from'lucide-react'
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

export default function AIFieldSection():JSX.Element|null{
 const{currentProject}=useProjectStore()
 const{agents,exitedAgentIds}=useAgentStore()
 const[selectedCharacter,setSelectedCharacter]=useState<CharacterState|null>(null)

 const characters=useMemo(():CharacterState[]=>{
  if(!currentProject)return[]

  const projectAgents=agents.filter(a=>
   a.projectId===currentProject.id&&!exitedAgentIds.has(a.id)
)

  return projectAgents.map((agent)=>{
   const isRunning=agent.status==='running'
   const isWaitingApproval=agent.status==='waiting_approval'
   const isActiveAgent=isRunning||isWaitingApproval
   const agentType=agent.type as AgentType
   const targetService=AGENT_SERVICE_MAP[agentType]||'llm'

   let status:CharacterState['status']='idle'
   let emotion:CharacterEmotion='idle'

   if(isRunning){
    status='working'
    emotion='working'
   }

   return{
    agentId:agent.id,
    agentType,
    status,
    emotion,
    isActive:isActiveAgent,
    targetService:isRunning?targetService:undefined,
    request:isRunning?{
     id:`req-${agent.id}`,
     serviceType:targetService,
     serviceName:targetService.toUpperCase(),
     agentId:agent.id,
     agentType,
     input:agent.currentTask||'処理中...',
     status:'processing',
     createdAt:agent.startedAt||new Date().toISOString()
    }:(isWaitingApproval?{
     id:`req-${agent.id}`,
     serviceType:targetService,
     serviceName:targetService.toUpperCase(),
     agentId:agent.id,
     agentType,
     input:'承認待ち',
     status:'waiting',
     createdAt:agent.startedAt||new Date().toISOString()
    }:undefined),
    position:{x:0,y:0}
   }
  })
 },[agents,currentProject,exitedAgentIds])

 const handleCharacterClick=useCallback((character:CharacterState)=>{
  setSelectedCharacter(character)
 },[])

 if(!currentProject)return null

 return(
  <>
   <Card>
    <CardHeader>
     <DiamondMarker>エージェント作業場</DiamondMarker>
    </CardHeader>
    <CardContent className="p-0">
     <div className="h-[380px] rounded-lg overflow-hidden">
      <AIField2D
       key={currentProject.id}
       characters={characters}
       onCharacterClick={handleCharacterClick}
      />
     </div>
    </CardContent>
   </Card>

   {selectedCharacter&&(
    <Card className="mt-3">
     <CardContent>
      <div className="flex items-start justify-between">
       <div>
        <h3 className="text-nier-body font-medium text-nier-text-main">
         {getAgentDisplayConfig(selectedCharacter.agentType).label}
        </h3>
        <p className="text-nier-small text-nier-text-light mt-1">
         ステータス: {selectedCharacter.status==='idle'?'待機中':
          selectedCharacter.status==='working'?'作業中':
           selectedCharacter.status==='departing'?'移動中':'帰還中'}
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
        {selectedCharacter.status==='idle'&&selectedCharacter.request?.status==='waiting'&&(
         <span className="text-nier-small text-nier-accent-orange">
          承認待ち
         </span>
)}
        {selectedCharacter.status==='idle'&&!selectedCharacter.request&&(
         <span className="text-nier-small text-nier-text-light">
          待機中
         </span>
)}
       </div>
      </div>
     </CardContent>
    </Card>
)}
  </>
)
}
