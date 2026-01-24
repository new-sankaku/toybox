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
 platform:string
 scope:string
 genre?:string
 targetAudience?:string
}

export interface AssetGenerationConfig {
 enableImageGeneration?:boolean
 enableBGMGeneration?:boolean
 enableVoiceSynthesis?:boolean
 enableVideoGeneration?:boolean
}

export interface ContentPermissionsConfig {
 allowViolence?:boolean
 allowSexualContent?:boolean
}

export interface ProjectConfig{
 llmProvider?:string
 maxTokensPerAgent?:number
 enableAssetGeneration?:boolean
 assetGeneration?:AssetGenerationConfig
 contentPermissions?:ContentPermissionsConfig
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
