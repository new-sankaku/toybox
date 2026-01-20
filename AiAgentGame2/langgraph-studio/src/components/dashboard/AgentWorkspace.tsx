import { useMemo, useEffect, useRef, useState, useCallback } from 'react'
import { Card, CardHeader, CardContent } from '@/components/ui/Card'
import { DiamondMarker } from '@/components/ui/DiamondMarker'
import { useProjectStore } from '@/stores/projectStore'
import { useAgentStore } from '@/stores/agentStore'
import { useAgentDefinitionStore } from '@/stores/agentDefinitionStore'
import { agentApi } from '@/services/apiService'
import type { Agent, AgentStatus } from '@/types/agent'

type CharacterType =
  | 'wizard'    // ボス - 魔法使い
  | 'knight'    // 分配係1 - 騎士
  | 'ninja'     // 分配係2 - 忍者
  | 'samurai'   // 分配係3 - 侍
  | 'archer'    // 分配係4 - 弓使い
  | 'princess'  // 企画 - 姫
  | 'bard'      // シナリオ - 吟遊詩人
  | 'druid'     // 世界観 - ドルイド
  | 'alchemist' // デザイン - 錬金術師
  | 'engineer'  // テック - エンジニア
  | 'cat'       // キャラアセット - 猫
  | 'owl'       // 背景アセット - フクロウ
  | 'fox'       // UIアセット - キツネ
  | 'fairy'     // エフェクト - 妖精
  | 'phoenix'   // BGM - 不死鳥
  | 'mermaid'   // ボイス - 人魚
  | 'wolf'      // 効果音 - オオカミ
  | 'golem'     // コード - ゴーレム
  | 'puppet'    // イベント - 人形
  | 'clockwork' // UI統合 - 機械仕掛け
  | 'mech'      // アセット統合 - メカ
  | 'dragon'    // テスト1 - ドラゴン
  | 'turtle'    // テスト2 - 亀

interface AgentDisplayConfig {
  label: string
  bodyColor: string    // メインカラー
  accentColor: string  // アクセントカラー
  characterType: CharacterType
}

function getAgentDisplayConfig(agentType: string): AgentDisplayConfig {
  const configs: Record<string, AgentDisplayConfig> = {
    concept: { label: 'ボス', bodyColor: '#1a4080', accentColor: '#4080c0', characterType: 'wizard' },
    task_split_1: { label: '分配係1', bodyColor: '#704010', accentColor: '#b08040', characterType: 'knight' },
    task_split_2: { label: '分配係2', bodyColor: '#302050', accentColor: '#6050a0', characterType: 'ninja' },
    task_split_3: { label: '分配係3', bodyColor: '#801020', accentColor: '#c04060', characterType: 'samurai' },
    task_split_4: { label: '分配係4', bodyColor: '#205030', accentColor: '#408060', characterType: 'archer' },
    concept_detail: { label: '企画', bodyColor: '#a02050', accentColor: '#e070a0', characterType: 'princess' },
    scenario: { label: 'シナリオ', bodyColor: '#502080', accentColor: '#9060c0', characterType: 'bard' },
    world: { label: '世界観', bodyColor: '#106030', accentColor: '#40a060', characterType: 'druid' },
    game_design: { label: 'デザイン', bodyColor: '#806010', accentColor: '#c0a030', characterType: 'alchemist' },
    tech_spec: { label: 'テック', bodyColor: '#105070', accentColor: '#3090b0', characterType: 'engineer' },
    asset_character: { label: 'キャラ', bodyColor: '#904020', accentColor: '#d08050', characterType: 'cat' },
    asset_background: { label: '背景', bodyColor: '#304060', accentColor: '#6080b0', characterType: 'owl' },
    asset_ui: { label: 'UI', bodyColor: '#804010', accentColor: '#c08040', characterType: 'fox' },
    asset_effect: { label: 'エフェクト', bodyColor: '#603080', accentColor: '#a060c0', characterType: 'fairy' },
    asset_bgm: { label: 'BGM', bodyColor: '#802010', accentColor: '#c06040', characterType: 'phoenix' },
    asset_voice: { label: 'ボイス', bodyColor: '#106060', accentColor: '#40a0a0', characterType: 'mermaid' },
    asset_sfx: { label: '効果音', bodyColor: '#404050', accentColor: '#707090', characterType: 'wolf' },
    code: { label: 'コード', bodyColor: '#303060', accentColor: '#6060a0', characterType: 'golem' },
    event: { label: 'イベント', bodyColor: '#503050', accentColor: '#906090', characterType: 'puppet' },
    ui_integration: { label: 'UI統合', bodyColor: '#504030', accentColor: '#908060', characterType: 'clockwork' },
    asset_integration: { label: '統合', bodyColor: '#204050', accentColor: '#508090', characterType: 'mech' },
    unit_test: { label: 'テスト1', bodyColor: '#106020', accentColor: '#40a050', characterType: 'dragon' },
    integration_test: { label: 'テスト2', bodyColor: '#205040', accentColor: '#409070', characterType: 'turtle' },
  }
  return configs[agentType] || { label: 'Agent', bodyColor: '#505050', accentColor: '#808080', characterType: 'wizard' }
}

function PixelAvatar({
  agentType,
  status,
  isExiting = false,
}: {
  agentType: string
  status: AgentStatus
  isExiting?: boolean
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const config = getAgentDisplayConfig(agentType)
  const isWorking = status === 'running' || isExiting
  const isPending = status === 'pending'
  const isCompleted = status === 'completed'
  const frameRef = useRef(0)
  const animationRef = useRef<number>(0)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const dpr = window.devicePixelRatio || 1
    const size = 56
    canvas.width = size * dpr
    canvas.height = size * dpr
    canvas.style.width = `${size}px`
    canvas.style.height = `${size}px`
    ctx.scale(dpr, dpr)

    const px = 2
    const drawPx = (x: number, y: number, w: number = 1, h: number = 1) => {
      ctx.fillRect(x * px, y * px, w * px, h * px)
    }

    const drawCat = (frame: number, baseY: number) => {
      const centerX = 14
      const anim = isWorking ? Math.sin(frame * 0.2) * 2 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.12)'
      drawPx(centerX - 5, 25, 10, 1)

      ctx.fillStyle = config.bodyColor
      const tailWave = Math.sin(frame * 0.1) * 2
      drawPx(centerX + 5, baseY + 8 + tailWave, 2, 6)
      drawPx(centerX + 6, baseY + 6 + tailWave, 2, 3)

      drawPx(centerX - 5, baseY + 10, 10, 6)

      drawPx(centerX - 4, baseY + 2, 8, 8)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY, 2, 3)
      drawPx(centerX + 2, baseY, 2, 3)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 1, 1, 1)
      drawPx(centerX + 2, baseY + 1, 1, 1)

      ctx.fillStyle = '#40a040'
      drawPx(centerX - 3, baseY + 5, 2, 2)
      drawPx(centerX + 1, baseY + 5, 2, 2)
      
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX - 2.5, baseY + 5.5, 1, 1)
      drawPx(centerX + 1.5, baseY + 5.5, 1, 1)

      ctx.fillStyle = '#ff9090'
      drawPx(centerX - 0.5, baseY + 7, 1, 1)

      ctx.fillStyle = '#ffffff'
      drawPx(centerX - 6, baseY + 7, 2, 0.5)
      drawPx(centerX + 4, baseY + 7, 2, 0.5)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 16, 2, 4 + anim)
      drawPx(centerX + 2, baseY + 16, 2, 4 - anim)
    }

    const drawWizard = (frame: number, baseY: number) => {
      const centerX = 14
      const float = Math.sin(frame * 0.08) * 1.5
      const staffGlow = isWorking ? 0.5 + Math.sin(frame * 0.2) * 0.3 : 0.3

      ctx.fillStyle = 'rgba(0,0,0,0.12)'
      drawPx(centerX - 4, 26, 8, 1)
      ctx.fillStyle = '#5a3a20'
      drawPx(centerX + 6, baseY + 4 + float, 1, 14)
      
      ctx.fillStyle = `rgba(${parseInt(config.accentColor.slice(1, 3), 16)}, ${parseInt(config.accentColor.slice(3, 5), 16)}, ${parseInt(config.accentColor.slice(5, 7), 16)}, ${staffGlow})`
      drawPx(centerX + 5, baseY + 2 + float, 3, 3)
      ctx.fillStyle = config.accentColor
      drawPx(centerX + 6, baseY + 3 + float, 1, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 1, baseY + float, 2, 2)
      drawPx(centerX - 2, baseY + 2 + float, 4, 2)
      drawPx(centerX - 4, baseY + 4 + float, 8, 2)

      ctx.fillStyle = '#e8d4c4'
      drawPx(centerX - 3, baseY + 6 + float, 6, 4)

      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 2, baseY + 7 + float, 1, 1)
      drawPx(centerX + 1, baseY + 7 + float, 1, 1)

      ctx.fillStyle = '#d0d0d0'
      drawPx(centerX - 2, baseY + 9 + float, 4, 2)
      drawPx(centerX - 1, baseY + 11 + float, 2, 3)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 10 + float, 8, 8)
      drawPx(centerX - 5, baseY + 14 + float, 10, 6)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 1, baseY + 11 + float, 2, 6)
    }

    const drawKnight = (frame: number, baseY: number) => {
      const centerX = 14
      const anim = isWorking ? Math.sin(frame * 0.12) : 0

      ctx.fillStyle = 'rgba(0,0,0,0.15)'
      drawPx(centerX - 5, 26, 10, 1)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 1, baseY, 2, 3)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 2, 6, 5)
      
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX - 2, baseY + 4, 4, 2)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 5, 1, 1)
      drawPx(centerX + 1, baseY + 5, 1, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 5, baseY + 7, 10, 6)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 8, 4, 3)
      ctx.fillStyle = '#808080'
      drawPx(centerX + 6, baseY + 5 + anim * 2, 1, 10)
      ctx.fillStyle = config.accentColor
      drawPx(centerX + 5, baseY + 14 + anim * 2, 3, 2)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 8, baseY + 8 - anim, 3, 6)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 7, baseY + 10 - anim, 1, 2)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 13, 2, 6)
      drawPx(centerX + 1, baseY + 13, 2, 6)
      ctx.fillStyle = '#404040'
      drawPx(centerX - 4, baseY + 18, 3, 2)
      drawPx(centerX + 1, baseY + 18, 3, 2)
    }

    const drawNinja = (frame: number, baseY: number) => {
      const centerX = 14
      const anim = isWorking ? Math.sin(frame * 0.25) * 2 : 0
      const jump = isWorking ? Math.abs(Math.sin(frame * 0.15)) * 3 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 3, 26, 6, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 2 - jump, 6, 5)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 4 - jump, 4, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 7 - jump, 8, 6)
      drawPx(centerX - 6, baseY + 7 - jump + anim, 2, 5)
      drawPx(centerX + 4, baseY + 7 - jump - anim, 2, 5)
      ctx.fillStyle = '#606060'
      drawPx(centerX + 5, baseY + 4 - jump - anim, 1, 4)
      ctx.fillStyle = config.accentColor
      drawPx(centerX + 3, baseY + 5 - jump, 3 + anim, 2)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 13 - jump, 2, 5)
      drawPx(centerX + 1, baseY + 13 - jump, 2, 5)
    }

    const drawSamurai = (frame: number, baseY: number) => {
      const centerX = 14
      const anim = isWorking ? Math.sin(frame * 0.15) : 0

      ctx.fillStyle = 'rgba(0,0,0,0.12)'
      drawPx(centerX - 5, 26, 10, 1)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 4, baseY, 2, 3)
      drawPx(centerX + 2, baseY, 2, 3)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 3, 8, 4)
      
      ctx.fillStyle = '#d0c0b0'
      drawPx(centerX - 2, baseY + 5, 4, 3)
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX - 1, baseY + 6, 1, 1)
      drawPx(centerX + 1, baseY + 6, 1, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 5, baseY + 8, 10, 6)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 5, baseY + 8, 10, 1)
      ctx.fillStyle = '#808080'
      drawPx(centerX + 5 + anim, baseY + 6, 1, 12)
      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX + 4 + anim, baseY + 16, 3, 2)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 14, 8, 6)
    }

    const drawArcher = (frame: number, baseY: number) => {
      const centerX = 14
      const drawAnim = isWorking ? Math.sin(frame * 0.1) * 2 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 4, 26, 8, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 1, 6, 4)
      drawPx(centerX - 4, baseY + 3, 8, 2)

      ctx.fillStyle = '#e8d4c4'
      drawPx(centerX - 2, baseY + 4, 4, 4)
      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 1, baseY + 5, 1, 1)
      drawPx(centerX + 1, baseY + 5, 1, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 8, 8, 6)
      ctx.fillStyle = '#6a4a30'
      drawPx(centerX - 7, baseY + 4, 1, 12)
      ctx.fillStyle = '#d0d0d0'
      drawPx(centerX - 6, baseY + 4, 1, 1)
      drawPx(centerX - 5 - drawAnim, baseY + 10, 1, 1)
      drawPx(centerX - 6, baseY + 15, 1, 1)
      if (isWorking) {
        ctx.fillStyle = '#808080'
        drawPx(centerX - 4 - drawAnim, baseY + 10, 4, 1)
      }
      ctx.fillStyle = config.accentColor
      drawPx(centerX + 4, baseY + 8, 2, 8)

      ctx.fillStyle = '#4a3a2a'
      drawPx(centerX - 2, baseY + 14, 2, 5)
      drawPx(centerX + 1, baseY + 14, 2, 5)
    }

    const drawPrincess = (frame: number, baseY: number) => {
      const centerX = 14
      const sway = Math.sin(frame * 0.08) * 0.5

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 4, 26, 8, 1)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 1, 4, 2)
      drawPx(centerX - 1, baseY, 2, 1)

      ctx.fillStyle = '#5a4030'
      drawPx(centerX - 4, baseY + 2, 8, 6)
      drawPx(centerX - 5, baseY + 5, 2, 8)
      drawPx(centerX + 3, baseY + 5, 2, 8)

      ctx.fillStyle = '#f0dcc8'
      drawPx(centerX - 3, baseY + 3, 6, 5)
      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 2, baseY + 5, 1.5, 1.5)
      drawPx(centerX + 0.5, baseY + 5, 1.5, 1.5)
      
      ctx.fillStyle = '#c08080'
      drawPx(centerX - 0.5, baseY + 7, 1, 0.5)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 8, 8, 4)
      
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 5, baseY + 12 + sway, 10, 8)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 1, baseY + 9, 2, 2)
      drawPx(centerX - 4, baseY + 14 + sway, 8, 1)
    }

    const drawBard = (frame: number, baseY: number) => {
      const centerX = 14
      const strum = isWorking ? Math.sin(frame * 0.3) * 1.5 : 0
      const noteY = isWorking ? (frame * 0.5) % 10 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 4, 26, 8, 1)
      if (isWorking) {
        ctx.fillStyle = config.accentColor
        drawPx(centerX + 5, baseY + 2 - noteY, 2, 2)
      }
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 2, 6, 3)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX + 2, baseY, 2, 3)

      ctx.fillStyle = '#e8d4c4'
      drawPx(centerX - 2, baseY + 4, 4, 4)
      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 1, baseY + 5, 1, 1)
      drawPx(centerX + 1, baseY + 5, 1, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 8, 8, 6)
      ctx.fillStyle = '#8a6a40'
      drawPx(centerX - 7, baseY + 10 + strum, 4, 6)
      ctx.fillStyle = '#6a4a30'
      drawPx(centerX - 6, baseY + 8 + strum, 2, 3)
      ctx.fillStyle = '#d0d0d0'
      drawPx(centerX - 5, baseY + 11 + strum, 1, 4)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 2, baseY + 14, 2, 5)
      drawPx(centerX + 1, baseY + 14, 2, 5)
    }

    const drawDruid = (frame: number, baseY: number) => {
      const centerX = 14
      const leafSway = Math.sin(frame * 0.1) * 1

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 4, 26, 8, 1)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 1 + leafSway, 2, 2)
      drawPx(centerX + 1, baseY + 1 - leafSway, 2, 2)
      drawPx(centerX - 1, baseY, 2, 2)
      ctx.fillStyle = '#6a5a4a'
      drawPx(centerX - 3, baseY + 2, 6, 5)
      drawPx(centerX - 4, baseY + 5, 2, 6)
      drawPx(centerX + 2, baseY + 5, 2, 6)

      ctx.fillStyle = '#e8d4c4'
      drawPx(centerX - 2, baseY + 4, 4, 4)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 1, baseY + 5, 1, 1)
      drawPx(centerX + 1, baseY + 5, 1, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 8, 8, 6)
      drawPx(centerX - 5, baseY + 12, 10, 8)
      ctx.fillStyle = '#5a4a30'
      drawPx(centerX + 5, baseY + 4, 1, 14)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX + 4, baseY + 2, 3, 3)
    }

    const drawAlchemist = (frame: number, baseY: number) => {
      const centerX = 14
      const bubble = isWorking ? Math.sin(frame * 0.3) * 2 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 4, 26, 8, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 1, 6, 4)

      ctx.fillStyle = '#e8d4c4'
      drawPx(centerX - 2, baseY + 4, 4, 4)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 5, 1.5, 1.5)
      drawPx(centerX + 0.5, baseY + 5, 1.5, 1.5)
      ctx.fillStyle = '#e0e0e0'
      drawPx(centerX - 4, baseY + 8, 8, 8)
      
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 9, 6, 6)
      ctx.fillStyle = '#90c0d0'
      drawPx(centerX + 4, baseY + 10, 3, 5)
      
      if (isWorking) {
        ctx.fillStyle = config.accentColor
        drawPx(centerX + 5, baseY + 8 - bubble, 1, 1)
        drawPx(centerX + 4, baseY + 6 - bubble, 1, 1)
      }

      ctx.fillStyle = '#4a4a4a'
      drawPx(centerX - 2, baseY + 16, 2, 4)
      drawPx(centerX + 1, baseY + 16, 2, 4)
    }

    const drawEngineer = (frame: number, baseY: number) => {
      const centerX = 14
      const wrench = isWorking ? Math.sin(frame * 0.2) * 2 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.12)'
      drawPx(centerX - 4, 26, 8, 1)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 1, 6, 4)
      
      ctx.fillStyle = isWorking ? '#ffff00' : '#808080'
      drawPx(centerX - 1, baseY + 2, 2, 1)

      ctx.fillStyle = '#e8d4c4'
      drawPx(centerX - 2, baseY + 4, 4, 4)
      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 1, baseY + 5, 1, 1)
      drawPx(centerX + 1, baseY + 5, 1, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 8, 8, 7)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 10, 2, 2)
      drawPx(centerX + 1, baseY + 10, 2, 2)
      ctx.fillStyle = '#606060'
      drawPx(centerX + 5, baseY + 8 + wrench, 2, 6)
      ctx.fillStyle = '#808080'
      drawPx(centerX + 4, baseY + 7 + wrench, 4, 2)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 15, 2, 4)
      drawPx(centerX + 1, baseY + 15, 2, 4)
    }

    const drawOwl = (frame: number, baseY: number) => {
      const centerX = 14
      const blink = Math.floor(frame / 30) % 5 === 0
      const headTilt = Math.sin(frame * 0.05) * 1

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 4, 26, 8, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 10, 8, 10)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4 + headTilt, baseY + 2, 8, 8)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 4 + headTilt, baseY + 1, 2, 3)
      drawPx(centerX + 2 + headTilt, baseY + 1, 2, 3)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3 + headTilt, baseY + 4, 6, 4)
      ctx.fillStyle = '#ffcc00'
      drawPx(centerX - 2 + headTilt, baseY + 5, 2, 2)
      drawPx(centerX + 1 + headTilt, baseY + 5, 2, 2)
      if (!blink) {
        ctx.fillStyle = '#1a1a1a'
        drawPx(centerX - 1.5 + headTilt, baseY + 5.5, 1, 1)
        drawPx(centerX + 1.5 + headTilt, baseY + 5.5, 1, 1)
      }

      ctx.fillStyle = '#e0a020'
      drawPx(centerX - 0.5 + headTilt, baseY + 7, 1, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 6, baseY + 11, 2, 6)
      drawPx(centerX + 4, baseY + 11, 2, 6)

      ctx.fillStyle = '#e0a020'
      drawPx(centerX - 2, baseY + 18, 1, 2)
      drawPx(centerX + 1, baseY + 18, 1, 2)
    }

    const drawFox = (frame: number, baseY: number) => {
      const centerX = 14
      const tailWag = isWorking ? Math.sin(frame * 0.2) * 3 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.1)'
      drawPx(centerX - 5, 26, 10, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX + 4 + tailWag, baseY + 10, 4, 6)
      ctx.fillStyle = '#ffffff'
      drawPx(centerX + 6 + tailWag, baseY + 14, 2, 2)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 12, 8, 6)

      drawPx(centerX - 4, baseY + 4, 8, 8)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 5, baseY + 2, 3, 4)
      drawPx(centerX + 2, baseY + 2, 3, 4)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 4, baseY + 3, 1, 2)
      drawPx(centerX + 3, baseY + 3, 1, 2)
      ctx.fillStyle = '#ffffff'
      drawPx(centerX - 2, baseY + 6, 4, 5)

      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 2, baseY + 6, 1.5, 1.5)
      drawPx(centerX + 0.5, baseY + 6, 1.5, 1.5)

      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 0.5, baseY + 9, 1, 1)

      ctx.fillStyle = '#2a2a2a'
      drawPx(centerX - 3, baseY + 18, 2, 2)
      drawPx(centerX + 1, baseY + 18, 2, 2)
    }

    const drawFairy = (frame: number, baseY: number) => {
      const centerX = 14
      const float = Math.sin(frame * 0.12) * 3
      const wingFlap = Math.sin(frame * 0.3) * 2
      ctx.fillStyle = `rgba(${parseInt(config.accentColor.slice(1, 3), 16)}, ${parseInt(config.accentColor.slice(3, 5), 16)}, ${parseInt(config.accentColor.slice(5, 7), 16)}, 0.2)`
      drawPx(centerX - 6, baseY + 4 + float, 12, 12)

      ctx.fillStyle = config.accentColor
      drawPx(centerX - 7, baseY + 6 + float - wingFlap, 3, 6)
      drawPx(centerX + 4, baseY + 6 + float - wingFlap, 3, 6)
      drawPx(centerX - 6, baseY + 10 + float + wingFlap, 2, 4)
      drawPx(centerX + 4, baseY + 10 + float + wingFlap, 2, 4)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 2, baseY + 3 + float, 4, 4)

      ctx.fillStyle = '#f0e0d0'
      drawPx(centerX - 1, baseY + 5 + float, 2, 3)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 1, baseY + 6 + float, 0.5, 0.5)
      drawPx(centerX + 0.5, baseY + 6 + float, 0.5, 0.5)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 2, baseY + 8 + float, 4, 4)
      drawPx(centerX - 3, baseY + 11 + float, 6, 3)
      if (isWorking) {
        ctx.fillStyle = '#ffffff'
        const sparkle = (frame * 0.2) % 6
        drawPx(centerX - 4 + sparkle, baseY + 4 + float, 1, 1)
        drawPx(centerX + 2 - sparkle, baseY + 8 + float, 1, 1)
      }
    }

    const drawPhoenix = (frame: number, baseY: number) => {
      const centerX = 14
      const fly = isWorking ? Math.sin(frame * 0.15) * 2 : 0
      const wingFlap = isWorking ? Math.abs(Math.sin(frame * 0.25)) * 4 : 0
      const flame = Math.sin(frame * 0.3) * 1
      if (isWorking) {
        ctx.fillStyle = 'rgba(255, 150, 50, 0.3)'
        drawPx(centerX - 5, baseY + 4 + fly, 10, 14)
      }
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 14 + fly + flame, 4, 6)
      drawPx(centerX - 1, baseY + 18 + fly + flame, 2, 3)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 8, baseY + 8 + fly - wingFlap, 4, 4)
      drawPx(centerX + 4, baseY + 8 + fly - wingFlap, 4, 4)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 7, baseY + 10 + fly - wingFlap, 2, 2)
      drawPx(centerX + 5, baseY + 10 + fly - wingFlap, 2, 2)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 6 + fly, 6, 8)

      drawPx(centerX - 2, baseY + 2 + fly, 4, 5)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 1, baseY + fly, 2, 3)

      ctx.fillStyle = '#ffcc00'
      drawPx(centerX - 1, baseY + 4 + fly, 1, 1)
      drawPx(centerX + 1, baseY + 4 + fly, 1, 1)

      ctx.fillStyle = '#e0a020'
      drawPx(centerX - 0.5, baseY + 6 + fly, 1, 1)
    }

    const drawMermaid = (frame: number, baseY: number) => {
      const centerX = 14
      const swim = Math.sin(frame * 0.1) * 1.5
      const tailWave = Math.sin(frame * 0.15) * 2

      ctx.fillStyle = 'rgba(0,0,0,0.08)'
      drawPx(centerX - 4, 26, 8, 1)
      ctx.fillStyle = '#4a6060'
      drawPx(centerX - 4, baseY + 2 + swim, 8, 6)
      drawPx(centerX - 5, baseY + 6 + swim, 2, 8)
      drawPx(centerX + 3, baseY + 6 + swim, 2, 8)

      ctx.fillStyle = '#f0e8e0'
      drawPx(centerX - 2, baseY + 3 + swim, 4, 4)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 1, baseY + 4 + swim, 1, 1)
      drawPx(centerX + 1, baseY + 4 + swim, 1, 1)
      ctx.fillStyle = '#f0e8e0'
      drawPx(centerX - 3, baseY + 7 + swim, 6, 4)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 8 + swim, 1.5, 1.5)
      drawPx(centerX + 0.5, baseY + 8 + swim, 1.5, 1.5)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 2, baseY + 11 + swim, 4, 4)
      drawPx(centerX - 1, baseY + 15 + swim + tailWave, 2, 3)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 17 + swim + tailWave, 2, 3)
      drawPx(centerX + 1, baseY + 17 + swim + tailWave, 2, 3)
    }

    const drawWolf = (frame: number, baseY: number) => {
      const centerX = 14
      const howl = isWorking && Math.floor(frame / 20) % 3 === 0

      ctx.fillStyle = 'rgba(0,0,0,0.12)'
      drawPx(centerX - 5, 26, 10, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX + 4, baseY + 10, 3, 4)
      drawPx(centerX + 5, baseY + 8, 2, 3)

      drawPx(centerX - 4, baseY + 12, 8, 6)

      if (howl) {
        
        drawPx(centerX - 3, baseY + 4, 6, 4)
        drawPx(centerX - 1, baseY + 2, 2, 3)
        
        ctx.fillStyle = '#1a1a1a'
        drawPx(centerX - 0.5, baseY + 2, 1, 2)
      } else {
        drawPx(centerX - 3, baseY + 5, 6, 6)
        
        ctx.fillStyle = config.accentColor
        drawPx(centerX - 1, baseY + 8, 2, 3)
        ctx.fillStyle = '#1a1a1a'
        drawPx(centerX - 0.5, baseY + 9, 1, 1)
      }

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 3, 2, 3)
      drawPx(centerX + 2, baseY + 3, 2, 3)

      ctx.fillStyle = '#c0a000'
      drawPx(centerX - 2, baseY + 6, 1.5, 1.5)
      drawPx(centerX + 0.5, baseY + 6, 1.5, 1.5)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 18, 2, 2)
      drawPx(centerX + 1, baseY + 18, 2, 2)
    }

    const drawGolem = (frame: number, baseY: number) => {
      const centerX = 14
      const stomp = isWorking ? Math.abs(Math.sin(frame * 0.1)) * 1 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.2)'
      drawPx(centerX - 6, 26, 12, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 2 + stomp, 6, 5)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 4 + stomp, 1.5, 1.5)
      drawPx(centerX + 0.5, baseY + 4 + stomp, 1.5, 1.5)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 5, baseY + 7 + stomp, 10, 8)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 1, baseY + 9 + stomp, 2, 4)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 8, baseY + 8 + stomp, 3, 8)
      drawPx(centerX + 5, baseY + 8 + stomp, 3, 8)
      
      drawPx(centerX - 9, baseY + 15 + stomp, 4, 3)
      drawPx(centerX + 5, baseY + 15 + stomp, 4, 3)
      drawPx(centerX - 4, baseY + 15, 3, 5)
      drawPx(centerX + 1, baseY + 15, 3, 5)
    }

    const drawPuppet = (frame: number, baseY: number) => {
      const centerX = 14
      const dangle = Math.sin(frame * 0.15) * 2
      const armSwing = Math.sin(frame * 0.2) * 3
      ctx.fillStyle = '#808080'
      drawPx(centerX, baseY, 1, 4)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 3 + dangle, 6, 5)
      
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX - 2, baseY + 5 + dangle, 1.5, 1.5)
      drawPx(centerX + 0.5, baseY + 5 + dangle, 1.5, 1.5)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 1, baseY + 7 + dangle, 2, 0.5)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 8 + dangle, 6, 6)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 9 + dangle, 4, 2)
      ctx.fillStyle = '#808080'
      drawPx(centerX - 5, baseY + 2, 1, 6 + armSwing)
      drawPx(centerX + 4, baseY + 2, 1, 6 - armSwing)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 6, baseY + 8 + dangle + armSwing, 2, 4)
      drawPx(centerX + 4, baseY + 8 + dangle - armSwing, 2, 4)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 2, baseY + 14 + dangle, 2, 4)
      drawPx(centerX + 1, baseY + 14 + dangle, 2, 4)
    }

    const drawClockwork = (frame: number, baseY: number) => {
      const centerX = 14
      const gearRotate = (frame * 2) % 360
      const tick = Math.floor(frame / 10) % 2

      ctx.fillStyle = 'rgba(0,0,0,0.12)'
      drawPx(centerX - 5, 26, 10, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 2, 8, 6)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 3, 6, 4)
      
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX, baseY + 4, 1, 2)
      drawPx(centerX - 1 + tick, baseY + 5, 2, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 5, baseY + 8, 10, 8)
      
      ctx.fillStyle = config.accentColor
      const gx = Math.cos(gearRotate * 0.02) * 0.5
      const gy = Math.sin(gearRotate * 0.02) * 0.5
      drawPx(centerX - 2 + gx, baseY + 10 + gy, 4, 4)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 1, baseY + 11, 2, 2)
      ctx.fillStyle = '#606060'
      drawPx(centerX - 7, baseY + 9, 2, 5)
      drawPx(centerX + 5, baseY + 9, 2, 5)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 7, baseY + 13, 2, 1)
      drawPx(centerX + 5, baseY + 13, 2, 1)

      ctx.fillStyle = '#606060'
      drawPx(centerX - 3, baseY + 16, 2, 4)
      drawPx(centerX + 1, baseY + 16, 2, 4)
    }

    const drawMech = (frame: number, baseY: number) => {
      const centerX = 14
      const walk = isWorking ? Math.sin(frame * 0.12) * 1 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.15)'
      drawPx(centerX - 6, 26, 12, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 2, 6, 4)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 3, 4, 2)
      
      ctx.fillStyle = isWorking ? '#00ff00' : '#404040'
      drawPx(centerX - 1, baseY + 4, 1, 1)
      drawPx(centerX + 1, baseY + 4, 1, 1)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 6, 8, 7)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 7, 6, 4)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 7, baseY + 6, 3, 3)
      drawPx(centerX + 4, baseY + 6, 3, 3)

      ctx.fillStyle = '#606060'
      drawPx(centerX - 7, baseY + 9, 2, 6)
      drawPx(centerX + 5, baseY + 9, 2, 6)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 8, baseY + 14, 3, 2)
      drawPx(centerX + 5, baseY + 14, 3, 2)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 13 + walk, 3, 5)
      drawPx(centerX + 1, baseY + 13 - walk, 3, 5)
      ctx.fillStyle = '#606060'
      drawPx(centerX - 5, baseY + 17 + walk, 4, 3)
      drawPx(centerX + 1, baseY + 17 - walk, 4, 3)
    }

    const drawDragon = (frame: number, baseY: number) => {
      const centerX = 14
      const breathe = Math.sin(frame * 0.08) * 0.5
      const wingFlap = isWorking ? Math.sin(frame * 0.2) * 3 : 0
      if (isWorking && Math.floor(frame / 15) % 2 === 0) {
        ctx.fillStyle = config.accentColor
        drawPx(centerX + 4, baseY + 8, 4, 2)
        drawPx(centerX + 6, baseY + 7, 2, 1)
      }

      ctx.fillStyle = config.accentColor
      drawPx(centerX - 9, baseY + 6 - wingFlap, 4, 5)
      drawPx(centerX + 5, baseY + 6 - wingFlap, 4, 5)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 6, baseY + 14, 3, 3)
      drawPx(centerX - 8, baseY + 16, 2, 2)
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 9, baseY + 17, 2, 2)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 4, baseY + 10 + breathe, 8, 8)

      drawPx(centerX - 2, baseY + 4 + breathe, 6, 6)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 2, baseY + 2 + breathe, 2, 3)
      drawPx(centerX + 2, baseY + 2 + breathe, 2, 3)

      ctx.fillStyle = '#ff6600'
      drawPx(centerX, baseY + 6 + breathe, 2, 2)
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX + 0.5, baseY + 6.5 + breathe, 1, 1)
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX + 2, baseY + 8 + breathe, 1, 1)

      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 3, baseY + 17, 2, 3)
      drawPx(centerX + 1, baseY + 17, 2, 3)
    }

    const drawTurtle = (frame: number, baseY: number) => {
      const centerX = 14
      const crawl = isWorking ? Math.sin(frame * 0.08) * 1 : 0

      ctx.fillStyle = 'rgba(0,0,0,0.15)'
      drawPx(centerX - 6, 26, 12, 1)

      ctx.fillStyle = config.accentColor
      drawPx(centerX - 6, baseY + 16, 2, 2)
      ctx.fillStyle = config.bodyColor
      drawPx(centerX - 5, baseY + 8, 10, 8)
      
      ctx.fillStyle = config.accentColor
      drawPx(centerX - 3, baseY + 10, 2, 2)
      drawPx(centerX + 1, baseY + 10, 2, 2)
      drawPx(centerX - 1, baseY + 13, 2, 2)

      ctx.fillStyle = config.accentColor
      drawPx(centerX + 3, baseY + 10 + crawl, 4, 4)
      ctx.fillStyle = '#1a1a1a'
      drawPx(centerX + 5, baseY + 11 + crawl, 1, 1)

      ctx.fillStyle = config.accentColor
      drawPx(centerX - 5, baseY + 16 + crawl, 2, 2)
      drawPx(centerX + 3, baseY + 16 - crawl, 2, 2)
      drawPx(centerX - 5, baseY + 10 - crawl, 2, 2)
      drawPx(centerX + 3, baseY + 10 + crawl, 2, 2)
    }

    const draw = (frame: number) => {
      ctx.clearRect(0, 0, size, size)
      const baseY = isWorking ? 2 + Math.sin(frame * 0.1) * 0.5 : 2

      switch (config.characterType) {
        case 'wizard': drawWizard(frame, baseY); break
        case 'knight': drawKnight(frame, baseY); break
        case 'ninja': drawNinja(frame, baseY); break
        case 'samurai': drawSamurai(frame, baseY); break
        case 'archer': drawArcher(frame, baseY); break
        case 'princess': drawPrincess(frame, baseY); break
        case 'bard': drawBard(frame, baseY); break
        case 'druid': drawDruid(frame, baseY); break
        case 'alchemist': drawAlchemist(frame, baseY); break
        case 'engineer': drawEngineer(frame, baseY); break
        case 'cat': drawCat(frame, baseY); break
        case 'owl': drawOwl(frame, baseY); break
        case 'fox': drawFox(frame, baseY); break
        case 'fairy': drawFairy(frame, baseY); break
        case 'phoenix': drawPhoenix(frame, baseY); break
        case 'mermaid': drawMermaid(frame, baseY); break
        case 'wolf': drawWolf(frame, baseY); break
        case 'golem': drawGolem(frame, baseY); break
        case 'puppet': drawPuppet(frame, baseY); break
        case 'clockwork': drawClockwork(frame, baseY); break
        case 'mech': drawMech(frame, baseY); break
        case 'dragon': drawDragon(frame, baseY); break
        case 'turtle': drawTurtle(frame, baseY); break
      }
      if (isWorking) {
        ctx.fillStyle = `rgba(255, 220, 100, ${0.3 + Math.sin(frame * 0.2) * 0.2})`
        const sparkleX = 14 + Math.cos(frame * 0.12) * 10
        const sparkleY = 14 + Math.sin(frame * 0.17) * 8
        drawPx(sparkleX, sparkleY, 1, 1)
      }
    }

    const animate = () => {
      frameRef.current += 3  // Faster animation speed
      draw(frameRef.current)
      if (isWorking) {
        animationRef.current = requestAnimationFrame(animate)
      }
    }

    if (isWorking) {
      animate()
    } else {
      draw(0)
    }

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [config, isWorking])

  return (
    <div
      className={`relative ${isPending ? 'opacity-30' : ''}`}
      style={{
        width: 56,
        height: 56,
        borderRadius: 8,
        border: isWorking ? '2px solid #C4956C' : isCompleted ? '2px solid #7AAA7A' : '2px solid transparent',
        boxShadow: isWorking
          ? '0 0 12px rgba(196, 149, 108, 0.5)'
          : isCompleted
          ? '0 0 8px rgba(122, 170, 122, 0.3)'
          : 'none',
        background: '#d4cdb8',
      }}
    >
      <canvas ref={canvasRef} style={{ display: 'block' }} />
    </div>
  )
}

function AgentCharacterCard({
  agent,
  onExitComplete,
  exitDelay = 0,
}: {
  agent: Agent
  onExitComplete?: (agentId: string) => void
  exitDelay?: number
}) {
  const { getShortLabel, getSpeechBubble } = useAgentDefinitionStore()
  const [isExiting, setIsExiting] = useState(false)
  const exitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const initialExitDelayRef = useRef(exitDelay)

  const isWorking = agent.status === 'running'
  const isWaiting = agent.status === 'waiting_approval'
  const isCompleted = agent.status === 'completed'
  const isFailed = agent.status === 'failed'
  const displayLabel = getShortLabel(agent.type)
  const speechBubbleText = getSpeechBubble(agent.type)

  useEffect(() => {
    if (isCompleted && !isExiting && !exitTimerRef.current) {
      exitTimerRef.current = setTimeout(() => {
        setIsExiting(true)
      }, 300 + initialExitDelayRef.current * 400)
    }
    return () => {
    }
  }, [isCompleted, isExiting])

  const handleAnimationEnd = useCallback(() => {
    if (isExiting && onExitComplete) {
      onExitComplete(agent.id)
    }
  }, [isExiting, onExitComplete, agent.id])

  return (
    <div
      className={`relative flex flex-col items-center p-2 rounded-lg transition-all duration-300 ${isExiting ? 'animate-agent-exit' : ''}`}
      style={{
        background: isWorking
          ? 'linear-gradient(135deg, rgba(196, 149, 108, 0.15) 0%, rgba(196, 149, 108, 0.05) 100%)'
          : isCompleted
          ? 'linear-gradient(135deg, rgba(122, 170, 122, 0.1) 0%, rgba(122, 170, 122, 0.05) 100%)'
          : 'transparent',
        border: isWorking ? '2px solid rgba(196, 149, 108, 0.4)' : '2px solid transparent',
        minWidth: 80,
      }}
      onAnimationEnd={handleAnimationEnd}
    >
      {/* Speech bubble (only when working) - replaces status badge */}
      {isWorking && speechBubbleText && (
        <div
          className="absolute -top-7 left-0 right-0 mx-auto px-2 py-0.5 rounded text-[9px] z-20 pointer-events-none text-center w-fit"
          style={{
            background: '#FFFEF0',
            border: '1px solid #C4956C',
            boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
            color: '#454138',
            minWidth: '60px',
            maxWidth: 'calc(100% + 20px)',
          }}
        >
          {speechBubbleText}
          <div
            className="absolute left-1/2 -translate-x-1/2 -bottom-1.5"
            style={{
              width: 0,
              height: 0,
              borderLeft: '5px solid transparent',
              borderRight: '5px solid transparent',
              borderTop: '5px solid #C4956C',
            }}
          />
          <div
            className="absolute left-1/2 -translate-x-1/2"
            style={{
              bottom: '-4px',
              width: 0,
              height: 0,
              borderLeft: '4px solid transparent',
              borderRight: '4px solid transparent',
              borderTop: '4px solid #FFFEF0',
            }}
          />
        </div>
      )}
      {isWaiting && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[9px] font-bold whitespace-nowrap z-10"
          style={{ background: '#D4C896', color: '#454138' }}
        >
          確認待ち
        </div>
      )}
      {isCompleted && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[9px] font-bold whitespace-nowrap z-10"
          style={{ background: '#7AAA7A', color: '#FFF' }}
        >
          完了
        </div>
      )}
      {isFailed && (
        <div
          className="absolute -top-2 left-1/2 -translate-x-1/2 px-2 py-0.5 rounded-full text-[9px] font-bold whitespace-nowrap z-10"
          style={{ background: '#B85C5C', color: '#FFF' }}
        >
          エラー
        </div>
      )}

      {/* Avatar */}
      <div className="mt-1">
        <PixelAvatar agentType={agent.type} status={agent.status} isExiting={isExiting} />
      </div>

      {/* Progress bar */}
      {(isWorking || isCompleted) && (
        <div className="w-14 h-1.5 mt-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(0,0,0,0.1)' }}>
          <div
            className="h-full transition-all duration-500"
            style={{
              width: `${agent.progress || (isCompleted ? 100 : 0)}%`,
              background: isCompleted
                ? 'linear-gradient(90deg, #7AAA7A 0%, #5C8A5C 100%)'
                : 'linear-gradient(90deg, #C4956C 0%, #8B6914 100%)',
            }}
          />
        </div>
      )}

      {/* Name */}
      <div className="mt-1 text-[10px] text-nier-text-main font-medium text-center">
        {displayLabel}
      </div>

      {/* Progress percentage for running */}
      {isWorking && (
        <div className="text-[9px] text-nier-accent-orange font-bold">
          {agent.progress || 0}%
        </div>
      )}
    </div>
  )
}

export default function AgentWorkspace(): JSX.Element {
  const { currentProject } = useProjectStore()
  const { agents, setAgents } = useAgentStore()
  const [exitedAgentIds, setExitedAgentIds] = useState<Set<string>>(new Set())

  const handleExitComplete = useCallback((agentId: string) => {
    setExitedAgentIds(prev => new Set([...prev, agentId]))
  }, [])

  useEffect(() => {
    if (!currentProject) return

    const fetchAgents = async () => {
      try {
        const agentsData = await agentApi.listByProject(currentProject.id)
        const agentsConverted: Agent[] = agentsData.map(a => ({
          id: a.id,
          projectId: a.projectId,
          type: a.type,
          phase: a.phase,
          status: a.status as AgentStatus,
          progress: a.progress,
          currentTask: a.currentTask,
          tokensUsed: a.tokensUsed,
          startedAt: a.startedAt,
          completedAt: a.completedAt,
          error: a.error,
          parentAgentId: null,
          metadata: a.metadata,
          createdAt: a.startedAt || new Date().toISOString()
        }))
        setAgents(agentsConverted)
      } catch (error) {
        console.error('Failed to fetch agents:', error)
      }
    }

    fetchAgents()
  }, [currentProject?.id, setAgents])

  const displayAgents = useMemo(() => {
    if (!currentProject) return []

    const projectAgents = agents.filter(a =>
      a.projectId === currentProject.id && !exitedAgentIds.has(a.id)
    )

    return projectAgents
      .sort((a, b) => {
        if (a.phase !== b.phase) return a.phase - b.phase
        return a.type.localeCompare(b.type)
      })
      .slice(0, 16) // Show max 16 agents
  }, [agents, currentProject, exitedAgentIds])

  const runningCount = displayAgents.filter(a => a.status === 'running').length
  const completedCount = displayAgents.filter(a => a.status === 'completed').length
  const totalCount = displayAgents.length

  if (!currentProject) {
    return (
      <Card>
        <CardHeader>
          <DiamondMarker>エージェント作業場</DiamondMarker>
        </CardHeader>
        <CardContent>
          <div className="text-nier-text-light text-center py-4 text-nier-small">
            -
          </div>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <DiamondMarker>エージェント作業場</DiamondMarker>
        <div className="ml-auto flex items-center gap-4 text-nier-caption text-nier-text-light">
          {runningCount > 0 && (
            <span className="text-nier-accent-orange font-bold animate-pulse">
              作業中: {runningCount}
            </span>
          )}
          <span>完了: {completedCount}/{totalCount}</span>
        </div>
      </CardHeader>
      <CardContent>
        {displayAgents.length === 0 ? (
          <div className="text-nier-text-light text-center py-8 text-nier-small">
            エージェントがまだ起動していません
          </div>
        ) : (
          <div className="flex flex-wrap justify-start gap-3 py-2">
            {displayAgents.map((agent, index) => (
              <div key={agent.id} className="agent-card-wrapper">
                <AgentCharacterCard
                  agent={agent}
                  onExitComplete={handleExitComplete}
                  exitDelay={index}
                />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
