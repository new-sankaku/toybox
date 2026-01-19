import { motion } from 'framer-motion'
import { Character3D } from './Character3D'
import type { CharacterState } from './types'

interface GuildHallProps {
  characters: CharacterState[]
  onCharacterClick?: (character: CharacterState) => void
}

export function GuildHall({ characters, onCharacterClick }: GuildHallProps): JSX.Element {
  // 待機中のキャラクターのみ表示
  const idleCharacters = characters.filter(c => c.status === 'idle')

  return (
    <div className="relative w-full">
      {/* ヘッダーライン */}
      <div className="flex items-center justify-center mb-4">
        <div className="flex-1 h-px bg-nier-border-dark" />
        <span className="px-6 text-nier-small text-nier-text-light tracking-nier-wide">
          GUILD HALL
        </span>
        <div className="flex-1 h-px bg-nier-border-dark" />
      </div>

      {/* ミニマリストなギルドホール */}
      <div className="relative bg-nier-bg-panel border border-nier-border-light">
        {/* 上部装飾ライン */}
        <div className="absolute top-0 left-0 right-0 flex justify-between px-4">
          <span className="text-nier-caption text-nier-text-light -translate-y-1/2 bg-nier-bg-panel px-2">◇</span>
          <span className="text-nier-caption text-nier-text-light -translate-y-1/2 bg-nier-bg-panel px-2">◇</span>
        </div>

        {/* キャラクター配置エリア */}
        <div className="px-8 py-6">
          {idleCharacters.length === 0 ? (
            <div className="flex items-center justify-center h-24">
              <span className="text-nier-small text-nier-text-light">
                全員外出中...
              </span>
            </div>
          ) : (
            <div className="flex items-end justify-center gap-6 flex-wrap min-h-[100px]">
              {idleCharacters.map((character, index) => (
                <motion.div
                  key={character.agentId}
                  initial={{ opacity: 0, y: 20 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: index * 0.1 }}
                >
                  <Character3D
                    agentType={character.agentType}
                    state={character}
                    size={70}
                    onClick={() => onCharacterClick?.(character)}
                  />
                </motion.div>
              ))}
            </div>
          )}
        </div>

        {/* 下部装飾ライン */}
        <div className="absolute bottom-0 left-0 right-0 h-px bg-nier-border-dark">
          <div className="absolute left-1/2 -translate-x-1/2 -translate-y-1/2 bg-nier-bg-panel px-4">
            <span className="text-nier-caption text-nier-text-light">
              {idleCharacters.length} / {characters.length}
            </span>
          </div>
        </div>
      </div>

      {/* ステータスサマリー */}
      <div className="flex justify-center gap-8 mt-3 text-nier-caption text-nier-text-light">
        <span>待機中: {idleCharacters.length}</span>
        <span>外出中: {characters.filter(c => c.status !== 'idle').length}</span>
      </div>
    </div>
  )
}
