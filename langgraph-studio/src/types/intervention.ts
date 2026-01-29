import type{components}from'./api-generated'

export type InterventionSchema=components['schemas']['InterventionSchema']

export type InterventionPriority='normal'|'urgent'

export type InterventionTarget='all'|'specific'

export type InterventionStatus='pending'|'delivered'|'acknowledged'|'processed'|'waiting_response'

export interface InterventionResponse{
 sender:'agent'|'operator'
 agentId:string|null
 message:string
 createdAt:string
}

export interface Intervention{
 id:string
 projectId:string
 targetType:InterventionTarget
 targetAgentId:string|null
 priority:InterventionPriority
 message:string
 attachedFileIds:string[]
 status:InterventionStatus
 responses:InterventionResponse[]
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
