import { motion, AnimatePresence } from 'framer-motion'
import { FlatEmoji, MiniIcon } from './FlatEmoji'
import type { CharacterEmotion } from './types'

interface SpeechBubbleProps {
  text?: string
  emotion?: CharacterEmotion
  icon?: 'sparkle' | 'sweat' | 'music' | 'heart' | 'exclaim'
  visible?: boolean
  position?: 'top' | 'right'
}

export function SpeechBubble({
  text,
  emotion,
  icon,
  visible = true,
  position = 'top'
}: SpeechBubbleProps): JSX.Element {
  const positionStyles = position === 'top'
    ? 'bottom-full left-1/2 -translate-x-1/2 mb-1'
    : 'left-full top-1/2 -translate-y-1/2 ml-1'

  const tailStyles = position === 'top'
    ? 'top-full left-1/2 -translate-x-1/2 border-l-[6px] border-r-[6px] border-t-[6px] border-l-transparent border-r-transparent border-t-nier-bg-panel'
    : 'right-full top-1/2 -translate-y-1/2 border-t-[6px] border-b-[6px] border-r-[6px] border-t-transparent border-b-transparent border-r-nier-bg-panel'

  return (
    <AnimatePresence>
      {visible && (text || emotion || icon) && (
        <motion.div
          className={`absolute ${positionStyles} z-10`}
          initial={{ opacity: 0, scale: 0.8, y: position === 'top' ? 10 : 0 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.8 }}
          transition={{ duration: 0.2 }}
        >
          <div className="relative bg-nier-bg-panel border border-nier-border-dark px-2 py-1 whitespace-nowrap">
            <div className="flex items-center gap-1">
              {emotion && <FlatEmoji emotion={emotion} size={16} />}
              {icon && <MiniIcon type={icon} size={14} />}
              {text && (
                <span className="text-nier-caption text-nier-text-main">
                  {text}
                </span>
              )}
            </div>
            {/* 吹き出しの尻尾 */}
            <div className={`absolute w-0 h-0 ${tailStyles}`} />
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}
