/**
 *Strategy Map Configuration
 *Centralized configuration for all visual and physics parameters
 */

export const PHYSICS={
  SPRING_STIFFNESS: 0.025,
  DAMPING: 0.92,
  MIN_VELOCITY: 0.01,
  EPSILON: 0.001,
  REPULSION_RADIUS: 50,
  AVOIDANCE_STRENGTH: 0.4,
  PARTICLE_FRICTION: 0.98,
} as const

export const LAYOUT={
  AI_ZONE_Y: 0.12,
  USER_ZONE_Y: 0.88,
  WORK_ZONE_TOP: 0.22,
  WORK_ZONE_BOTTOM: 0.72,
  LEADER_SPACING_MAX: 180,
  LEADER_OFFSET_Y: 40,
  CHILD_SPREAD_FACTOR: 45,
  CHILD_SPREAD_MAX: 300,
  CHILD_VERTICAL_GAP: 70,
  CHILD_ROW_GAP: 55,
  APPROVAL_QUEUE_SPACING: 55,
  APPROVAL_QUEUE_OFFSET_Y: 70,
  AI_ORBIT_RADIUS_BASE: 65,
  AI_ORBIT_RADIUS_STEP: 35,
  AI_ORBIT_ANGLE_SPREAD: Math.PI*0.7,
  MARGIN_X: 100,
} as const

export const TIMING={
  SPAWN_DURATION_MS: 800,
  SPAWN_PARTICLE_COUNT: 10,
  DESPAWN_PARTICLE_COUNT: 6,
  PACKET_SPAWN_INTERVAL: 25,
  PACKET_SPEED: 0.035,
  PACKET_ARRIVAL_PARTICLES: 4,
  PACKET_ARRIVAL_SPREAD: 1.8,
  PARTICLE_GRAVITY: 0.12,
  PARTICLE_INITIAL_LIFE: 35,
  SPAWN_PARTICLE_SPREAD: 3.5,
  DESPAWN_PARTICLE_SPREAD: 2.5,
} as const

export const ANIMATION={
  AI_PULSE_SPEED: 0.04,
  AI_PULSE_AMPLITUDE: 0.025,
  USER_ALERT_SPEED: 0.07,
  USER_ALERT_BASE: 0.18,
  USER_ALERT_AMPLITUDE: 0.12,
  BUBBLE_FLOAT_SPEED: 0.055,
  BUBBLE_FLOAT_AMPLITUDE: 1.8,
  AGENT_BOB_SPEED: 0.08,
  AGENT_BOB_AMPLITUDE: 1.2,
  AGENT_WORK_GLOW_SPEED: 0.1,
  AGENT_WORK_GLOW_BASE: 0.12,
  AGENT_WORK_GLOW_AMPLITUDE: 0.08,
  WAITING_DASH_SPEED: 0.25,
  PENDING_ZZZ_SPEED: 0.05,
  PENDING_ZZZ_AMPLITUDE: 1.2,
  SPAWN_GLOW_SHRINK: 0.6,
  SPAWN_RING_COUNT: 3,
  SPAWN_RING_INTERVAL: 0.33,
  SPAWN_RING_EXPAND_SPEED: 0.025,
  SPAWN_PARTICLE_RISE_SPEED: 1.5,
  SPAWN_PARTICLE_FADE_SPEED: 0.02,
} as const

export const SIZES={
  AI_NODE_RADIUS: 38,
  AI_BADGE_RADIUS: 13,
  AI_BADGE_OFFSET: 0.72,
  USER_NODE_RADIUS: 34,
  USER_ALERT_BASE_OFFSET: 18,
  USER_ALERT_QUEUE_FACTOR: 2.5,
  USER_GRADIENT_OFFSET_Y: 6,
  AGENT_SCALE: 0.85,
  AGENT_OFFSET_Y: 8,
  AGENT_LABEL_OFFSET_Y: 19,
  AGENT_WORK_GLOW_RADIUS: 32,
  AGENT_WAITING_CIRCLE_RADIUS: 26,
  AGENT_SPAWN_GLOW_RADIUS: 45,
  PENDING_ZZZ_OFFSET_X: 14,
  PENDING_ZZZ_OFFSET_Y: 14,
  BUBBLE_OFFSET_Y: 40,
  BUBBLE_MAX_WIDTH: 140,
  BUBBLE_HEIGHT: 20,
  BUBBLE_PADDING: 14,
  BUBBLE_MIN_WIDTH: 48,
  BUBBLE_BORDER_RADIUS: 3,
  BUBBLE_TAIL_WIDTH: 3,
  BUBBLE_TAIL_HEIGHT: 4,
  PACKET_OUTER_RADIUS: 7,
  PACKET_INNER_RADIUS: 2.5,
  WAITING_DASH_ON: 4,
  WAITING_DASH_OFF: 3,
  GRID_SIZE: 40,
  GRID_DOT_SIZE: 1.5,
} as const

export const COLORS={
  BACKGROUND: '#E8E4D4',
  TEXT_PRIMARY: '#454138',
  TEXT_SECONDARY: '#6B6558',
  TEXT_MUTED: '#9A9080',

  INSTRUCTION: '#5080B0',
  CONFIRM: '#C49060',
  DELIVERY: '#60A060',
  AI_REQUEST: '#9060B0',
  USER_CONTACT: '#B05050',

  USER_NODE_INNER: '#C85858',
  USER_NODE_OUTER: '#A04848',
  USER_NODE_BORDER: '#803838',

  SPAWN_GLOW: 'rgba(255, 240, 180, 0.7)',
  SPAWN_GLOW_END: 'rgba(255, 240, 180, 0)',
  SPAWN_PARTICLE: '#FFD080',
  DESPAWN_PARTICLE: '#888888',

  BUBBLE_DEFAULT_BG: '#F8F6F0',
  BUBBLE_DEFAULT_BORDER: '#454138',
  BUBBLE_SUCCESS_BG: '#E6F4E6',
  BUBBLE_SUCCESS_BORDER: '#5A9A5A',
  BUBBLE_QUESTION_BG: '#FFF6E6',
  BUBBLE_QUESTION_BORDER: '#C49060',
  BUBBLE_WARNING_BG: '#FFE8E8',
  BUBBLE_WARNING_BORDER: '#B05050',
} as const

export const ZOOM={
  MIN: 0.35,
  MAX: 2.8,
  STEP: 0.07,
} as const

export const AGENT_TIERS={
  ORCHESTRATOR: {
    scale: 1.2,
    hasFrame: false,
    summonEffect: 'magicCircle' as const,
  },
  DIRECTOR: {
    scale: 1.0,
    hasFrame: true,
    summonEffect: 'warpGate' as const,
  },
  LEADER: {
    scale: 1.0,
    hasFrame: true,
    summonEffect: 'warpGate' as const,
  },
  WORKER: {
    scale: 0.85,
    hasFrame: false,
    summonEffect: 'splitMerge' as const,
  },
} as const

export const FRAME_CONFIG={
  BORDER_RADIUS: 8,
  BORDER_WIDTH: 1.5,
  BORDER_COLOR: 0x8A7A6A,
  BORDER_ALPHA: 0.6,
  FILL_COLOR: 0xF5F0E8,
  FILL_ALPHA: 0.15,
  MIN_WIDTH: 150,
  MIN_HEIGHT: 100,
  PADDING: 20,
  MAX_VISIBLE_CHILDREN: 3,
  BADGE_SIZE: 18,
  BADGE_OFFSET_X:-8,
  BADGE_OFFSET_Y:-8,
  COLLISION_PADDING: 10,
  PUSH_STRENGTH: 0.5,
} as const

export const ROAD_CONFIG={
  LANE_WIDTH: 10,
  LINE_COLOR: 0x9A8A7A,
  LINE_ALPHA: 0.25,
  CENTER_LINE_WIDTH: 0.5,
  LANE_LINE_WIDTH: 1.5,
  SEED_SPACING: 60,
  OBSTACLE_MARGIN: 40,
  INTERSECTION_RADIUS: 8,
} as const

export const SUMMON_EFFECTS={
  MAGIC_CIRCLE: {
    duration: 2000,
    outerRingRadius: 60,
    innerRingRadius: 40,
    rotationSpeed: 0.02,
    particleCount: 16,
    glowColor: 0xD4A574,
    glowAlpha: 0.6,
  },
  WARP_GATE: {
    duration: 1500,
    width: 80,
    height: 50,
    expandSpeed: 0.04,
    portalColor: 0x4A3A5A,
    borderColor: 0x8A6AAA,
    particleCount: 12,
  },
  LIGHTNING: {
    duration: 800,
    boltCount: 3,
    segmentCount: 8,
    maxOffset: 25,
    boltWidth: 2,
    boltColor: 0xFFEEAA,
    glowColor: 0xFFFFCC,
    flashDuration: 100,
  },
  SPLIT_MERGE: {
    duration: 1000,
    streamCount: 5,
    streamSpeed: 0.06,
    streamColor: 0xC49060,
    connectionColor: 0xE8C090,
    connectionAlpha: 0.5,
  },
} as const

export const AI_SERVICES_CONFIG=[
  { id: 'claude',name: 'Claude',color: '#D97706' },
  { id: 'openai',name: 'OpenAI',color: '#10B981' },
  { id: 'gemini',name: 'Gemini',color: '#3B82F6' },
] as const

export type AIServiceId=typeof AI_SERVICES_CONFIG[number]['id']
