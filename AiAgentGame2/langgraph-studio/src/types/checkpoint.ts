export type CheckpointStatus = 'pending' | 'approved' | 'rejected' | 'revision_requested'

export type CheckpointType =
  // Phase 1
  | 'concept_review'
  | 'design_review'
  | 'scenario_review'
  | 'character_review'
  | 'world_review'
  | 'task_split_review'
  // Phase 2
  | 'code_review'
  | 'asset_review'
  | 'integration_review'
  // Phase 3
  | 'test_review'
  | 'final_review'
  | 'release_decision'

export interface Checkpoint {
  id: string
  projectId: string
  agentId: string
  type: CheckpointType
  title: string
  description: string | null
  output: CheckpointOutput
  status: CheckpointStatus
  feedback: string | null
  resolvedAt: string | null
  createdAt: string
  updatedAt: string
}

export interface CheckpointOutput {
  documentType?: string
  summary?: string
  content?: Record<string, unknown>
  tokensUsed?: number
  generationTimeMs?: number
  previewUrl?: string
}

export interface CheckpointResolution {
  checkpointId: string
  resolution: 'approved' | 'rejected' | 'revision_requested'
  feedback?: string
}

export interface CheckpointWithMeta extends Checkpoint {
  waitingTimeMinutes: number
  agentName: string
  phaseName: string
}
