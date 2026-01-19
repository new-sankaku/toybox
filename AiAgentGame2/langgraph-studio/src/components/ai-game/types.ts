import type { AgentType } from '@/types/agent'

export type AIServiceType = 'llm' | 'image' | 'audio' | 'music'
export type RequestStatus = 'pending' | 'processing' | 'completed' | 'failed'
export type CharacterEmotion = 'idle' | 'happy' | 'working' | 'sleepy' | 'sad' | 'excited'

export interface AIRequest {
  id: string
  serviceType: AIServiceType
  serviceName: string
  agentId: string
  agentType: AgentType
  input: string
  output?: string
  status: RequestStatus
  tokensUsed?: number
  cost?: number
  duration?: number
  createdAt: string
  completedAt?: string
  error?: string
}

export interface CharacterState {
  agentId: string
  agentType: AgentType
  status: 'idle' | 'departing' | 'working' | 'returning'
  emotion: CharacterEmotion
  targetService?: AIServiceType
  request?: AIRequest
  position: { x: number; y: number }
  speechBubble?: string
}

export interface ServiceZoneState {
  serviceType: AIServiceType
  serviceName: string
  characters: CharacterState[]
  isActive: boolean
}

// 精霊の種類（5種類をローテーション）
const SPIRIT_TYPES = ['spirit_fire', 'spirit_water', 'spirit_earth', 'spirit_light', 'spirit_wind'] as const

// エージェントタイプと3Dモデルのマッピング（全て精霊モデルを使用）
export const AGENT_MODEL_MAP: Record<AgentType, string> = {
  // Phase 0: 企画
  concept: SPIRIT_TYPES[0],           // spirit_fire
  // Phase 1: タスク分割1
  task_split_1: SPIRIT_TYPES[1],      // spirit_water
  // Phase 2: 設計
  concept_detail: SPIRIT_TYPES[2],    // spirit_earth
  scenario: SPIRIT_TYPES[3],          // spirit_light
  world: SPIRIT_TYPES[4],             // spirit_wind
  game_design: SPIRIT_TYPES[0],       // spirit_fire
  tech_spec: SPIRIT_TYPES[1],         // spirit_water
  // Phase 3: タスク分割2 + アセット
  task_split_2: SPIRIT_TYPES[2],      // spirit_earth
  asset_character: SPIRIT_TYPES[3],   // spirit_light
  asset_background: SPIRIT_TYPES[4],  // spirit_wind
  asset_ui: SPIRIT_TYPES[0],          // spirit_fire
  asset_effect: SPIRIT_TYPES[1],      // spirit_water
  asset_bgm: SPIRIT_TYPES[2],         // spirit_earth
  asset_voice: SPIRIT_TYPES[3],       // spirit_light
  asset_sfx: SPIRIT_TYPES[4],         // spirit_wind
  // Phase 4: タスク分割3 + 実装
  task_split_3: SPIRIT_TYPES[0],      // spirit_fire
  code: SPIRIT_TYPES[1],              // spirit_water
  event: SPIRIT_TYPES[2],             // spirit_earth
  ui_integration: SPIRIT_TYPES[3],    // spirit_light
  asset_integration: SPIRIT_TYPES[4], // spirit_wind
  // Phase 5: タスク分割4 + テスト
  task_split_4: SPIRIT_TYPES[0],      // spirit_fire
  unit_test: SPIRIT_TYPES[1],         // spirit_water
  integration_test: SPIRIT_TYPES[2]   // spirit_earth
}

// サービスタイプの設定
export const SERVICE_CONFIG: Record<AIServiceType, { label: string; description: string }> = {
  llm: { label: 'LLM', description: 'Claude 3.5 Sonnet' },
  image: { label: '画像生成', description: 'DALL-E 3' },
  music: { label: '音楽生成', description: 'Suno AI' },
  audio: { label: '音声生成', description: 'ElevenLabs' }
}
