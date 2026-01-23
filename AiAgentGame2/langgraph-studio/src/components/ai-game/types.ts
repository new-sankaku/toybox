import type{AgentType}from'@/types/agent'

export type AIServiceType='llm'|'image'|'audio'|'music'

// Agent階層定義
export type AgentHierarchyLevel='orchestrator'|'division'|'worker'

export interface AgentHierarchyConfig{
 level:AgentHierarchyLevel
 parent?:AgentType
 label:string
 groupLabel?:string
}

// オーケストラ（大区分）: concept
// 中区分: task_split_1, task_split_2, task_split_3, task_split_4
// 小区分: それぞれのtask_splitに属するworker agents
export const AGENT_HIERARCHY:Record<AgentType,AgentHierarchyConfig>={
 concept:{level:'orchestrator',label:'オーケストラ'},
 task_split_1:{level:'division',parent:'concept',label:'設計分配',groupLabel:'設計'},
 task_split_2:{level:'division',parent:'concept',label:'アセット分配',groupLabel:'アセット'},
 task_split_3:{level:'division',parent:'concept',label:'実装分配',groupLabel:'実装'},
 task_split_4:{level:'division',parent:'concept',label:'テスト分配',groupLabel:'テスト'},
 concept_detail:{level:'worker',parent:'task_split_1',label:'企画'},
 scenario:{level:'worker',parent:'task_split_1',label:'シナリオ'},
 world:{level:'worker',parent:'task_split_1',label:'世界観'},
 game_design:{level:'worker',parent:'task_split_1',label:'デザイン'},
 tech_spec:{level:'worker',parent:'task_split_1',label:'テック'},
 asset_character:{level:'worker',parent:'task_split_2',label:'キャラ'},
 asset_background:{level:'worker',parent:'task_split_2',label:'背景'},
 asset_ui:{level:'worker',parent:'task_split_2',label:'UI'},
 asset_effect:{level:'worker',parent:'task_split_2',label:'エフェクト'},
 asset_bgm:{level:'worker',parent:'task_split_2',label:'BGM'},
 asset_voice:{level:'worker',parent:'task_split_2',label:'ボイス'},
 asset_sfx:{level:'worker',parent:'task_split_2',label:'効果音'},
 code:{level:'worker',parent:'task_split_3',label:'コード'},
 event:{level:'worker',parent:'task_split_3',label:'イベント'},
 ui_integration:{level:'worker',parent:'task_split_3',label:'UI統合'},
 asset_integration:{level:'worker',parent:'task_split_3',label:'統合'},
 unit_test:{level:'worker',parent:'task_split_4',label:'テスト1'},
 integration_test:{level:'worker',parent:'task_split_4',label:'テスト2'}
}

// 中区分Agentとその子Agentのグループ化
export const DIVISION_AGENTS:AgentType[]=['task_split_1','task_split_2','task_split_3','task_split_4']

export function getAgentsByDivision(division:AgentType):AgentType[]{
 return(Object.entries(AGENT_HIERARCHY)as[AgentType,AgentHierarchyConfig][])
  .filter(([_,config])=>config.parent===division&&config.level==='worker')
  .map(([type])=>type)
}

export function getAgentLevel(agentType:AgentType):AgentHierarchyLevel{
 return AGENT_HIERARCHY[agentType]?.level||'worker'
}

export function getAgentParent(agentType:AgentType):AgentType|undefined{
 return AGENT_HIERARCHY[agentType]?.parent
}
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
