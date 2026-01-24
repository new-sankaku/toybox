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
 references?:string
 targetAudience?:string
 primaryLanguage?:string
 languages?:string[]
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
 scale?:string
}

export interface CreateProjectInput{
 name:string
 description?:string
 concept:GameConcept
 config?:ProjectConfig
}

export interface GenerationCountItem{
 count:number
 unit:string
 calls?:number
}

export interface GenerationCounts{
 characters?:GenerationCountItem
 backgrounds?:GenerationCountItem
 ui?:GenerationCountItem
 effects?:GenerationCountItem
 music?:GenerationCountItem
 sfx?:GenerationCountItem
 voice?:GenerationCountItem
 video?:GenerationCountItem
 scenarios?:GenerationCountItem
 code?:GenerationCountItem
 documents?:GenerationCountItem
}

export interface ProjectMetrics{
 projectId:string
 totalTokensUsed:number
 totalInputTokens?:number
 totalOutputTokens?:number
 estimatedTotalTokens:number
 tokensByType?:Record<string,{input:number;output:number}>
 generationCounts?:GenerationCounts
 elapsedTimeSeconds:number
 estimatedRemainingSeconds:number
 estimatedEndTime:string|null
 completedTasks:number
 totalTasks:number
 progressPercent:number
 currentPhase:number
 phaseName:string
 activeGenerations?:number
}
