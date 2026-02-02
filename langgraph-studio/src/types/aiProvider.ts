export type AIProviderType='claude'|'comfyui'|'tts'|'audiocraft'|'custom'

export interface BaseProviderConfig{
 id:string
 type:AIProviderType
 name:string
 enabled:boolean
 serviceType?:string
 providerId?:string
}

export interface LLMProviderConfig extends BaseProviderConfig{
 type:'claude'
 apiKey:string
 endpoint:string
}

export interface ComfyUIConfig extends BaseProviderConfig{
 type:'comfyui'
 endpoint:string
}

export interface TTSConfig extends BaseProviderConfig{
 type:'tts'
 endpoint:string
}

export interface AudioCraftConfig extends BaseProviderConfig{
 type:'audiocraft'
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
 |TTSConfig
 |AudioCraftConfig
 |CustomProviderConfig
