import { useRef, useEffect, useCallback, useMemo } from 'react'
import type {
  MapAgent,
  AIService,
  UserNode,
  Connection,
  Particle,
  DataPacket,
  AgentPositionState,
  Vec2,
  ConnectionType,
  BubbleType,
} from './strategyMapTypes'
import {
  PHYSICS,
  LAYOUT,
  TIMING,
  SIZES,
  COLORS,
  ZOOM,
} from './strategyMapConfig'
import { drawPixelCharacter, getAgentDisplayConfig } from '../ai-game/pixelCharacters'

interface Props {
  agents: readonly MapAgent[]
  aiServices: readonly AIService[]
  user: UserNode
  connections: readonly Connection[]
  width: number
  height: number
}

interface RenderState {
  positions: Map<string, AgentPositionState>
  particles: Particle[]
  packets: DataPacket[]
  frame: number
}

interface CanvasState {
  zoom: number
  panX: number
  panY: number
  isDragging: boolean
  dragStartX: number
  dragStartY: number
}

const CONNECTION_COLORS: Record<ConnectionType, string> = {
  instruction: COLORS.INSTRUCTION,
  confirm: COLORS.CONFIRM,
  delivery: COLORS.DELIVERY,
  'ai-request': COLORS.AI_REQUEST,
  'user-contact': COLORS.USER_CONTACT,
}

const BUBBLE_STYLES: Record<BubbleType, { bg: string; border: string }> = {
  info: { bg: COLORS.BUBBLE_DEFAULT_BG, border: COLORS.BUBBLE_DEFAULT_BORDER },
  success: { bg: COLORS.BUBBLE_SUCCESS_BG, border: COLORS.BUBBLE_SUCCESS_BORDER },
  question: { bg: COLORS.BUBBLE_QUESTION_BG, border: COLORS.BUBBLE_QUESTION_BORDER },
  warning: { bg: COLORS.BUBBLE_WARNING_BG, border: COLORS.BUBBLE_WARNING_BORDER },
}

function createParticle(x: number, y: number, color: string, spread: number): Particle {
  const angle = Math.random() * Math.PI * 2
  const speed = Math.random() * spread + spread * 0.5
  return {
    x,
    y,
    vx: Math.cos(angle) * speed,
    vy: Math.sin(angle) * speed,
    life: TIMING.PARTICLE_INITIAL_LIFE,
    maxLife: TIMING.PARTICLE_INITIAL_LIFE,
    color,
    size: 2 + Math.random() * 2,
  }
}

function computeAgentTarget(
  agent: MapAgent,
  allAgents: readonly MapAgent[],
  positions: Map<string, AgentPositionState>,
  aiServices: readonly AIService[],
  user: UserNode,
  width: number,
  height: number
): Vec2 {
  const userZoneY = height * LAYOUT.USER_ZONE_Y
  const workZoneTop = height * LAYOUT.WORK_ZONE_TOP

  if (agent.status === 'waiting_approval') {
    const waiting = allAgents.filter(a => a.status === 'waiting_approval')
    const idx = waiting.findIndex(a => a.id === agent.id)
    const count = waiting.length
    const spacing = Math.min(LAYOUT.APPROVAL_QUEUE_SPACING, (width * 0.75) / Math.max(count, 1))
    const startX = user.x - ((count - 1) * spacing) / 2
    return { x: startX + idx * spacing, y: userZoneY - 70 }
  }

  if (agent.aiTarget && agent.status === 'running') {
    const ai = aiServices.find(s => s.id === agent.aiTarget)
    if (ai) {
      const atThisAI = allAgents.filter(a => a.aiTarget === agent.aiTarget && a.status === 'running')
      const idx = atThisAI.findIndex(a => a.id === agent.id)
      const count = atThisAI.length
      const angleSpread = LAYOUT.AI_ORBIT_ANGLE_SPREAD
      const baseAngle = Math.PI / 2
      const angle = count === 1
        ? baseAngle
        : baseAngle - angleSpread / 2 + (angleSpread * idx) / (count - 1)
      const layer = Math.floor(idx / 6)
      const radius = LAYOUT.AI_ORBIT_RADIUS_BASE + layer * LAYOUT.AI_ORBIT_RADIUS_STEP
      return {
        x: ai.x + Math.cos(angle) * radius,
        y: ai.y + Math.sin(angle) * radius,
      }
    }
  }

  if (agent.parentId) {
    const parentPos = positions.get(agent.parentId)
    if (parentPos) {
      const siblings = allAgents.filter(a => a.parentId === agent.parentId)
      const idx = siblings.findIndex(a => a.id === agent.id)
      const count = siblings.length
      const spread = Math.min(count * 45, LAYOUT.CHILD_SPREAD_MAX)
      const col = idx % 6
      const row = Math.floor(idx / 6)
      const colCount = Math.min(count, 6)
      const startX = parentPos.x - spread / 2
      const xStep = spread / Math.max(colCount - 1, 1)
      return {
        x: startX + col * xStep,
        y: parentPos.y + LAYOUT.CHILD_VERTICAL_GAP + row * 55,
      }
    }
  }

  const leaders = allAgents.filter(a => !a.parentId)
  const idx = leaders.findIndex(a => a.id === agent.id)
  const count = leaders.length
  const availableWidth = width - LAYOUT.MARGIN_X * 2
  const spacing = Math.min(LAYOUT.LEADER_SPACING_MAX, availableWidth / Math.max(count, 1))
  const startX = width / 2 - ((count - 1) * spacing) / 2
  return { x: startX + idx * spacing, y: workZoneTop + 40 }
}

function updatePhysics(pos: AgentPositionState): void {
  const dx = pos.targetX - pos.x
  const dy = pos.targetY - pos.y

  pos.vx += dx * PHYSICS.SPRING_STIFFNESS
  pos.vy += dy * PHYSICS.SPRING_STIFFNESS
  pos.vx *= PHYSICS.DAMPING
  pos.vy *= PHYSICS.DAMPING

  if (Math.abs(pos.vx) < PHYSICS.MIN_VELOCITY) pos.vx = 0
  if (Math.abs(pos.vy) < PHYSICS.MIN_VELOCITY) pos.vy = 0

  pos.x += pos.vx
  pos.y += pos.vy
}

function renderAIService(
  ctx: CanvasRenderingContext2D,
  ai: AIService,
  frame: number,
  activeCount: number
): void {
  const { x, y, name, color } = ai
  const pulse = 1 + Math.sin(frame * 0.04) * 0.025
  const radius = SIZES.AI_NODE_RADIUS * pulse

  const glowGradient = ctx.createRadialGradient(x, y, radius * 0.4, x, y, radius * 1.6)
  glowGradient.addColorStop(0, color + '28')
  glowGradient.addColorStop(1, color + '00')
  ctx.fillStyle = glowGradient
  ctx.beginPath()
  ctx.arc(x, y, radius * 1.6, 0, Math.PI * 2)
  ctx.fill()

  ctx.fillStyle = color
  ctx.beginPath()
  ctx.arc(x, y, radius, 0, Math.PI * 2)
  ctx.fill()

  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 13px system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(name, x, y)

  if (activeCount > 0) {
    const badgeX = x + radius * 0.72
    const badgeY = y - radius * 0.72
    ctx.fillStyle = color
    ctx.beginPath()
    ctx.arc(badgeX, badgeY, 13, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillStyle = '#ffffff'
    ctx.font = 'bold 10px system-ui, sans-serif'
    ctx.fillText(String(activeCount), badgeX, badgeY)
  }
}

function renderUserNode(
  ctx: CanvasRenderingContext2D,
  user: UserNode,
  frame: number
): void {
  const { x, y, queue } = user
  const hasQueue = queue.length > 0

  if (hasQueue) {
    const alertIntensity = 0.18 + Math.sin(frame * 0.07) * 0.12
    ctx.fillStyle = `rgba(180, 60, 60, ${alertIntensity})`
    ctx.beginPath()
    ctx.arc(x, y, SIZES.USER_NODE_RADIUS + 18 + queue.length * 2.5, 0, Math.PI * 2)
    ctx.fill()
  }

  const gradient = ctx.createRadialGradient(x, y - 6, 0, x, y, SIZES.USER_NODE_RADIUS)
  gradient.addColorStop(0, COLORS.USER_NODE_INNER)
  gradient.addColorStop(1, COLORS.USER_NODE_OUTER)
  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(x, y, SIZES.USER_NODE_RADIUS, 0, Math.PI * 2)
  ctx.fill()

  ctx.strokeStyle = COLORS.USER_NODE_BORDER
  ctx.lineWidth = 2
  ctx.stroke()

  ctx.fillStyle = '#ffffff'
  ctx.font = 'bold 11px system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText('USER', x, y - 3)
  ctx.font = '9px system-ui, sans-serif'
  ctx.fillText('承認者', x, y + 10)
}

function renderBubble(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  text: string,
  type: BubbleType | null,
  frame: number
): void {
  ctx.save()

  const style = type ? BUBBLE_STYLES[type] : BUBBLE_STYLES.info
  const displayText = text.length > 18 ? text.slice(0, 16) + '…' : text

  ctx.font = '9px system-ui, sans-serif'
  const textWidth = ctx.measureText(displayText).width
  const w = Math.min(Math.max(textWidth + SIZES.BUBBLE_PADDING, 48), SIZES.BUBBLE_MAX_WIDTH)
  const h = SIZES.BUBBLE_HEIGHT
  const floatY = y + Math.sin(frame * 0.055) * 1.8

  ctx.shadowColor = 'rgba(0, 0, 0, 0.08)'
  ctx.shadowBlur = 3
  ctx.shadowOffsetY = 1

  ctx.fillStyle = style.bg
  ctx.strokeStyle = style.border
  ctx.lineWidth = 1

  ctx.beginPath()
  ctx.roundRect(x - w / 2, floatY - h / 2, w, h, 3)
  ctx.fill()
  ctx.shadowBlur = 0
  ctx.stroke()

  ctx.beginPath()
  ctx.moveTo(x - 3, floatY + h / 2)
  ctx.lineTo(x, floatY + h / 2 + 4)
  ctx.lineTo(x + 3, floatY + h / 2)
  ctx.closePath()
  ctx.fillStyle = style.bg
  ctx.fill()
  ctx.stroke()

  ctx.fillStyle = COLORS.TEXT_PRIMARY
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(displayText, x, floatY)

  ctx.restore()
}

function renderAgent(
  ctx: CanvasRenderingContext2D,
  agent: MapAgent,
  pos: AgentPositionState,
  frame: number
): void {
  const { x, y } = pos
  const { type, status, bubble, bubbleType, spawnProgress } = agent
  const isSpawning = spawnProgress < 1

  ctx.save()

  let alpha = isSpawning ? spawnProgress : 1
  if (status === 'failed' || status === 'blocked') {
    alpha *= 0.5
  }

  if (isSpawning) {
    const glowRadius = 45 * (1 - spawnProgress * 0.6)
    const glowGradient = ctx.createRadialGradient(x, y, 0, x, y, glowRadius)
    glowGradient.addColorStop(0, COLORS.SPAWN_GLOW)
    glowGradient.addColorStop(1, 'rgba(255, 240, 180, 0)')
    ctx.fillStyle = glowGradient
    ctx.beginPath()
    ctx.arc(x, y, glowRadius, 0, Math.PI * 2)
    ctx.fill()
  }

  ctx.globalAlpha = alpha

  if (status === 'running') {
    const intensity = 0.12 + Math.sin(frame * 0.1) * 0.08
    const workGlow = ctx.createRadialGradient(x, y, 0, x, y, 32)
    workGlow.addColorStop(0, `rgba(255, 200, 100, ${intensity})`)
    workGlow.addColorStop(1, 'rgba(255, 200, 100, 0)')
    ctx.fillStyle = workGlow
    ctx.beginPath()
    ctx.arc(x, y, 32, 0, Math.PI * 2)
    ctx.fill()
  }

  if (status === 'waiting_approval') {
    ctx.strokeStyle = COLORS.CONFIRM
    ctx.lineWidth = 1.5
    ctx.setLineDash([4, 3])
    ctx.lineDashOffset = -frame * 0.25
    ctx.beginPath()
    ctx.arc(x, y, 26, 0, Math.PI * 2)
    ctx.stroke()
    ctx.setLineDash([])
  }

  const bobY = status === 'running' ? Math.sin(frame * 0.08) * 1.2 : 0
  drawPixelCharacter(ctx, x, y - 8 + bobY, type, status === 'running', frame, SIZES.AGENT_SCALE)

  ctx.globalAlpha = 1
  const config = getAgentDisplayConfig(type)
  ctx.fillStyle = COLORS.TEXT_PRIMARY
  ctx.font = '9px system-ui, sans-serif'
  ctx.textAlign = 'center'
  ctx.fillText(config.label, x, y + 19)

  if (status === 'pending') {
    ctx.fillStyle = COLORS.TEXT_SECONDARY
    ctx.font = 'italic 8px system-ui, sans-serif'
    const zOffset = Math.sin(frame * 0.05) * 1.2
    ctx.fillText('zzz', x + 14, y - 14 + zOffset)
  }

  if (bubble) {
    renderBubble(ctx, x, y - 40, bubble, bubbleType, frame)
  }

  ctx.restore()
}

function renderPacket(ctx: CanvasRenderingContext2D, packet: DataPacket): void {
  const t = packet.progress
  const x = packet.fromX + (packet.toX - packet.fromX) * t
  const y = packet.fromY + (packet.toY - packet.fromY) * t

  const gradient = ctx.createRadialGradient(x, y, 0, x, y, SIZES.PACKET_OUTER_RADIUS)
  gradient.addColorStop(0, packet.color)
  gradient.addColorStop(1, packet.color + '00')

  ctx.fillStyle = gradient
  ctx.beginPath()
  ctx.arc(x, y, SIZES.PACKET_OUTER_RADIUS, 0, Math.PI * 2)
  ctx.fill()

  ctx.fillStyle = '#ffffff'
  ctx.beginPath()
  ctx.arc(x, y, SIZES.PACKET_INNER_RADIUS, 0, Math.PI * 2)
  ctx.fill()
}

function renderParticle(ctx: CanvasRenderingContext2D, particle: Particle): void {
  const alpha = particle.life / particle.maxLife
  const radius = particle.size * alpha

  ctx.globalAlpha = alpha
  ctx.fillStyle = particle.color
  ctx.beginPath()
  ctx.arc(particle.x, particle.y, radius, 0, Math.PI * 2)
  ctx.fill()
  ctx.globalAlpha = 1
}

export default function StrategyMapCanvas({
  agents,
  aiServices,
  user,
  connections,
  width,
  height,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  const renderStateRef = useRef<RenderState>({
    positions: new Map(),
    particles: [],
    packets: [],
    frame: 0,
  })

  const canvasStateRef = useRef<CanvasState>({
    zoom: 1,
    panX: 0,
    panY: 0,
    isDragging: false,
    dragStartX: 0,
    dragStartY: 0,
  })

  const agentIdsSet = useMemo(() => new Set(agents.map(a => a.id)), [agents])

  const spawnParticles = useCallback((
    x: number,
    y: number,
    color: string,
    count: number,
    spread: number
  ) => {
    const state = renderStateRef.current
    for (let i = 0; i < count; i++) {
      state.particles.push(createParticle(x, y, color, spread))
    }
  }, [])

  const spawnPacket = useCallback((
    fromX: number,
    fromY: number,
    toX: number,
    toY: number,
    color: string
  ) => {
    const state = renderStateRef.current
    state.packets.push({
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      fromX,
      fromY,
      toX,
      toY,
      color,
      progress: 0,
    })
  }, [])

  const updatePositions = useCallback(() => {
    const state = renderStateRef.current
    const { positions } = state

    for (const agent of agents) {
      const target = computeAgentTarget(
        agent,
        agents,
        positions,
        aiServices,
        user,
        width,
        height
      )

      let pos = positions.get(agent.id)
      if (!pos) {
        pos = {
          x: target.x,
          y: target.y,
          vx: 0,
          vy: 0,
          targetX: target.x,
          targetY: target.y,
        }
        positions.set(agent.id, pos)
        spawnParticles(target.x, target.y, '#FFD080', TIMING.SPAWN_PARTICLE_COUNT, 3.5)
      } else {
        pos.targetX = target.x
        pos.targetY = target.y
      }
    }

    positions.forEach((pos, id) => {
      if (!agentIdsSet.has(id)) {
        spawnParticles(pos.x, pos.y, '#888888', TIMING.DESPAWN_PARTICLE_COUNT, 2.5)
        positions.delete(id)
      }
    })

    positions.forEach(updatePhysics)
  }, [agents, aiServices, user, width, height, agentIdsSet, spawnParticles])

  const updateParticles = useCallback(() => {
    const state = renderStateRef.current
    state.particles = state.particles.filter(p => {
      p.x += p.vx
      p.y += p.vy
      p.vy += TIMING.PARTICLE_GRAVITY
      p.vx *= 0.98
      p.life--
      return p.life > 0
    })
  }, [])

  const updatePackets = useCallback(() => {
    const state = renderStateRef.current
    state.packets = state.packets.filter(p => {
      p.progress += TIMING.PACKET_SPEED
      if (p.progress >= 1) {
        spawnParticles(p.toX, p.toY, p.color, 4, 1.8)
        return false
      }
      return true
    })
  }, [spawnParticles])

  const spawnConnectionPackets = useCallback(() => {
    const state = renderStateRef.current
    const { positions } = state

    for (const conn of connections) {
      if (!conn.active) continue

      const fromPos = positions.get(conn.fromId)
      if (!fromPos) continue

      let toX = 0
      let toY = 0
      const toPos = positions.get(conn.toId)
      const toAI = aiServices.find(s => s.id === conn.toId)

      if (toPos) {
        toX = toPos.x
        toY = toPos.y
      } else if (toAI) {
        toX = toAI.x
        toY = toAI.y
      } else if (conn.toId === 'user') {
        toX = user.x
        toY = user.y
      } else {
        continue
      }

      const color = CONNECTION_COLORS[conn.type]
      spawnPacket(fromPos.x, fromPos.y, toX, toY, color)
    }
  }, [connections, aiServices, user, spawnPacket])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationId: number

    const render = () => {
      const state = renderStateRef.current
      const canvasState = canvasStateRef.current
      state.frame++

      updatePositions()
      updateParticles()
      updatePackets()

      if (state.frame % TIMING.PACKET_SPAWN_INTERVAL === 0) {
        spawnConnectionPackets()
      }

      ctx.fillStyle = COLORS.BACKGROUND
      ctx.fillRect(0, 0, width, height)

      ctx.save()
      ctx.translate(width / 2, height / 2)
      ctx.scale(canvasState.zoom, canvasState.zoom)
      ctx.translate(-width / 2 + canvasState.panX, -height / 2 + canvasState.panY)

      for (const packet of state.packets) {
        renderPacket(ctx, packet)
      }

      for (const ai of aiServices) {
        const activeCount = agents.filter(
          a => a.aiTarget === ai.id && a.status === 'running'
        ).length
        renderAIService(ctx, ai, state.frame, activeCount)
      }

      renderUserNode(ctx, user, state.frame)

      const sortedAgents = [...agents].sort((a, b) => {
        const posA = state.positions.get(a.id)
        const posB = state.positions.get(b.id)
        return (posA?.y ?? 0) - (posB?.y ?? 0)
      })

      for (const agent of sortedAgents) {
        const pos = state.positions.get(agent.id)
        if (pos) {
          renderAgent(ctx, agent, pos, state.frame)
        }
      }

      for (const particle of state.particles) {
        renderParticle(ctx, particle)
      }

      ctx.restore()

      animationId = requestAnimationFrame(render)
    }

    render()

    return () => cancelAnimationFrame(animationId)
  }, [
    agents,
    aiServices,
    user,
    width,
    height,
    updatePositions,
    updateParticles,
    updatePackets,
    spawnConnectionPackets,
  ])

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault()
    const state = canvasStateRef.current
    const factor = e.deltaY > 0 ? 1 - ZOOM.STEP : 1 + ZOOM.STEP
    state.zoom = Math.max(ZOOM.MIN, Math.min(ZOOM.MAX, state.zoom * factor))
  }, [])

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    const state = canvasStateRef.current
    state.isDragging = true
    state.dragStartX = e.clientX - state.panX
    state.dragStartY = e.clientY - state.panY
  }, [])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    const state = canvasStateRef.current
    if (!state.isDragging) return
    state.panX = e.clientX - state.dragStartX
    state.panY = e.clientY - state.dragStartY
  }, [])

  const handleMouseUp = useCallback(() => {
    canvasStateRef.current.isDragging = false
  }, [])

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="cursor-grab active:cursor-grabbing"
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUp}
      onMouseLeave={handleMouseUp}
    />
  )
}
