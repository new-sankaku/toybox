import { motion } from 'framer-motion'
import { MessageSquare, Image, Music, Mic } from 'lucide-react'
import { SimpleCharacter3D } from './Character3D'
import { SpeechBubble } from './SpeechBubble'
import type { AIServiceType, CharacterState, AIRequest } from './types'

interface ServiceZoneProps {
  serviceType: AIServiceType
  serviceName: string
  characters: CharacterState[]
  requests: AIRequest[]
  onCharacterClick?: (character: CharacterState) => void
}

const SERVICE_ICONS = {
  llm: MessageSquare,
  image: Image,
  music: Music,
  audio: Mic
}

const SERVICE_LABELS = {
  llm: 'LLM',
  image: '画像生成',
  music: '音楽生成',
  audio: '音声生成'
}

export function ServiceZone({
  serviceType,
  serviceName,
  characters,
  requests,
  onCharacterClick
}: ServiceZoneProps): JSX.Element {
  const Icon = SERVICE_ICONS[serviceType]
  const label = SERVICE_LABELS[serviceType]

  // このサービスで作業中のキャラクター
  const workingCharacters = characters.filter(c =>
    c.status === 'working' && c.targetService === serviceType
  )

  // 処理中のリクエスト
  const processingRequests = requests.filter(r => r.status === 'processing')
  const completedCount = requests.filter(r => r.status === 'completed').length
  const totalCost = requests.reduce((sum, r) => sum + (r.cost || 0), 0)

  const isActive = workingCharacters.length > 0

  return (
    <div className="relative">
      {/* サービスゾーンコンテナ */}
      <motion.div
        className={`
          relative border bg-nier-bg-panel
          ${isActive ? 'border-nier-border-dark' : 'border-nier-border-light'}
        `}
        animate={isActive ? {
          boxShadow: ['0 0 0 rgba(69,65,56,0)', '0 0 8px rgba(69,65,56,0.2)', '0 0 0 rgba(69,65,56,0)']
        } : {}}
        transition={{ duration: 2, repeat: Infinity }}
      >
        {/* ヘッダー */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-nier-border-light">
          <div className="flex items-center gap-2">
            <Icon size={14} className="text-nier-text-light" />
            <span className="text-nier-small text-nier-text-main tracking-nier">
              {serviceName}
            </span>
          </div>
          <span className="text-nier-caption text-nier-text-light">
            [{label}]
          </span>
        </div>

        {/* キャラクター表示エリア - わちゃわちゃ配置 */}
        <div className="relative min-h-[120px] p-4">
          {workingCharacters.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <span className="text-nier-caption text-nier-text-light">
                ─ 空き ─
              </span>
            </div>
          ) : (
            <div className="relative h-[100px]">
              {workingCharacters.map((character, index) => {
                // わちゃわちゃ配置：ランダムっぽい位置にずらす
                const offsetX = (index % 3) * 25 - 10 + (index * 7) % 15
                const offsetY = Math.floor(index / 3) * 20 + (index * 11) % 10
                const rotation = (index * 5) % 10 - 5

                return (
                  <motion.div
                    key={character.agentId}
                    className="absolute cursor-pointer"
                    style={{
                      left: `calc(50% + ${offsetX}px - 30px)`,
                      top: offsetY,
                      zIndex: index
                    }}
                    initial={{ opacity: 0, y: -50 }}
                    animate={{
                      opacity: 1,
                      y: 0,
                      rotate: rotation
                    }}
                    whileHover={{ scale: 1.1, zIndex: 100 }}
                    onClick={() => onCharacterClick?.(character)}
                  >
                    <div className="relative">
                      <SimpleCharacter3D
                        agentType={character.agentType}
                        size={55}
                      />
                      {/* 作業中の吹き出し */}
                      <SpeechBubble
                        emotion={character.emotion}
                        text={character.speechBubble}
                        visible={true}
                        position="top"
                      />
                    </div>
                  </motion.div>
                )
              })}
            </div>
          )}

          {/* 処理中のプログレスバー */}
          {processingRequests.length > 0 && (
            <div className="mt-2 space-y-1">
              {processingRequests.slice(0, 3).map((req, index) => (
                <div key={req.id} className="flex items-center gap-2">
                  <div className="flex-1 h-1 bg-nier-border-light overflow-hidden">
                    <motion.div
                      className="h-full bg-nier-text-light"
                      initial={{ width: '0%' }}
                      animate={{ width: '100%' }}
                      transition={{ duration: 3 + index, repeat: Infinity }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* フッター統計 */}
        <div className="flex items-center justify-between px-3 py-1.5 border-t border-nier-border-light text-nier-caption">
          <span className="text-nier-text-light">
            {completedCount}完了 / {processingRequests.length}処理中
          </span>
          {totalCost > 0 && (
            <span className="text-nier-text-main">
              ${totalCost.toFixed(3)}
            </span>
          )}
        </div>
      </motion.div>
    </div>
  )
}
