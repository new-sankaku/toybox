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
 enableAutoApproval?:boolean
 enableImageGeneration?:boolean
 enableBGMGeneration?:boolean
 enableVoiceSynthesis?:boolean
 enableVideoGeneration?:boolean
 playTime?:'5min'|'15min'|'30min'|'1hour'|'2hour'
 characterCount?:'1-3'|'4-10'|'11+'
 artStyle?:'pixel'|'anime'|'realistic'|'minimal'
 language?:'ja'|'ja-en'|'en'
 allowViolence?:boolean
 allowSexualContent?:boolean
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
