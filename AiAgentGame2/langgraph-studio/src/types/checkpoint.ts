export type CheckpointStatus='pending'|'approved'|'rejected'|'revision_requested'

export type CheckpointType=
 |'concept_review'
 |'design_review'
 |'scenario_review'
 |'character_review'
 |'world_review'
 |'task_split_review'
 |'code_review'
 |'asset_review'
 |'integration_review'
 |'test_review'
 |'final_review'
 |'release_decision'

export interface Checkpoint{
 id:string
 projectId:string
 agentId:string
 type:CheckpointType
 title:string
 description:string|null
 output:CheckpointOutput
 status:CheckpointStatus
 feedback:string|null
 resolvedAt:string|null
 createdAt:string
 updatedAt:string
}

export interface CheckpointOutput{
 type?:string           // バックエンド: "document", "code", etc.
 format?:string         // バックエンド: "markdown", "json", etc.
 documentType?:string   // 互換性のため残す
 summary?:string
 content?:string|Record<string,unknown>// 文字列またはオブジェクト
 tokensUsed?:number
 generationTimeMs?:number
 previewUrl?:string
}

export interface CheckpointResolution{
 checkpointId:string
 resolution:'approved'|'rejected'|'revision_requested'
 feedback?:string
}

export interface CheckpointWithMeta extends Checkpoint{
 waitingTimeMinutes:number
 agentName:string
 phaseName:string
}
