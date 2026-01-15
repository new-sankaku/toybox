import { useState } from 'react'
import { CheckpointListView } from '@/components/checkpoints'
import CheckpointReviewView from '@/components/checkpoints/CheckpointReviewView'
import type { Checkpoint } from '@/types/checkpoint'

// Mock checkpoint data for UI demonstration
const mockCheckpoints: Checkpoint[] = [
  {
    id: 'cp-001',
    projectId: 'proj-001',
    agentId: 'agent-concept',
    type: 'concept_review',
    title: 'ゲームコンセプトドキュメント',
    description: 'RPGゲームの基本コンセプトとビジョン',
    output: {
      documentType: 'markdown',
      summary: '中世ファンタジー世界を舞台にしたアクションRPG。プレイヤーは失われた記憶を持つ騎士として、世界の真実を解き明かす旅に出る。',
      content: {
        title: 'Project Aurora - Game Concept',
        genre: 'Action RPG',
        platform: 'PC/Console',
        targetAudience: 'Core gamers 18-35'
      },
      tokensUsed: 2450,
      generationTimeMs: 12500
    },
    status: 'pending',
    feedback: null,
    resolvedAt: null,
    createdAt: new Date(Date.now() - 1000 * 60 * 15).toISOString(), // 15 min ago
    updatedAt: new Date(Date.now() - 1000 * 60 * 15).toISOString()
  },
  {
    id: 'cp-002',
    projectId: 'proj-001',
    agentId: 'agent-design',
    type: 'design_review',
    title: 'ゲームデザインドキュメント',
    description: 'コアメカニクスとゲームループの設計',
    output: {
      documentType: 'markdown',
      summary: 'リアルタイム戦闘システム、スキルツリー、クエストシステムの詳細設計。',
      content: {
        combatSystem: 'Real-time action',
        progressionSystem: 'Skill tree + Equipment',
        questSystem: 'Main + Side quests'
      },
      tokensUsed: 3200,
      generationTimeMs: 18000
    },
    status: 'pending',
    feedback: null,
    resolvedAt: null,
    createdAt: new Date(Date.now() - 1000 * 60 * 5).toISOString(), // 5 min ago
    updatedAt: new Date(Date.now() - 1000 * 60 * 5).toISOString()
  },
  {
    id: 'cp-003',
    projectId: 'proj-001',
    agentId: 'agent-scenario',
    type: 'scenario_review',
    title: 'シナリオ概要',
    description: 'メインストーリーとキーイベントの概要',
    output: {
      documentType: 'markdown',
      summary: '3幕構成のメインストーリー。記憶を失った騎士が、古代の陰謀を解き明かし、世界を救う物語。',
      content: {
        act1: '目覚めと旅立ち',
        act2: '真実の探求',
        act3: '最終決戦'
      },
      tokensUsed: 4100,
      generationTimeMs: 22000
    },
    status: 'approved',
    feedback: '素晴らしいストーリー構成です。',
    resolvedAt: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    createdAt: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    updatedAt: new Date(Date.now() - 1000 * 60 * 60).toISOString()
  },
  {
    id: 'cp-004',
    projectId: 'proj-001',
    agentId: 'agent-character',
    type: 'character_review',
    title: 'キャラクター設定',
    description: 'メインキャラクターの詳細設定',
    output: {
      documentType: 'markdown',
      summary: '主人公と主要NPCの性格、背景、能力の詳細設定。',
      content: {
        protagonist: 'Aria - 記憶喪失の騎士',
        companion: 'Felix - 謎の魔術師',
        antagonist: 'Lord Varen - 影の支配者'
      },
      tokensUsed: 2800,
      generationTimeMs: 15000
    },
    status: 'revision_requested',
    feedback: '主人公の動機付けをより明確にしてください。',
    resolvedAt: null,
    createdAt: new Date(Date.now() - 1000 * 60 * 90).toISOString(),
    updatedAt: new Date(Date.now() - 1000 * 60 * 30).toISOString()
  }
]

export default function CheckpointsView(): JSX.Element {
  const [selectedCheckpoint, setSelectedCheckpoint] = useState<Checkpoint | null>(null)

  const handleSelectCheckpoint = (checkpoint: Checkpoint) => {
    setSelectedCheckpoint(checkpoint)
  }

  const handleApprove = () => {
    console.log('Approved:', selectedCheckpoint?.id)
    setSelectedCheckpoint(null)
  }

  const handleReject = (reason: string) => {
    console.log('Rejected:', selectedCheckpoint?.id, reason)
    setSelectedCheckpoint(null)
  }

  const handleRequestChanges = (feedback: string) => {
    console.log('Changes requested:', selectedCheckpoint?.id, feedback)
    setSelectedCheckpoint(null)
  }

  const handleClose = () => {
    setSelectedCheckpoint(null)
  }

  // Show review view if checkpoint is selected
  if (selectedCheckpoint) {
    return (
      <CheckpointReviewView
        checkpoint={selectedCheckpoint}
        onApprove={handleApprove}
        onReject={handleReject}
        onRequestChanges={handleRequestChanges}
        onClose={handleClose}
      />
    )
  }

  // Show checkpoint list
  return (
    <CheckpointListView
      checkpoints={mockCheckpoints}
      onSelectCheckpoint={handleSelectCheckpoint}
      selectedCheckpointId={undefined}
    />
  )
}
