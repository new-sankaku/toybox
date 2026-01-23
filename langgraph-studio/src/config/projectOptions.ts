/**
 * プロジェクトオプション設定
 * バックエンドの project_options.json と同期して使用
 * 将来的にはAPIから取得することを推奨
 */

export type Platform = 'web-canvas' | 'web-dom' | 'electron'
export type Scope = 'prototype' | 'demo' | 'standard' | 'full'
export type LLMProvider = 'claude' | 'gpt4'
export type PlayTime = '5min' | '15min' | '30min' | '1hour' | '2hour'
export type CharacterCount = '1-3' | '4-10' | '11+'
export type ArtStyle = 'pixel' | 'anime' | 'realistic' | 'minimal'
export type GameLanguage = 'ja' | 'ja-en' | 'en'

export interface PlatformOption {
  value: Platform
  label: string
  description: string
}

export interface ScopeOption {
  value: Scope
  label: string
  description: string
}

export interface LLMProviderOption {
  value: LLMProvider
  label: string
  recommended?: boolean
}

export interface ProjectTemplateOption {
  value: string
  label: string
}

export interface PlayTimeOption {
  value: PlayTime
  label: string
}

export interface CharacterCountOption {
  value: CharacterCount
  label: string
}

export interface ArtStyleOption {
  value: ArtStyle
  label: string
  description: string
}

export interface GameLanguageOption {
  value: GameLanguage
  label: string
}

// プラットフォーム選択肢
export const PLATFORM_OPTIONS: PlatformOption[] = [
  {
    value: 'web-canvas',
    label: 'ブラウザゲーム (Canvas)',
    description: '2D/3Dゲーム、HTML5 Canvas+JavaScript'
  },
  {
    value: 'web-dom',
    label: 'ブラウザゲーム (DOM)',
    description: 'テキストベース、カードゲーム、HTML+CSS+JavaScript'
  },
  {
    value: 'electron',
    label: 'デスクトップアプリ',
    description: 'Win/Mac/Linux対応、Electron+JavaScript'
  }
]

// スコープ選択肢
export const SCOPE_OPTIONS: ScopeOption[] = [
  {
    value: 'prototype',
    label: 'プロトタイプ',
    description: '動作確認用の最小実装'
  },
  {
    value: 'demo',
    label: 'デモ版',
    description: '見せられるレベルの完成度'
  },
  {
    value: 'standard',
    label: 'スタンダード',
    description: '完全な1本のゲーム'
  },
  {
    value: 'full',
    label: 'フル版',
    description: '商用レベルの完成度'
  }
]

// LLMプロバイダー選択肢
export const LLM_PROVIDER_OPTIONS: LLMProviderOption[] = [
  {
    value: 'claude',
    label: 'Claude (推奨)',
    recommended: true
  },
  {
    value: 'gpt4',
    label: 'GPT-4'
  }
]

// プロジェクトテンプレート選択肢
export const PROJECT_TEMPLATE_OPTIONS: ProjectTemplateOption[] = [
  { value: 'rpg', label: 'RPG (ロールプレイングゲーム)' },
  { value: 'action', label: 'アクションゲーム' },
  { value: 'adventure', label: 'アドベンチャーゲーム' },
  { value: 'puzzle', label: 'パズルゲーム' },
  { value: 'simulation', label: 'シミュレーションゲーム' },
  { value: 'custom', label: 'カスタム' }
]

// プレイ時間選択肢
export const PLAY_TIME_OPTIONS: PlayTimeOption[] = [
  { value: '5min', label: '5分' },
  { value: '15min', label: '15分' },
  { value: '30min', label: '30分' },
  { value: '1hour', label: '1時間' },
  { value: '2hour', label: '2時間' }
]

// キャラクター数選択肢
export const CHARACTER_COUNT_OPTIONS: CharacterCountOption[] = [
  { value: '1-3', label: '1〜3体' },
  { value: '4-10', label: '4〜10体' },
  { value: '11+', label: '11体以上' }
]

// アートスタイル選択肢
export const ART_STYLE_OPTIONS: ArtStyleOption[] = [
  { value: 'pixel', label: 'ピクセルアート', description: 'ドット絵スタイル' },
  { value: 'anime', label: 'アニメ調', description: '日本アニメ風' },
  { value: 'realistic', label: 'リアル調', description: '写実的なスタイル' },
  { value: 'minimal', label: 'ミニマル', description: 'シンプルな図形' }
]

// 言語選択肢
export const GAME_LANGUAGE_OPTIONS: GameLanguageOption[] = [
  { value: 'ja', label: '日本語のみ' },
  { value: 'ja-en', label: '日英両対応' },
  { value: 'en', label: '英語のみ' }
]

// デフォルト値
export const PROJECT_DEFAULTS = {
  platform: 'web-canvas' as Platform,
  scope: 'demo' as Scope,
  llmProvider: 'claude' as LLMProvider,
  projectTemplate: 'rpg',
  playTime: '15min' as PlayTime,
  characterCount: '1-3' as CharacterCount,
  artStyle: 'pixel' as ArtStyle,
  language: 'ja' as GameLanguage,
  enableImageGeneration: false,
  enableBGMGeneration: false,
  enableVoiceSynthesis: false,
  enableVideoGeneration: false,
  allowViolence: false,
  allowSexualContent: false
}
