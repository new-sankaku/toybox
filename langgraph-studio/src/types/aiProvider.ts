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
 endpoint:string
}

export interface ComfyUIConfig extends BaseProviderConfig{
 type:'comfyui'
 endpoint:string
}

export interface VoicevoxConfig extends BaseProviderConfig{
 type:'voicevox'
 endpoint:string
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
