export type AIProviderType='claude'|'openai'|'comfyui'|'voicevox'|'suno'|'video'|'custom'

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

export interface VideoGeneratorConfig extends BaseProviderConfig{
 type:'video'
 apiKey:string
 endpoint:string
 model:'runway'|'pika'|'stablevideo'
 resolution:'720p'|'1080p'
 fps:number
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
 |VideoGeneratorConfig
 |CustomProviderConfig

export const PROVIDER_TYPE_LABELS:Record<AIProviderType,string>={
 claude:'Claude',
 openai:'OpenAI',
 comfyui:'ComfyUI',
 voicevox:'VOICEVOX',
 suno:'Suno AI',
 video:'動画生成',
 custom:'カスタム'
}

export const VIDEO_MODELS=[
 {id:'runway',label:'Runway Gen-3'},
 {id:'pika',label:'Pika Labs'},
 {id:'stablevideo',label:'Stable Video Diffusion'},
]

export const VIDEO_RESOLUTIONS=[
 {id:'720p',label:'720p (HD)'},
 {id:'1080p',label:'1080p (Full HD)'},
]

export const CLAUDE_MODELS=[
 {id:'claude-sonnet-4-20250514',label:'Claude Sonnet 4'},
 {id:'claude-opus-4-20250514',label:'Claude Opus 4'},
 {id:'claude-3-5-sonnet-20241022',label:'Claude 3.5 Sonnet'},
 {id:'claude-3-5-haiku-20241022',label:'Claude 3.5 Haiku'},
]

export const OPENAI_MODELS=[
 {id:'gpt-4o',label:'GPT-4o'},
 {id:'gpt-4-turbo',label:'GPT-4 Turbo'},
 {id:'gpt-4',label:'GPT-4'},
 {id:'gpt-3.5-turbo',label:'GPT-3.5 Turbo'},
]

export const COMFYUI_SAMPLERS=[
 'euler','euler_ancestral','heun','dpm_2','dpm_2_ancestral',
 'lms','dpm_fast','dpm_adaptive','dpmpp_2s_ancestral','dpmpp_sde',
 'dpmpp_2m','dpmpp_2m_sde','ddim','uni_pc'
]

export const COMFYUI_SCHEDULERS=[
 'normal','karras','exponential','sgm_uniform','simple','ddim_uniform'
]

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

export const DEFAULT_VIDEO_CONFIG:Omit<VideoGeneratorConfig,'id'|'name'>={
 type:'video',
 enabled:false,
 apiKey:'',
 endpoint:'https://api.runwayml.com',
 model:'runway',
 resolution:'1080p',
 fps:24
}
