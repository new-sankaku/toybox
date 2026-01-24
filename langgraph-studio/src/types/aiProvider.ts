export type AIProviderType='claude'|'openai'|'comfyui'|'voicevox'|'suno'|'custom'

export interface BaseProviderConfig{
 id:string
 type:AIProviderType
 name:string
 enabled:boolean
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

export const PROVIDER_TYPE_LABELS:Record<AIProviderType,string>={
 claude:'Claude',
 openai:'OpenAI',
 comfyui:'ComfyUI',
 voicevox:'VOICEVOX',
 suno:'Suno AI',
 custom:'カスタム'
}

export type AIServiceCategory='llm'|'image'|'voice'|'music'

export const SERVICE_CATEGORIES:Record<AIServiceCategory,{label:string,types:AIProviderType[]}>={
 llm:{label:'LLM（テキスト生成）',types:['claude','openai']},
 image:{label:'画像生成',types:['comfyui']},
 voice:{label:'音声合成',types:['voicevox']},
 music:{label:'音楽生成',types:['suno']}
}

export const getServiceCategory=(type:AIProviderType):AIServiceCategory|null=>{
 for(const[cat,info]of Object.entries(SERVICE_CATEGORIES)){
  if(info.types.includes(type))return cat as AIServiceCategory
 }
 return null
}

export const DEFAULT_LLM_CONFIG:Omit<LLMProviderConfig,'id'|'name'>={
 type:'claude',
 enabled:false,
 apiKey:'',
 model:'claude-sonnet-4-20250514',
 endpoint:'https://api.anthropic.com',
 maxTokens:4096,
 temperature:0.7
}

export const DEFAULT_COMFYUI_CONFIG:Omit<ComfyUIConfig,'id'|'name'>={
 type:'comfyui',
 enabled:false,
 endpoint:'http://localhost:8188',
 workflowFile:'default.json',
 outputDir:'./outputs',
 steps:20,
 cfgScale:7.0,
 sampler:'euler_ancestral',
 scheduler:'normal'
}

export const DEFAULT_VOICEVOX_CONFIG:Omit<VoicevoxConfig,'id'|'name'>={
 type:'voicevox',
 enabled:false,
 endpoint:'http://localhost:50021',
 speakerId:1,
 speed:1.0
}

export const DEFAULT_SUNO_CONFIG:Omit<MusicGeneratorConfig,'id'|'name'>={
 type:'suno',
 enabled:false,
 apiKey:'',
 endpoint:'https://api.suno.ai'
}
