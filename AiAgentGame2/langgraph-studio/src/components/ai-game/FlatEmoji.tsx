import {
  Smile,
  Meh,
  Frown,
  Moon,
  Flame,
  Sparkles,
  Droplet,
  Music,
  Heart,
  AlertCircle
} from 'lucide-react'
import type { CharacterEmotion } from './types'

interface FlatEmojiProps {
  emotion: CharacterEmotion
  size?: number
  className?: string
}

// 感情に対応するLucideアイコン
const EMOTION_ICONS = {
  idle: Meh,           // 穏やか
  happy: Smile,        // 嬉しい
  working: Flame,      // 集中・作業中
  sleepy: Moon,        // 眠い
  sad: Frown,          // 悲しい
  excited: Sparkles    // 興奮・キラキラ
} as const

// Lucideアイコンを使ったフラット絵文字コンポーネント
export function FlatEmoji({ emotion, size = 20, className = '' }: FlatEmojiProps): JSX.Element {
  const Icon = EMOTION_ICONS[emotion]

  return (
    <Icon
      size={size}
      className={`text-nier-text-main ${className}`}
      strokeWidth={1.5}
    />
  )
}

// 小さなアイコン用
const MINI_ICONS = {
  sparkle: Sparkles,
  sweat: Droplet,
  music: Music,
  heart: Heart,
  exclaim: AlertCircle
} as const

export function MiniIcon({
  type,
  size = 14
}: {
  type: keyof typeof MINI_ICONS
  size?: number
}): JSX.Element {
  const Icon = MINI_ICONS[type]

  return (
    <Icon
      size={size}
      className="text-nier-text-main"
      strokeWidth={1.5}
    />
  )
}
