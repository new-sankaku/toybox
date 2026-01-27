export type Platform=string
export type Scope=string
export type ProjectScale=string
export type LLMProvider=string

export interface ProjectScaleOption{
 value:ProjectScale
 label:string
 description:string
 estimatedHours:string
}

export interface AssetGenerationOptions {
 enableImageGeneration: boolean
 enableBGMGeneration: boolean
 enableVoiceSynthesis: boolean
 enableVideoGeneration: boolean
}

export interface AssetServiceOption {
 key: keyof AssetGenerationOptions
 label: string
 service: string
}

export type ContentRatingLevel=0|1|2|3|4

export interface ContentPermissions {
 violenceLevel: ContentRatingLevel
 sexualLevel: ContentRatingLevel
}

export interface ContentRatingOption {
 level: ContentRatingLevel
 label: string
 age: string
 description: string
}
