import type{AgentType}from'@/types/agent'

export type AIServiceType='llm'|'image'|'audio'|'music'
export type RequestStatus='pending'|'processing'|'completed'|'failed'|'waiting'
export type CharacterEmotion='idle'|'happy'|'working'|'sleepy'|'sad'|'excited'

export interface AIRequest{
 id:string
 serviceType:AIServiceType
 serviceName:string
 agentId:string
 agentType:AgentType
 input:string
 output?:string
 status:RequestStatus
 tokensUsed?:number
 cost?:number
 duration?:number
 createdAt:string
 completedAt?:string
 error?:string
}

export interface CharacterState{
 agentId:string
 agentType:AgentType
 status:'idle'|'departing'|'working'|'returning'|'waiting_approval'|'completed'|'failed'|'blocked'
 emotion:CharacterEmotion
 targetService?:AIServiceType
 request?:AIRequest
 position:{x:number;y:number}
 speechBubble?:string
 isActive?:boolean
 phase?:number
}

export interface ServiceZoneState{
 serviceType:AIServiceType
 serviceName:string
 characters:CharacterState[]
 isActive:boolean
}

const SPIRIT_TYPES=['spirit_fire','spirit_water','spirit_earth','spirit_light','spirit_wind']as const

export const AGENT_MODEL_MAP:Record<AgentType,string>={
 director_phase1:SPIRIT_TYPES[1],
 director_phase2:SPIRIT_TYPES[2],
 director_phase3:SPIRIT_TYPES[3],
 leader_concept:SPIRIT_TYPES[4],
 leader_scenario:SPIRIT_TYPES[0],
 leader_design:SPIRIT_TYPES[1],
 leader_task_split:SPIRIT_TYPES[2],
 leader_code:SPIRIT_TYPES[3],
 leader_asset:SPIRIT_TYPES[4],
 worker_concept:SPIRIT_TYPES[0],
 worker_scenario:SPIRIT_TYPES[1],
 worker_design:SPIRIT_TYPES[2],
 worker_task_split:SPIRIT_TYPES[3],
 worker_code:SPIRIT_TYPES[4],
 worker_asset:SPIRIT_TYPES[0],
 concept:SPIRIT_TYPES[0],
 task_split_1:SPIRIT_TYPES[1],
 concept_detail:SPIRIT_TYPES[2],
 scenario:SPIRIT_TYPES[3],
 world:SPIRIT_TYPES[4],
 character:SPIRIT_TYPES[0],
 game_design:SPIRIT_TYPES[0],
 tech_spec:SPIRIT_TYPES[1],
 task_split_2:SPIRIT_TYPES[2],
 asset_character:SPIRIT_TYPES[3],
 asset_background:SPIRIT_TYPES[4],
 asset_ui:SPIRIT_TYPES[0],
 asset_effect:SPIRIT_TYPES[1],
 asset_bgm:SPIRIT_TYPES[2],
 asset_voice:SPIRIT_TYPES[3],
 asset_sfx:SPIRIT_TYPES[4],
 task_split_3:SPIRIT_TYPES[0],
 code:SPIRIT_TYPES[1],
 event:SPIRIT_TYPES[2],
 ui_integration:SPIRIT_TYPES[3],
 asset_integration:SPIRIT_TYPES[4],
 task_split_4:SPIRIT_TYPES[0],
 unit_test:SPIRIT_TYPES[1],
 integration_test:SPIRIT_TYPES[2],
 integrator:SPIRIT_TYPES[3],
 reviewer:SPIRIT_TYPES[4]
}

export const DEFAULT_SERVICE_CONFIG:Record<AIServiceType,{label:string;description:string}>={
 llm:{label:'LLM',description:'-'},
 image:{label:'画像生成',description:'-'},
 music:{label:'音楽生成',description:'-'},
 audio:{label:'音声生成',description:'-'}
}
