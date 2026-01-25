import{useMemo,useCallback,useState}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Modal}from'@/components/ui/Modal'
import{useProjectStore}from'@/stores/projectStore'
import{useAgentStore}from'@/stores/agentStore'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{AIField2D}from'@/components/ai-game'
import type{CharacterState,AIServiceType,CharacterEmotion}from'@/components/ai-game/types'
import{Pause}from'lucide-react'
import type{AgentType}from'@/types/agent'

const AGENT_SERVICE_MAP:Record<string,AIServiceType>={
 director_phase1:'llm',
 director_phase2:'llm',
 director_phase3:'llm',
 leader_concept:'llm',
 leader_scenario:'llm',
 leader_design:'llm',
 leader_task_split:'llm',
 leader_code:'llm',
 leader_asset:'llm',
 worker_concept:'llm',
 worker_scenario:'llm',
 worker_design:'llm',
 worker_task_split:'llm',
 worker_code:'llm',
 worker_asset:'image',
 concept:'llm',
 task_split_1:'llm',
 concept_detail:'llm',
 scenario:'llm',
 world:'llm',
 character:'llm',
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
 integrator:'llm',
 reviewer:'llm',
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
 const{getLabel}=useAgentDefinitionStore()
 const[selectedCharacter,setSelectedCharacter]=useState<CharacterState|null>(null)

 const currentPhase=useMemo(()=>{
  if(!currentProject)return-1
  const projectAgents=agents.filter(a=>a.projectId===currentProject.id)
  const runningAgent=projectAgents.find(a=>a.status==='running'||a.status==='waiting_approval')
  if(runningAgent&&runningAgent.phase!==undefined)return runningAgent.phase
  const completedAgents=projectAgents.filter(a=>a.status==='completed'&&a.phase!==undefined)
  if(completedAgents.length===0)return 0
  return Math.max(...completedAgents.map(a=>a.phase as number))
 },[agents,currentProject])

 const characters=useMemo(():CharacterState[]=>{
  if(!currentProject)return[]

  const projectAgents=agents.filter(a=>{
   if(a.projectId!==currentProject.id)return false
   if(exitedAgentIds.has(a.id))return false
   if(a.status==='running'||a.status==='waiting_approval')return true
   return false
  }).filter(a=>{
   if(a.phase===undefined)return true
   return a.phase===currentPhase
  })

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
   }else if(isWaitingApproval){
    status='waiting_approval'
    emotion='idle'
   }

   return{
    agentId:agent.id,
    agentType,
    status,
    emotion,
    isActive:isActiveAgent,
    targetService:isRunning?targetService:(isWaitingApproval?targetService:undefined),
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
    position:{x:0,y:0},
    phase:agent.phase
   }
  })
 },[agents,currentProject,exitedAgentIds,currentPhase])

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
     <div className="h-[40vh] min-h-[280px] max-h-[500px] rounded-lg overflow-hidden">
      <AIField2D
       key={currentProject.id}
       characters={characters}
       onCharacterClick={handleCharacterClick}
      />
     </div>
    </CardContent>
   </Card>

   <Modal
    isOpen={!!selectedCharacter}
    onClose={()=>setSelectedCharacter(null)}
    title="エージェント詳細"
    size="md"
   >
    {selectedCharacter&&(
     <div className="space-y-4">
      <div className="flex items-start justify-between">
       <h3 className="text-nier-body font-medium text-nier-text-main">
        {getLabel(selectedCharacter.agentType)}
       </h3>
       <div className="flex gap-2 items-center">
        {selectedCharacter.status==='working'&&(
         <span className="text-nier-small text-nier-accent-orange flex items-center">
          <Pause size={14} className="mr-1 animate-pulse"/>
          処理中...
         </span>
)}
        {selectedCharacter.status==='waiting_approval'&&(
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
      <div className="grid grid-cols-2 gap-4">
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">ステータス</span>
        <span className="text-nier-small text-nier-text-main">
         {selectedCharacter.status==='idle'?'待機中':
          selectedCharacter.status==='working'?'作業中':
           selectedCharacter.status==='waiting_approval'?'承認待ち':
            selectedCharacter.status==='departing'?'移動中':'帰還中'}
        </span>
       </div>
       {selectedCharacter.targetService&&(
        <div>
         <span className="text-nier-caption text-nier-text-light block mb-1">サービス</span>
         <span className="text-nier-small text-nier-text-main">{selectedCharacter.targetService.toUpperCase()}</span>
        </div>
)}
      </div>
      {selectedCharacter.request&&(
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">タスク</span>
        <span className="text-nier-small text-nier-text-main">{selectedCharacter.request.input}</span>
       </div>
)}
     </div>
)}
   </Modal>
  </>
)
}
