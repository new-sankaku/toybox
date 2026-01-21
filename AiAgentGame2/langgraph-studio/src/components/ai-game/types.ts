import type{AgentType}from'@/types/agent'

export type AIServiceType='llm'|'image'|'audio'|'music'
export type RequestStatus='pending'|'processing'|'completed'|'failed'
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
 status:'idle'|'departing'|'working'|'returning'
 emotion:CharacterEmotion
 targetService?:AIServiceType
 request?:AIRequest
 position:{x:number;y:number}
 speechBubble?:string
 isActive?:boolean
}

export interface ServiceZoneState{
 serviceType:AIServiceType
 serviceName:string
 characters:CharacterState[]
 isActive:boolean
}

const SPIRIT_TYPES=['spirit_fire','spirit_water','spirit_earth','spirit_light','spirit_wind']as const

export const AGENT_MODEL_MAP:Record<AgentType,string>={
 concept:SPIRIT_TYPES[0],
 task_split_1:SPIRIT_TYPES[1],
 concept_detail:SPIRIT_TYPES[2],
 scenario:SPIRIT_TYPES[3],
 world:SPIRIT_TYPES[4],
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
 integration_test:SPIRIT_TYPES[2]
}

export const SERVICE_CONFIG:Record<AIServiceType,{label:string;description:string}>={
 llm:{label:'LLM',description:'Claude 3.5 Sonnet'},
 image:{label:'画像生成',description:'DALL-E 3'},
 music:{label:'音楽生成',description:'Suno AI'},
 audio:{label:'音声生成',description:'ElevenLabs'}
}
