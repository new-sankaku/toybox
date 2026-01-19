import { useRef, useEffect, useCallback, useState } from 'react'
import type { CharacterState, AIServiceType } from './types'
import { AGENT_MODEL_MAP, SERVICE_CONFIG } from './types'

interface AIField2DProps {
  characters: CharacterState[]
  onCharacterClick?: (character: CharacterState) => void
  characterScale?: number
}

// NieR Automata UI color palette - warm beige base
const NIER_COLORS = {
  background: '#d4cdb8',
  backgroundDark: '#c4bda8',
  primary: '#4a4540',
  primaryDim: '#6a655a',
  accent: '#b5a078',
  accentBright: '#c4a574',
  textMain: '#4a4540',
  textDim: '#7a756a'
}

// Spirit colors - gray tones
const SPIRIT_COLORS: Record<string, { body: string; core: string }> = {
  spirit_fire: { body: '#6a6a6a', core: '#8a8a8a' },
  spirit_water: { body: '#5a5a5a', core: '#7a7a7a' },
  spirit_earth: { body: '#707070', core: '#909090' },
  spirit_light: { body: '#505050', core: '#707070' },
  spirit_wind: { body: '#606060', core: '#808080' }
}

// Character position tracking
interface CharacterPosition {
  x: number
  y: number
  targetX: number
  targetY: number
  wanderTimer: number
  rotation: number
  wasWorking: boolean  // Track previous working state
}

export function AIField2D({ characters, onCharacterClick, characterScale = 1.0 }: AIField2DProps): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 })
  const positionsRef = useRef<Map<string, CharacterPosition>>(new Map())
  const frameRef = useRef<number>(0)
  const animationRef = useRef<number>(0)

  // Layout - Agent Room is narrower and taller on right, Platforms wider on left
  const ROOM_X = 0.75
  const ROOM_WIDTH = 0.22
  const PLATFORM_X = 0.03
  const PLATFORM_WIDTH = 0.35

  // Handle resize with devicePixelRatio for crisp rendering
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current && canvasRef.current) {
        const rect = containerRef.current.getBoundingClientRect()
        const dpr = window.devicePixelRatio || 1
        const canvas = canvasRef.current

        // Set actual canvas size scaled by devicePixelRatio
        canvas.width = rect.width * dpr
        canvas.height = rect.height * dpr

        // Set display size
        canvas.style.width = `${rect.width}px`
        canvas.style.height = `${rect.height}px`

        // Scale context
        const ctx = canvas.getContext('2d')
        if (ctx) {
          ctx.scale(dpr, dpr)
        }

        setDimensions({ width: rect.width, height: rect.height })
      }
    }
    updateDimensions()
    window.addEventListener('resize', updateDimensions)
    return () => window.removeEventListener('resize', updateDimensions)
  }, [])

  // Initialize character positions
  useEffect(() => {
    const positions = positionsRef.current
    const roomStartX = dimensions.width * ROOM_X
    const roomWidth = dimensions.width * ROOM_WIDTH
    const roomStartY = dimensions.height * 0.08
    const roomHeight = dimensions.height * 0.84

    characters.forEach((char) => {
      if (!positions.has(char.agentId)) {
        const x = roomStartX + 20 + Math.random() * (roomWidth - 40)
        const y = roomStartY + 30 + Math.random() * (roomHeight - 60)
        positions.set(char.agentId, {
          x, y,
          targetX: x,
          targetY: y,
          wanderTimer: Math.random() * 3000,
          rotation: Math.random() * Math.PI * 2,
          wasWorking: false
        })
      }
    })
  }, [characters, dimensions])

  // Draw sprite with shadow for depth
  const drawSprite = useCallback((
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    spiritType: string,
    size: number,
    isWorking: boolean,
    frame: number,
    rotation: number
  ) => {
    const colors = SPIRIT_COLORS[spiritType] || SPIRIT_COLORS.spirit_light
    const s = size / 2

    // Draw shadow first (offset and darker)
    ctx.save()
    ctx.translate(x + 3, y + 4)
    ctx.rotate(rotation + frame * 0.02)
    ctx.fillStyle = 'rgba(0, 0, 0, 0.2)'
    ctx.beginPath()
    ctx.moveTo(0, -s)
    ctx.lineTo(s * 0.7, 0)
    ctx.lineTo(0, s)
    ctx.lineTo(-s * 0.7, 0)
    ctx.closePath()
    ctx.fill()
    ctx.restore()

    // Draw main sprite
    ctx.save()
    ctx.translate(x, y)
    ctx.rotate(rotation + frame * 0.02)

    if (isWorking) {
      ctx.shadowColor = NIER_COLORS.accent
      ctx.shadowBlur = 12 + Math.sin(frame * 0.15) * 4
    }

    // Diamond shape
    ctx.fillStyle = colors.body
    ctx.beginPath()
    ctx.moveTo(0, -s)
    ctx.lineTo(s * 0.7, 0)
    ctx.lineTo(0, s)
    ctx.lineTo(-s * 0.7, 0)
    ctx.closePath()
    ctx.fill()

    // Core
    ctx.fillStyle = isWorking ? NIER_COLORS.accent : colors.core
    const coreSize = s * 0.4
    ctx.beginPath()
    ctx.moveTo(0, -coreSize)
    ctx.lineTo(coreSize * 0.7, 0)
    ctx.lineTo(0, coreSize)
    ctx.lineTo(-coreSize * 0.7, 0)
    ctx.closePath()
    ctx.fill()

    ctx.restore()
  }, [])

  // Draw platform (no grid)
  const drawPlatform = useCallback((
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    serviceType: AIServiceType,
    hasWorkers: boolean,
    frame: number
  ): { centerX: number; centerY: number } => {
    const config = SERVICE_CONFIG[serviceType]

    // Simple background
    ctx.fillStyle = hasWorkers ? NIER_COLORS.backgroundDark : NIER_COLORS.background
    ctx.fillRect(x, y, width, height)

    // Border
    ctx.strokeStyle = hasWorkers ? NIER_COLORS.accent : NIER_COLORS.primaryDim
    ctx.lineWidth = hasWorkers ? 2 : 1
    ctx.strokeRect(x, y, width, height)

    // Corner markers
    const cs = 8
    ctx.fillStyle = hasWorkers ? NIER_COLORS.accent : NIER_COLORS.primary
    ctx.fillRect(x, y, cs, 2)
    ctx.fillRect(x, y, 2, cs)
    ctx.fillRect(x + width - cs, y, cs, 2)
    ctx.fillRect(x + width - 2, y, 2, cs)
    ctx.fillRect(x, y + height - 2, cs, 2)
    ctx.fillRect(x, y + height - cs, 2, cs)
    ctx.fillRect(x + width - cs, y + height - 2, cs, 2)
    ctx.fillRect(x + width - 2, y + height - cs, 2, cs)

    // Label - left aligned
    ctx.fillStyle = NIER_COLORS.textMain
    ctx.font = 'bold 13px "Courier New", monospace'
    ctx.textAlign = 'left'
    ctx.fillText(serviceType.toUpperCase(), x + 12, y + 20)

    // Description - left aligned
    ctx.font = '10px "Courier New", monospace'
    ctx.fillStyle = NIER_COLORS.textDim
    ctx.fillText(config.description, x + 12, y + 36)

    // Status indicator
    const indicatorY = y + height - 15
    if (hasWorkers) {
      ctx.shadowColor = NIER_COLORS.accent
      ctx.shadowBlur = 8 + Math.sin(frame * 0.1) * 4
    }
    ctx.beginPath()
    ctx.arc(x + width / 2, indicatorY, 4, 0, Math.PI * 2)
    ctx.fillStyle = hasWorkers ? NIER_COLORS.accent : NIER_COLORS.primaryDim
    ctx.fill()
    ctx.shadowBlur = 0

    // Progress bar when active
    if (hasWorkers) {
      const barW = width - 30
      const barX = x + 15
      const barY = y + height - 30
      ctx.fillStyle = NIER_COLORS.primaryDim
      ctx.fillRect(barX, barY, barW, 3)
      ctx.fillStyle = NIER_COLORS.accent
      ctx.fillRect(barX, barY, barW * ((Math.sin(frame * 0.05) + 1) / 2), 3)
    }

    return { centerX: x + width / 2, centerY: y + height / 2 }
  }, [])

  // Draw agent room with accumulated assets
  const drawRoom = useCallback((
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    width: number,
    height: number,
    assetCount: number,
    frame: number
  ) => {
    // Background
    ctx.fillStyle = NIER_COLORS.backgroundDark
    ctx.fillRect(x, y, width, height)

    // Draw accumulated assets at bottom of room
    const assetAreaY = y + height - 60
    const maxVisibleAssets = Math.min(assetCount, 20)

    // Asset pile visualization
    for (let i = 0; i < maxVisibleAssets; i++) {
      const row = Math.floor(i / 5)
      const col = i % 5
      const assetX = x + 15 + col * (width - 30) / 5
      const assetY = assetAreaY - row * 12

      // Different asset shapes based on index
      const assetType = i % 4
      ctx.fillStyle = i % 2 === 0 ? '#9a9590' : '#8a8580'

      if (assetType === 0) {
        // Document/text asset
        ctx.fillRect(assetX, assetY, 12, 15)
        ctx.fillStyle = '#b5b0a8'
        ctx.fillRect(assetX + 2, assetY + 2, 8, 2)
        ctx.fillRect(assetX + 2, assetY + 5, 6, 2)
        ctx.fillRect(assetX + 2, assetY + 8, 7, 2)
      } else if (assetType === 1) {
        // Image asset
        ctx.fillRect(assetX, assetY, 14, 12)
        ctx.fillStyle = '#7a7570'
        ctx.fillRect(assetX + 2, assetY + 2, 10, 8)
        ctx.fillStyle = '#a5a098'
        ctx.beginPath()
        ctx.arc(assetX + 5, assetY + 5, 2, 0, Math.PI * 2)
        ctx.fill()
      } else if (assetType === 2) {
        // Audio asset
        ctx.fillRect(assetX, assetY, 13, 13)
        ctx.fillStyle = '#b5b0a8'
        ctx.beginPath()
        ctx.moveTo(assetX + 4, assetY + 3)
        ctx.lineTo(assetX + 4, assetY + 10)
        ctx.lineTo(assetX + 9, assetY + 6.5)
        ctx.closePath()
        ctx.fill()
      } else {
        // Code asset
        ctx.fillRect(assetX, assetY, 12, 14)
        ctx.fillStyle = '#b5b0a8'
        ctx.font = '8px monospace'
        ctx.fillText('<>', assetX + 2, assetY + 9)
      }
    }

    // Asset count indicator
    if (assetCount > 0) {
      ctx.fillStyle = NIER_COLORS.textDim
      ctx.font = '9px -apple-system, sans-serif'
      ctx.textAlign = 'right'
      ctx.fillText(`${assetCount} assets`, x + width - 8, y + height - 5)
    }

    // Border
    ctx.strokeStyle = NIER_COLORS.primary
    ctx.lineWidth = 2
    ctx.strokeRect(x, y, width, height)

    // Corner decorations
    const cl = 15
    ctx.fillStyle = NIER_COLORS.primary
    ctx.fillRect(x, y, cl, 2)
    ctx.fillRect(x, y, 2, cl)
    ctx.fillRect(x + width - cl, y, cl, 2)
    ctx.fillRect(x + width - 2, y, 2, cl)
    ctx.fillRect(x, y + height - 2, cl, 2)
    ctx.fillRect(x, y + height - cl, 2, cl)
    ctx.fillRect(x + width - cl, y + height - 2, cl, 2)
    ctx.fillRect(x + width - 2, y + height - cl, 2, cl)

    // Title
    ctx.fillStyle = NIER_COLORS.textMain
    ctx.font = 'bold 11px "Courier New", monospace'
    ctx.textAlign = 'center'
    ctx.fillText('[ AGENTS ]', x + width / 2, y + 15)
  }, [])

  // Draw data connection line between API platform and Agent Room
  const drawDataLine = useCallback((
    ctx: CanvasRenderingContext2D,
    platformRight: number,
    platformCenterY: number,
    roomLeft: number,
    roomCenterY: number,
    frame: number
  ) => {
    // Main connection line
    ctx.strokeStyle = NIER_COLORS.primaryDim
    ctx.lineWidth = 2
    ctx.setLineDash([])
    ctx.beginPath()
    ctx.moveTo(platformRight, platformCenterY)
    ctx.lineTo(roomLeft, roomCenterY)
    ctx.stroke()

    // Data flow direction indicators (small arrows)
    const dx = roomLeft - platformRight
    const dy = roomCenterY - platformCenterY
    const len = Math.sqrt(dx * dx + dy * dy)

    // Packets flowing TO API (request)
    const packetsToApi = 4
    for (let i = 0; i < packetsToApi; i++) {
      const t = ((frame * 0.015 + i / packetsToApi) % 1)
      const px = roomLeft - dx * t
      const py = roomCenterY - dy * t

      ctx.fillStyle = NIER_COLORS.accent
      ctx.beginPath()
      ctx.arc(px, py, 4, 0, Math.PI * 2)
      ctx.fill()
    }

    // Packets flowing FROM API (response)
    const packetsFromApi = 4
    for (let i = 0; i < packetsFromApi; i++) {
      const t = ((frame * 0.012 + i / packetsFromApi + 0.5) % 1)
      const px = platformRight + dx * t
      const py = platformCenterY + dy * t

      ctx.fillStyle = '#7a7a7a'
      ctx.beginPath()
      ctx.rect(px - 3, py - 3, 6, 6)
      ctx.fill()
    }
  }, [])

  // Draw speech bubble - dynamic size based on text
  const drawSpeechBubble = useCallback((
    ctx: CanvasRenderingContext2D,
    x: number,
    y: number,
    text: string
  ) => {
    ctx.font = '12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'

    const padding = 8
    const lineHeight = 15

    // Measure actual text width
    const textWidth = ctx.measureText(text).width

    // Short text: single line, tight bubble
    // Long text: wrap to multiple lines
    const maxLineWidth = 180

    let lines: string[] = []
    if (textWidth <= maxLineWidth) {
      lines = [text]
    } else {
      let currentLine = ''
      for (const char of text.split('')) {
        const testLine = currentLine + char
        if (ctx.measureText(testLine).width > maxLineWidth) {
          if (currentLine) lines.push(currentLine)
          currentLine = char
        } else {
          currentLine = testLine
        }
      }
      if (currentLine) lines.push(currentLine)

      // Limit to 2 lines
      if (lines.length > 2) {
        lines = lines.slice(0, 2)
        lines[1] = lines[1].slice(0, -3) + '...'
      }
    }

    // Calculate bubble size based on actual content
    const actualTextWidth = Math.max(...lines.map(l => ctx.measureText(l).width))
    const bubbleWidth = actualTextWidth + padding * 2 + 4
    const bubbleHeight = lines.length * lineHeight + padding * 2

    const bubbleX = Math.round(x - bubbleWidth / 2)
    const bubbleY = Math.round(y - bubbleHeight - 10)

    // Background - NieR beige
    ctx.fillStyle = '#e8e4d8'
    ctx.fillRect(bubbleX, bubbleY, bubbleWidth, bubbleHeight)

    // Border
    ctx.strokeStyle = '#8a8070'
    ctx.lineWidth = 1
    ctx.strokeRect(bubbleX + 0.5, bubbleY + 0.5, bubbleWidth - 1, bubbleHeight - 1)

    // Pointer
    ctx.fillStyle = '#e8e4d8'
    ctx.beginPath()
    ctx.moveTo(x - 5, bubbleY + bubbleHeight)
    ctx.lineTo(x, bubbleY + bubbleHeight + 6)
    ctx.lineTo(x + 5, bubbleY + bubbleHeight)
    ctx.closePath()
    ctx.fill()

    // Text
    ctx.fillStyle = '#3a3530'
    ctx.textAlign = 'left'
    lines.forEach((line, i) => {
      ctx.fillText(line, bubbleX + padding, bubbleY + padding + (i + 1) * lineHeight - 3)
    })
  }, [])

  // Main render loop
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const render = () => {
      frameRef.current++
      const frame = frameRef.current

      // Reset transform and apply DPR scaling
      const dpr = window.devicePixelRatio || 1
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

      // Clear
      ctx.fillStyle = NIER_COLORS.background
      ctx.fillRect(0, 0, dimensions.width, dimensions.height)

      // Layout
      const platformX = dimensions.width * PLATFORM_X
      const platformWidth = dimensions.width * PLATFORM_WIDTH
      const roomX = dimensions.width * ROOM_X
      const roomWidth = dimensions.width * ROOM_WIDTH
      const roomY = dimensions.height * 0.08
      const roomHeight = dimensions.height * 0.84

      // Draw platforms and store their centers - dynamic based on SERVICE_CONFIG
      const services = Object.keys(SERVICE_CONFIG) as AIServiceType[]
      const numServices = services.length
      const platformGap = dimensions.height * 0.02
      const totalGapHeight = (numServices - 1) * platformGap
      const platformHeight = (roomHeight - totalGapHeight) / numServices
      const platformCenters: Record<AIServiceType, { centerX: number; centerY: number }> = {} as any

      services.forEach((service, index) => {
        const py = roomY + index * (platformHeight + platformGap)
        const hasWorkers = characters.some(c => c.status === 'working' && c.targetService === service)
        platformCenters[service] = drawPlatform(ctx, platformX, py, platformWidth, platformHeight, service, hasWorkers, frame)
      })

      // Count completed requests as assets
      const completedCount = characters.filter(c => c.request?.status === 'completed').length
      // Use a base count + simulation for demo
      const assetCount = Math.floor(frame / 300) + completedCount + 5

      // Draw room with assets
      drawRoom(ctx, roomX, roomY, roomWidth, roomHeight, assetCount, frame)

      // Update positions and collect working agents for data lines
      const positions = positionsRef.current
      const spriteSize = 26 * characterScale
      const workingAgents: { char: CharacterState; pos: CharacterPosition }[] = []

      // Count working agents per service for positioning
      const workingPerService: Record<AIServiceType, number> = {} as Record<AIServiceType, number>
      services.forEach(s => { workingPerService[s] = 0 })
      const workingIndexMap = new Map<string, number>()

      characters.forEach((char) => {
        if (char.status === 'working' && char.targetService) {
          workingIndexMap.set(char.agentId, workingPerService[char.targetService])
          workingPerService[char.targetService]++
        }
      })

      characters.forEach((char) => {
        const pos = positions.get(char.agentId)
        if (!pos) return

        const isWorking = char.status === 'working'

        // Update target
        if (isWorking && char.targetService) {
          const pc = platformCenters[char.targetService]
          const workingIndex = workingIndexMap.get(char.agentId) || 0
          const totalWorking = workingPerService[char.targetService]

          // Position along the line (right side of platform), spread vertically to avoid overlap
          const lineX = platformX + platformWidth + 20
          const spreadY = totalWorking > 1 ? (workingIndex - (totalWorking - 1) / 2) * 25 : 0
          pos.targetX = lineX
          pos.targetY = pc.centerY + spreadY
          pos.wasWorking = true
          workingAgents.push({ char, pos })
        } else {
          // Just finished working - immediately set target back to room
          if (pos.wasWorking) {
            pos.targetX = roomX + 20 + Math.random() * (roomWidth - 40)
            pos.targetY = roomY + 30 + Math.random() * (roomHeight - 60)
            pos.wanderTimer = 2000 + Math.random() * 3000
            pos.wasWorking = false
          } else {
            // Normal wandering
            pos.wanderTimer -= 16
            if (pos.wanderTimer <= 0) {
              let newX, newY
              let attempts = 0
              do {
                newX = roomX + 20 + Math.random() * (roomWidth - 40)
                newY = roomY + 30 + Math.random() * (roomHeight - 60)
                attempts++
              } while (attempts < 10 && isOverlapping(newX, newY, char.agentId, positions, 30))

              pos.targetX = newX
              pos.targetY = newY
              pos.wanderTimer = 3000 + Math.random() * 4000
            }
          }
        }

        // Move - faster return speed when just finished working
        const justReturning = !isWorking && Math.abs(pos.x - pos.targetX) > 50
        const speed = isWorking ? 0.08 : (justReturning ? 0.12 : 0.025)
        pos.x += (pos.targetX - pos.x) * speed
        pos.y += (pos.targetY - pos.y) * speed
        // Fast rotation when working, slow when idle
        pos.rotation += isWorking ? 0.15 : 0.01
      })

      // Helper to check overlap
      function isOverlapping(x: number, y: number, excludeId: string, positions: Map<string, CharacterPosition>, minDist: number): boolean {
        for (const [id, p] of positions) {
          if (id === excludeId) continue
          const dist = Math.sqrt((x - p.x) ** 2 + (y - p.y) ** 2)
          if (dist < minDist) return true
        }
        return false
      }

      // Draw data lines between active platforms and Agent Room
      const activeServices = new Set<AIServiceType>()
      workingAgents.forEach(({ char, pos }) => {
        if (char.targetService) {
          const distToTarget = Math.sqrt(Math.pow(pos.x - pos.targetX, 2) + Math.pow(pos.y - pos.targetY, 2))
          // Mark service as active when agent is close to platform
          if (distToTarget < 50) {
            activeServices.add(char.targetService)
          }
        }
      })

      // Draw connection lines from each active platform to Agent Room
      activeServices.forEach((service) => {
        const pc = platformCenters[service]
        const platformRightEdge = platformX + platformWidth
        drawDataLine(ctx, platformRightEdge, pc.centerY, roomX, roomY + roomHeight / 2, frame)
      })

      // Draw characters
      characters.forEach((char) => {
        const pos = positions.get(char.agentId)
        if (!pos) return

        const spiritType = AGENT_MODEL_MAP[char.agentType] || 'spirit_light'
        const isWorking = char.status === 'working'

        drawSprite(ctx, pos.x, pos.y, spiritType, spriteSize, isWorking, frame, pos.rotation)

        // Agent name below sprite
        ctx.font = '10px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'
        ctx.fillStyle = NIER_COLORS.textDim
        ctx.textAlign = 'center'
        const agentName = char.agentType.replace(/_/g, ' ').toUpperCase()
        ctx.fillText(agentName, pos.x, pos.y + spriteSize / 2 + 12)

        // Speech bubble - dynamic size
        if (isWorking && char.request) {
          drawSpeechBubble(ctx, pos.x, pos.y - spriteSize / 2, char.request.input)
        }
      })

      // HUD
      ctx.fillStyle = NIER_COLORS.textDim
      ctx.font = '10px "Courier New", monospace'
      ctx.textAlign = 'left'
      ctx.fillText(`AGENTS: ${characters.length}`, 10, dimensions.height - 8)
      ctx.fillText(`ACTIVE: ${workingAgents.length}`, 90, dimensions.height - 8)

      animationRef.current = requestAnimationFrame(render)
    }

    render()

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current)
      }
    }
  }, [characters, dimensions, characterScale, drawSprite, drawPlatform, drawRoom, drawDataLine, drawSpeechBubble])

  // Handle click
  const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!onCharacterClick) return

    const canvas = canvasRef.current
    if (!canvas) return

    const rect = canvas.getBoundingClientRect()
    const x = e.clientX - rect.left
    const y = e.clientY - rect.top
    const spriteSize = 26 * characterScale

    const positions = positionsRef.current
    for (const char of characters) {
      const pos = positions.get(char.agentId)
      if (!pos) continue

      const dist = Math.sqrt(Math.pow(x - pos.x, 2) + Math.pow(y - pos.y, 2))
      if (dist < spriteSize / 2 + 12) {
        onCharacterClick(char)
        return
      }
    }
  }, [characters, onCharacterClick, characterScale])

  return (
    <div ref={containerRef} className="w-full h-full" style={{ backgroundColor: '#d4cdb8' }}>
      <canvas
        ref={canvasRef}
        onClick={handleClick}
        className="cursor-pointer"
      />
    </div>
  )
}
