export type CheckpointStatus='pending'|'approved'|'rejected'|'revision_requested'

export type CheckpointType=
 |'concept_review'
 |'concept_detail_review'
 |'design_review'
 |'scenario_review'
 |'character_review'
 |'world_review'
 |'game_design_review'
 |'tech_spec_review'
 |'task_review_1'
 |'task_review_2'
 |'task_review_3'
 |'task_review_4'
 |'task_split_review'
 |'code_review'
 |'ui_review'
 |'ui_integration_review'
 |'asset_review'
 |'integration_review'
 |'unit_test_review'
 |'integration_test_review'
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
