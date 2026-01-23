export type ProjectStatus='draft'|'running'|'paused'|'completed'|'failed'

export type PhaseNumber=1|2|3

export interface Project{
 id:string
 name:string
 description?:string
 concept?:GameConcept
 status:ProjectStatus
 currentPhase:PhaseNumber
 state?:Record<string,unknown>
 config?:ProjectConfig
 createdAt:string
 updatedAt:string
}

export interface GameConcept{
 description:string
 platform:'web'|'desktop'|'mobile'
 scope:'mvp'|'full'
 genre?:string
 targetAudience?:string
}

export interface ProjectConfig{
 llmProvider?:'claude'|'gpt4'|'mock'
 maxTokensPerAgent?:number
 enableAssetGeneration?:boolean
 enableAutoApproval?:boolean
}

export interface CreateProjectInput{
 name:string
 description?:string
 concept:GameConcept
 config?:ProjectConfig
}

export interface ProjectMetrics{
 projectId:string
 totalTokensUsed:number
 estimatedTotalTokens:number
 elapsedTimeSeconds:number
 estimatedRemainingSeconds:number
 estimatedEndTime:string|null
 completedTasks:number
 totalTasks:number
 progressPercent:number
 currentPhase:PhaseNumber
 phaseName:string
}
