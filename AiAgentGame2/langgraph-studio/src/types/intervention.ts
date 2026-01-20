export type InterventionPriority='normal'|'urgent'

export type InterventionTarget='all'|'specific'

export type InterventionStatus='pending'|'delivered'|'acknowledged'|'processed'

export interface Intervention{
 id:string
 projectId:string
 targetType:InterventionTarget
 targetAgentId:string|null
 priority:InterventionPriority
 message:string
 attachedFileIds:string[]
 status:InterventionStatus
 createdAt:string
 deliveredAt:string|null
 acknowledgedAt:string|null
 processedAt:string|null
}

export interface CreateInterventionInput{
 projectId:string
 targetType:InterventionTarget
 targetAgentId?:string
 priority:InterventionPriority
 message:string
 attachedFileIds?:string[]
}

export interface InterventionWithMeta extends Intervention{
 targetAgentName:string|null
 deliveryTimeSeconds:number|null
}
