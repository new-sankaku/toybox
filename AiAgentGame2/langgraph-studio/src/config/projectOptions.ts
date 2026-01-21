/**
 * プロジェクトオプション設定
 * バックエンドの project_options.json と同期して使用
 * 将来的にはAPIから取得することを推奨
 */

export type Platform = 'web-canvas' | 'web-dom' | 'electron'
export type Scope = 'prototype' | 'demo' | 'standard' | 'full'
export type LLMProvider = 'claude' | 'gpt4'

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

// デフォルト値
export const PROJECT_DEFAULTS = {
  platform: 'web-canvas' as Platform,
  scope: 'demo' as Scope,
  llmProvider: 'claude' as LLMProvider,
  projectTemplate: 'rpg'
}
