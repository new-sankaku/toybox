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

// エージェントタイプと3Dモデルのマッピング
export const AGENT_MODEL_MAP: Record<AgentType, string> = {
  // Phase 0: 企画
  concept: 'cube_robot',
  // Phase 1: タスク分割1
  task_split_1: 'spider_robot',
  // Phase 2: 設計
  concept_detail: 'antenna_robot',
  scenario: 'animal_cat',
  world: 'animal_bird',
  game_design: 'tank_robot',
  tech_spec: 'submarine_robot',
  // Phase 3: タスク分割2 + アセット
  task_split_2: 'spider_robot',
  asset_character: 'spirit_fire',
  asset_background: 'spirit_earth',
  asset_ui: 'spirit_light',
  asset_effect: 'spirit_water',
  asset_bgm: 'spirit_wind',
  asset_voice: 'animal_dog',
  asset_sfx: 'drum_robot',
  // Phase 4: タスク分割3 + 実装
  task_split_3: 'spider_robot',
  code: 'hover_robot',
  event: 'train_robot',
  ui_integration: 'plane_robot',
  asset_integration: 'helicopter_robot',
  // Phase 5: タスク分割4 + テスト
  task_split_4: 'spider_robot',
  unit_test: 'animal_rabbit',
  integration_test: 'animal_bear'
}

// サービスタイプの設定
export const SERVICE_CONFIG: Record<AIServiceType, { label: string; description: string }> = {
  llm: { label: 'LLM', description: 'Claude 3.5 Sonnet' },
  image: { label: '画像生成', description: 'DALL-E 3' },
  music: { label: '音楽生成', description: 'Suno AI' },
  audio: { label: '音声生成', description: 'ElevenLabs' }
}
