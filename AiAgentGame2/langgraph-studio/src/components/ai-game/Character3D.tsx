import { motion } from 'framer-motion'
import { SpeechBubble } from './SpeechBubble'
import { FlatEmoji } from './FlatEmoji'
import type { CharacterState } from './types'
import { AGENT_MODEL_MAP } from './types'
import type { AgentType } from '@/types/agent'

interface Character3DProps {
  agentType: AgentType
  state: CharacterState
  size?: number
  showLabel?: boolean
  onClick?: () => void
}

export function Character3D({
  agentType,
  state,
  size = 80,
  showLabel = true,
  onClick
}: Character3DProps): JSX.Element {
  const modelName = AGENT_MODEL_MAP[agentType] || 'cube_robot'
  const modelPath = `/sample/${modelName}.html`

  // ステータスに応じたアニメーション
  const getAnimation = () => {
    switch (state.status) {
      case 'idle':
        return {
          y: [0, -3, 0],
          transition: { duration: 2, repeat: Infinity, ease: 'easeInOut' }
        }
      case 'working':
        return {
          scale: [1, 1.05, 1],
          transition: { duration: 0.5, repeat: Infinity, ease: 'easeInOut' }
        }
      case 'departing':
      case 'returning':
        return {}
      default:
        return {}
    }
  }

  // 感情に応じた吹き出しテキスト
  const getSpeechBubbleContent = () => {
    if (state.speechBubble) {
      return { text: state.speechBubble }
    }

    switch (state.status) {
      case 'departing':
        return { text: '行ってきます', icon: 'exclaim' as const }
      case 'working':
        return { text: '処理中...', emotion: state.emotion }
      case 'returning':
        return { text: '持ってきた!', icon: 'sparkle' as const }
      default:
        return state.emotion !== 'idle' ? { emotion: state.emotion } : null
    }
  }

  const bubbleContent = getSpeechBubbleContent()

  return (
    <motion.div
      className="relative cursor-pointer group"
      animate={getAnimation()}
      onClick={onClick}
      whileHover={{ scale: 1.05 }}
      style={{ width: size, height: size + (showLabel ? 20 : 0) }}
    >
      {/* 吹き出し */}
      {bubbleContent && (
        <SpeechBubble
          text={bubbleContent.text}
          emotion={bubbleContent.emotion}
          icon={bubbleContent.icon}
          visible={true}
        />
      )}

      {/* 3Dモデル表示（iframe） */}
      <div
        className="relative overflow-hidden"
        style={{ width: size, height: size }}
      >
        <iframe
          src={modelPath}
          width={size * 2}
          height={size * 2}
          className="pointer-events-none border-0"
          style={{
            transform: `scale(0.5) translate(-${size}px, -${size}px)`,
            transformOrigin: 'top left',
            background: 'transparent'
          }}
          title={agentType}
        />

        {/* ステータスインジケーター */}
        {state.status === 'working' && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-nier-border-light">
            <motion.div
              className="h-full bg-nier-text-main"
              initial={{ width: '0%' }}
              animate={{ width: '100%' }}
              transition={{ duration: 3, repeat: Infinity }}
            />
          </div>
        )}

        {/* 感情アイコン（右下） */}
        {state.emotion !== 'idle' && state.status === 'idle' && (
          <div className="absolute bottom-1 right-1">
            <FlatEmoji emotion={state.emotion} size={16} />
          </div>
        )}
      </div>

      {/* ラベル */}
      {showLabel && (
        <div className="text-center mt-1">
          <span className="text-nier-caption text-nier-text-light tracking-nier">
            {agentType.toUpperCase().replace('_', ' ')}
          </span>
        </div>
      )}
    </motion.div>
  )
}

// シンプルな3Dキャラクター（状態なし、表示のみ）
export function SimpleCharacter3D({
  agentType,
  size = 60
}: {
  agentType: AgentType
  size?: number
}): JSX.Element {
  const modelName = AGENT_MODEL_MAP[agentType] || 'cube_robot'
  const modelPath = `/sample/${modelName}.html`

  return (
    <div
      className="relative overflow-hidden"
      style={{ width: size, height: size }}
    >
      <iframe
        src={modelPath}
        width={size * 2}
        height={size * 2}
        className="pointer-events-none border-0"
        style={{
          transform: `scale(0.5) translate(-${size}px, -${size}px)`,
          transformOrigin: 'top left',
          background: 'transparent'
        }}
        title={agentType}
      />
    </div>
  )
}
