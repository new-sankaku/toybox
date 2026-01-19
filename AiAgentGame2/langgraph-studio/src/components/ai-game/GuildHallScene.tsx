import { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { GuildHall } from './GuildHall'
import { ServiceZone } from './ServiceZone'
import { SimpleCharacter3D } from './Character3D'
import { SpeechBubble } from './SpeechBubble'
import type { AIServiceType, CharacterState, AIRequest } from './types'
import type { AgentType } from '@/types/agent'

interface GuildHallSceneProps {
  requests: AIRequest[]
}

// リクエストからキャラクター状態を生成
function generateCharacterStates(requests: AIRequest[]): CharacterState[] {
  const characterMap = new Map<string, CharacterState>()

  // まずすべてのエージェントを待機状態で追加
  const uniqueAgents = new Map<string, AgentType>()
  requests.forEach(req => {
    if (!uniqueAgents.has(req.agentId)) {
      uniqueAgents.set(req.agentId, req.agentType)
    }
  })

  uniqueAgents.forEach((agentType, agentId) => {
    characterMap.set(agentId, {
      agentId,
      agentType,
      status: 'idle',
      emotion: 'idle',
      position: { x: 0, y: 0 }
    })
  })

  // 処理中のリクエストがあるエージェントは作業中に
  requests.forEach(req => {
    if (req.status === 'processing') {
      const char = characterMap.get(req.agentId)
      if (char) {
        char.status = 'working'
        char.emotion = 'working'
        char.targetService = req.serviceType
        char.request = req
        char.speechBubble = '処理中...'
      }
    }
  })

  // 最近完了したエージェントは嬉しい表情
  const recentCompleted = requests
    .filter(r => r.status === 'completed' && r.completedAt)
    .sort((a, b) => new Date(b.completedAt!).getTime() - new Date(a.completedAt!).getTime())
    .slice(0, 3)

  recentCompleted.forEach(req => {
    const char = characterMap.get(req.agentId)
    if (char && char.status === 'idle') {
      char.emotion = 'happy'
    }
  })

  // 失敗したリクエストがあるエージェントは悲しい
  requests.forEach(req => {
    if (req.status === 'failed') {
      const char = characterMap.get(req.agentId)
      if (char && char.status === 'idle') {
        char.emotion = 'sad'
      }
    }
  })

  // 長時間待機中のエージェントは眠い（pending状態が多い）
  const pendingCounts = new Map<string, number>()
  requests.forEach(req => {
    if (req.status === 'pending') {
      pendingCounts.set(req.agentId, (pendingCounts.get(req.agentId) || 0) + 1)
    }
  })
  pendingCounts.forEach((count, agentId) => {
    if (count >= 2) {
      const char = characterMap.get(agentId)
      if (char && char.status === 'idle' && char.emotion === 'idle') {
        char.emotion = 'sleepy'
      }
    }
  })

  return Array.from(characterMap.values())
}

// 移動中のキャラクターを表示するコンポーネント
function MovingCharacter({
  character,
  from,
  to,
  onComplete
}: {
  character: CharacterState
  from: { x: number; y: number }
  to: { x: number; y: number }
  onComplete?: () => void
}): JSX.Element {
  return (
    <motion.div
      className="absolute z-50"
      initial={{ x: from.x, y: from.y, opacity: 0 }}
      animate={{ x: to.x, y: to.y, opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 1.5, ease: 'easeInOut' }}
      onAnimationComplete={onComplete}
    >
      <div className="relative">
        <SimpleCharacter3D agentType={character.agentType} size={50} />
        <SpeechBubble
          text={character.status === 'departing' ? '行ってきます' : '持ってきた!'}
          icon={character.status === 'departing' ? 'exclaim' : 'sparkle'}
          visible={true}
        />
      </div>
    </motion.div>
  )
}

export function GuildHallScene({ requests }: GuildHallSceneProps): JSX.Element {
  const [selectedCharacter, setSelectedCharacter] = useState<CharacterState | null>(null)
  // 将来的に移動アニメーション用に使用
  const [movingCharacters] = useState<CharacterState[]>([])

  // リクエストからキャラクター状態を生成
  const characters = useMemo(() => generateCharacterStates(requests), [requests])

  // サービス別にリクエストをグループ化
  const serviceGroups = useMemo(() => {
    const groups: Record<AIServiceType, { serviceName: string; requests: AIRequest[] }> = {
      llm: { serviceName: 'Claude 3.5 Sonnet', requests: [] },
      image: { serviceName: 'DALL-E 3', requests: [] },
      music: { serviceName: 'Suno AI', requests: [] },
      audio: { serviceName: 'ElevenLabs', requests: [] }
    }

    requests.forEach(req => {
      groups[req.serviceType].requests.push(req)
      // サービス名を更新
      if (req.serviceName) {
        groups[req.serviceType].serviceName = req.serviceName
      }
    })

    return groups
  }, [requests])

  // サービス別のキャラクター
  const getCharactersForService = (serviceType: AIServiceType) => {
    return characters.filter(c => c.status === 'working' && c.targetService === serviceType)
  }

  const handleCharacterClick = (character: CharacterState) => {
    setSelectedCharacter(character)
  }

  // 統計
  const stats = useMemo(() => {
    const completed = requests.filter(r => r.status === 'completed').length
    const processing = requests.filter(r => r.status === 'processing').length
    const totalCost = requests.reduce((sum, r) => sum + (r.cost || 0), 0)
    const totalTokens = requests.reduce((sum, r) => sum + (r.tokensUsed || 0), 0)

    return { completed, processing, totalCost, totalTokens }
  }, [requests])

  return (
    <div className="relative w-full h-full min-h-[600px] bg-nier-bg-main p-4">
      {/* 上部: ギルドホール */}
      <div className="mb-8">
        <GuildHall
          characters={characters}
          onCharacterClick={handleCharacterClick}
        />
      </div>

      {/* 中央: 接続ライン（シンプルな点線） */}
      <div className="relative h-16 mb-4">
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex items-center gap-4 text-nier-caption text-nier-text-light">
            <div className="w-16 border-t border-dashed border-nier-border-dark" />
            <span>↓</span>
            <div className="w-16 border-t border-dashed border-nier-border-dark" />
            <span>↓</span>
            <div className="w-16 border-t border-dashed border-nier-border-dark" />
            <span>↓</span>
            <div className="w-16 border-t border-dashed border-nier-border-dark" />
          </div>
        </div>

        {/* 移動中のキャラクター */}
        <AnimatePresence>
          {movingCharacters.map(char => (
            <MovingCharacter
              key={char.agentId}
              character={char}
              from={{ x: 200, y: -50 }}
              to={{ x: 200, y: 50 }}
            />
          ))}
        </AnimatePresence>
      </div>

      {/* 下部: サービスゾーン */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {(Object.keys(serviceGroups) as AIServiceType[]).map(serviceType => (
          <ServiceZone
            key={serviceType}
            serviceType={serviceType}
            serviceName={serviceGroups[serviceType].serviceName}
            characters={getCharactersForService(serviceType)}
            requests={serviceGroups[serviceType].requests}
            onCharacterClick={handleCharacterClick}
          />
        ))}
      </div>

      {/* 下部: サマリー統計 */}
      <div className="mt-6 flex items-center justify-center gap-8 text-nier-small text-nier-text-light">
        <span>
          完了: <span className="text-nier-text-main">{stats.completed}</span>
        </span>
        <span>
          処理中: <span className="text-nier-text-main">{stats.processing}</span>
        </span>
        {stats.totalTokens > 0 && (
          <span>
            トークン: <span className="text-nier-text-main">{stats.totalTokens.toLocaleString()}</span>
          </span>
        )}
        <span>
          コスト: <span className="text-nier-text-main">${stats.totalCost.toFixed(3)}</span>
        </span>
      </div>

      {/* 選択されたキャラクターの詳細（モーダル的に表示） */}
      <AnimatePresence>
        {selectedCharacter && (
          <motion.div
            className="fixed inset-0 bg-black/20 flex items-center justify-center z-50"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={() => setSelectedCharacter(null)}
          >
            <motion.div
              className="bg-nier-bg-panel border border-nier-border-dark p-4 max-w-sm"
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              onClick={e => e.stopPropagation()}
            >
              <div className="flex items-start gap-4">
                <SimpleCharacter3D
                  agentType={selectedCharacter.agentType}
                  size={80}
                />
                <div className="flex-1">
                  <h3 className="text-nier-body font-medium text-nier-text-main mb-2">
                    {selectedCharacter.agentType.toUpperCase().replace('_', ' ')}
                  </h3>
                  <div className="space-y-1 text-nier-small text-nier-text-light">
                    <p>状態: {selectedCharacter.status === 'idle' ? '待機中' : '作業中'}</p>
                    {selectedCharacter.targetService && (
                      <p>対象: {selectedCharacter.targetService}</p>
                    )}
                    {selectedCharacter.request && (
                      <p className="text-nier-caption truncate">
                        タスク: {selectedCharacter.request.input.slice(0, 30)}...
                      </p>
                    )}
                  </div>
                </div>
              </div>
              <button
                className="mt-4 w-full py-1.5 text-nier-small text-nier-text-light border border-nier-border-light hover:bg-nier-bg-selected"
                onClick={() => setSelectedCharacter(null)}
              >
                閉じる
              </button>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
