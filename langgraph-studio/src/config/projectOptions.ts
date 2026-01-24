/**
 *プロジェクトオプション設定
 *サーバーから取得する設定の型定義
 */

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

export const PROJECT_SCALE_OPTIONS:ProjectScaleOption[]=[
 {value:'small',label:'小規模',description:'個人開発',estimatedHours:'~100時間'},
 {value:'medium',label:'中規模',description:'小チーム開発',estimatedHours:'100~500時間'},
 {value:'large',label:'大規模',description:'フルチーム開発',estimatedHours:'500時間以上'}
]

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

export const ASSET_SERVICE_OPTIONS: AssetServiceOption[]=[
 { key: 'enableImageGeneration',label: '画像生成',service: 'ComfyUI' },
 { key: 'enableBGMGeneration',label: 'BGM/効果音',service: 'Suno AI' },
 { key: 'enableVoiceSynthesis',label: 'ボイス合成',service: 'VOICEVOX' },
 { key: 'enableVideoGeneration',label: '動画生成',service: 'Runway' }
]


export interface ContentPermissions {
 allowViolence: boolean
 allowSexualContent: boolean
}

export interface ContentPermissionOption {
 key: keyof ContentPermissions
 label: string
}

export const CONTENT_PERMISSION_OPTIONS: ContentPermissionOption[]=[
 { key: 'allowViolence',label: '暴力表現を許可' },
 { key: 'allowSexualContent',label: '性表現を許可' }
]


export const PROJECT_DEFAULTS={
 assetGeneration: {
  enableImageGeneration: false,
  enableBGMGeneration: false,
  enableVoiceSynthesis: false,
  enableVideoGeneration: false
 } as AssetGenerationOptions,
 contentPermissions: {
  allowViolence: false,
  allowSexualContent: false
 } as ContentPermissions
}
