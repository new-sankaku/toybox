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

export const VIOLENCE_RATING_OPTIONS: ContentRatingOption[]=[
 {level:0,label:'なし',age:'全年齢',description:'暴力表現を含まない'},
 {level:1,label:'軽度',age:'12+',description:'軽い衝突、コミカルな表現'},
 {level:2,label:'中程度',age:'15+',description:'戦闘シーン、軽度の流血'},
 {level:3,label:'強め',age:'17+',description:'リアルな戦闘、負傷表現'},
 {level:4,label:'過激',age:'18+',description:'グロテスク、残虐表現'}
]

export const SEXUAL_RATING_OPTIONS: ContentRatingOption[]=[
 {level:0,label:'なし',age:'全年齢',description:'性的表現を含まない'},
 {level:1,label:'軽度',age:'12+',description:'軽いロマンス、着衣'},
 {level:2,label:'中程度',age:'15+',description:'キスシーン、水着'},
 {level:3,label:'強め',age:'17+',description:'セクシー表現、露出'},
 {level:4,label:'過激',age:'18+',description:'成人向け表現'}
]

export const PROJECT_DEFAULTS={
 assetGeneration: {
  enableImageGeneration: false,
  enableBGMGeneration: false,
  enableVoiceSynthesis: false,
  enableVideoGeneration: false
 } as AssetGenerationOptions,
 contentPermissions: {
  violenceLevel: 0,
  sexualLevel: 0
 } as ContentPermissions
}
