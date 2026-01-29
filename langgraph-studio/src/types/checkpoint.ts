import type{components}from'./api-generated'

export type CheckpointSchema=components['schemas']['CheckpointSchema']
export type CheckpointResolveSchema=components['schemas']['CheckpointResolveSchema']

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
 type:string
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
 type?:string
 format?:string
 documentType?:string
 summary?:string
 content?:string|Record<string,unknown>
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
