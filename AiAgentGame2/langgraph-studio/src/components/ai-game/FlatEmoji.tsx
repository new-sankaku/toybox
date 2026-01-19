import twemoji from '@twemoji/api'
import { useEffect, useRef } from 'react'
import type { CharacterEmotion } from './types'

interface FlatEmojiProps {
  emotion: CharacterEmotion
  size?: number
  className?: string
}

// 感情に対応するUnicode絵文字
const EMOTION_EMOJI: Record<CharacterEmotion, string> = {
  idle: '😌',      // 穏やか
  happy: '😊',     // 嬉しい
  working: '🔥',   // 集中・作業中
  sleepy: '😴',    // 眠い
  sad: '😢',       // 悲しい
  excited: '✨'    // 興奮・キラキラ
}

// Twemojiを使ったフラット絵文字コンポーネント
export function FlatEmoji({ emotion, size = 20, className = '' }: FlatEmojiProps): JSX.Element {
  const containerRef = useRef<HTMLSpanElement>(null)
  const emoji = EMOTION_EMOJI[emotion]

  useEffect(() => {
    if (containerRef.current) {
      // Twemojiで絵文字をSVGに変換
      twemoji.parse(containerRef.current, {
        folder: 'svg',
        ext: '.svg',
        className: 'twemoji-icon'
      })
    }
  }, [emoji])

  return (
    <span
      ref={containerRef}
      className={`inline-flex items-center justify-center ${className}`}
      style={{
        width: size,
        height: size,
        fontSize: size * 0.8
      }}
    >
      {emoji}
      <style>{`
        .twemoji-icon {
          width: ${size}px;
          height: ${size}px;
          vertical-align: middle;
        }
      `}</style>
    </span>
  )
}

// 小さなアイコン用のミニ絵文字
const MINI_ICONS: Record<string, string> = {
  sparkle: '✨',
  sweat: '💧',
  music: '🎵',
  heart: '❤️',
  exclaim: '❗'
}

export function MiniIcon({ type, size = 14 }: { type: keyof typeof MINI_ICONS; size?: number }): JSX.Element {
  const containerRef = useRef<HTMLSpanElement>(null)
  const emoji = MINI_ICONS[type] || '❓'

  useEffect(() => {
    if (containerRef.current) {
      twemoji.parse(containerRef.current, {
        folder: 'svg',
        ext: '.svg',
        className: 'twemoji-mini'
      })
    }
  }, [emoji])

  return (
    <span
      ref={containerRef}
      className="inline-flex items-center justify-center"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.8
      }}
    >
      {emoji}
      <style>{`
        .twemoji-mini {
          width: ${size}px;
          height: ${size}px;
          vertical-align: middle;
        }
      `}</style>
    </span>
  )
}
