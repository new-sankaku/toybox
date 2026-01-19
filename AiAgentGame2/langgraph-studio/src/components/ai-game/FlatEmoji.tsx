import type { CharacterEmotion } from './types'

interface FlatEmojiProps {
  emotion: CharacterEmotion
  size?: number
  className?: string
}

// NieRテーマのフラットな絵文字（SVGアイコン）
export function FlatEmoji({ emotion, size = 20, className = '' }: FlatEmojiProps): JSX.Element {
  const strokeColor = '#454138'
  const strokeWidth = 1.5

  const renderEmoji = () => {
    switch (emotion) {
      case 'idle':
        // 穏やかな顔（- -）
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
            <circle cx="12" cy="12" r="10" stroke={strokeColor} strokeWidth={strokeWidth} fill="none" />
            <line x1="7" y1="10" x2="10" y2="10" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" />
            <line x1="14" y1="10" x2="17" y2="10" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" />
            <line x1="9" y1="15" x2="15" y2="15" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" />
          </svg>
        )

      case 'happy':
        // 嬉しい顔（^ ^）
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
            <circle cx="12" cy="12" r="10" stroke={strokeColor} strokeWidth={strokeWidth} fill="none" />
            <path d="M7 11 L8.5 9 L10 11" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" fill="none" />
            <path d="M14 11 L15.5 9 L17 11" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" fill="none" />
            <path d="M8 14 Q12 18 16 14" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" fill="none" />
          </svg>
        )

      case 'working':
        // 集中顔（> <）
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
            <circle cx="12" cy="12" r="10" stroke={strokeColor} strokeWidth={strokeWidth} fill="none" />
            <path d="M7 9 L9 10.5 L7 12" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" fill="none" />
            <path d="M17 9 L15 10.5 L17 12" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" fill="none" />
            <line x1="10" y1="16" x2="14" y2="16" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" />
          </svg>
        )

      case 'sleepy':
        // 眠い顔（- - ） zzz
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
            <circle cx="12" cy="12" r="10" stroke={strokeColor} strokeWidth={strokeWidth} fill="none" />
            <line x1="6" y1="11" x2="10" y2="11" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" />
            <line x1="14" y1="11" x2="18" y2="11" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" />
            <ellipse cx="12" cy="15" rx="2" ry="1.5" stroke={strokeColor} strokeWidth={strokeWidth} fill="none" />
            {/* zzz */}
            <text x="18" y="6" fontSize="6" fill={strokeColor} fontFamily="sans-serif">z</text>
            <text x="20" y="4" fontSize="5" fill={strokeColor} fontFamily="sans-serif">z</text>
          </svg>
        )

      case 'sad':
        // 悲しい顔（; ;）
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
            <circle cx="12" cy="12" r="10" stroke={strokeColor} strokeWidth={strokeWidth} fill="none" />
            <circle cx="8" cy="10" r="1.5" fill={strokeColor} />
            <circle cx="16" cy="10" r="1.5" fill={strokeColor} />
            <line x1="6" y1="12" x2="6" y2="14" stroke={strokeColor} strokeWidth={1} strokeLinecap="round" />
            <line x1="18" y1="12" x2="18" y2="14" stroke={strokeColor} strokeWidth={1} strokeLinecap="round" />
            <path d="M9 16 Q12 14 15 16" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" fill="none" />
          </svg>
        )

      case 'excited':
        // 興奮顔（* *）
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" fill="none" className={className}>
            <circle cx="12" cy="12" r="10" stroke={strokeColor} strokeWidth={strokeWidth} fill="none" />
            {/* 左目スター */}
            <path d="M8 10 L8.5 8.5 L9 10 L10.5 10.5 L9 11 L8.5 12.5 L8 11 L6.5 10.5 Z" stroke={strokeColor} strokeWidth={1} fill="none" />
            {/* 右目スター */}
            <path d="M16 10 L16.5 8.5 L17 10 L18.5 10.5 L17 11 L16.5 12.5 L16 11 L14.5 10.5 Z" stroke={strokeColor} strokeWidth={1} fill="none" />
            <path d="M8 15 Q12 19 16 15" stroke={strokeColor} strokeWidth={strokeWidth} strokeLinecap="round" fill="none" />
          </svg>
        )

      default:
        return null
    }
  }

  return <>{renderEmoji()}</>
}

// 小さなアイコン用（吹き出し内など）
export function MiniIcon({ type, size = 14 }: { type: 'sparkle' | 'sweat' | 'music' | 'heart' | 'exclaim'; size?: number }): JSX.Element {
  const strokeColor = '#454138'

  switch (type) {
    case 'sparkle':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
          <path d="M8 1 L8 3 M8 13 L8 15 M1 8 L3 8 M13 8 L15 8 M3 3 L4.5 4.5 M11.5 11.5 L13 13 M3 13 L4.5 11.5 M11.5 4.5 L13 3" stroke={strokeColor} strokeWidth={1.5} strokeLinecap="round" />
        </svg>
      )
    case 'sweat':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
          <path d="M8 2 Q12 6 8 12 Q4 6 8 2" stroke={strokeColor} strokeWidth={1.5} fill="none" />
        </svg>
      )
    case 'music':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
          <path d="M6 12 L6 4 L12 2 L12 10" stroke={strokeColor} strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" fill="none" />
          <circle cx="4" cy="12" r="2" stroke={strokeColor} strokeWidth={1.5} fill="none" />
          <circle cx="10" cy="10" r="2" stroke={strokeColor} strokeWidth={1.5} fill="none" />
        </svg>
      )
    case 'heart':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
          <path d="M8 14 L2 8 Q0 5 3 3 Q6 2 8 5 Q10 2 13 3 Q16 5 14 8 Z" stroke={strokeColor} strokeWidth={1.5} fill="none" />
        </svg>
      )
    case 'exclaim':
      return (
        <svg width={size} height={size} viewBox="0 0 16 16" fill="none">
          <line x1="8" y1="2" x2="8" y2="9" stroke={strokeColor} strokeWidth={2} strokeLinecap="round" />
          <circle cx="8" cy="13" r="1.5" fill={strokeColor} />
        </svg>
      )
    default:
      return <></>
  }
}
