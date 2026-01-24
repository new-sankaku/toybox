export type AIProviderType='claude'|'openai'|'comfyui'|'voicevox'|'suno'|'custom'

export interface BaseProviderConfig{
 id:string
 type:AIProviderType
 name:string
 enabled:boolean
 serviceType?:string
 providerId?:string
}

export interface LLMProviderConfig extends BaseProviderConfig{
 type:'claude'|'openai'
 apiKey:string
 model:string
 endpoint:string
 maxTokens:number
 temperature:number
}

export interface ComfyUIConfig extends BaseProviderConfig{
 type:'comfyui'
 endpoint:string
 workflowFile:string
 outputDir:string
 steps:number
 cfgScale:number
 sampler:string
 scheduler:string
}

export interface VoicevoxConfig extends BaseProviderConfig{
 type:'voicevox'
 endpoint:string
 speakerId:number
 speed:number
}

export interface MusicGeneratorConfig extends BaseProviderConfig{
 type:'suno'
 apiKey:string
 endpoint:string
}

export interface CustomProviderConfig extends BaseProviderConfig{
 type:'custom'
 endpoint:string
 apiKey:string
 settings:Record<string,unknown>
}

export type AIProviderConfig=
 |LLMProviderConfig
 |ComfyUIConfig
 |VoicevoxConfig
 |MusicGeneratorConfig
 |CustomProviderConfig
