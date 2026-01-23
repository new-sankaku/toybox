import Phaser from 'phaser'
import { SIZES,COLORS,ANIMATION } from '../../../strategyMapConfig'
import type { PhaserMapAgent } from '../../types/phaserTypes'
import { generateCharacterTexture,getAgentDisplayConfig } from '../utils/CharacterTextures'
import { BubbleContainer } from './BubbleContainer'

interface SpawnParticle {
 x: number
 y: number
 vx: number
 vy: number
 alpha: number
 size: number
}

export class AgentSprite extends Phaser.GameObjects.Container {
 private sprite: Phaser.GameObjects.Sprite
 private label: Phaser.GameObjects.Text
 private workGlow: Phaser.GameObjects.Graphics
 private spawnGlow: Phaser.GameObjects.Graphics
 private spawnRings: Phaser.GameObjects.Graphics
 private spawnParticleGraphics: Phaser.GameObjects.Graphics
 private waitingCircle: Phaser.GameObjects.Graphics
 private pendingZzz: Phaser.GameObjects.Text
 private bubble: BubbleContainer|null=null

 private agentData: PhaserMapAgent
 private frameCount: number=0
 private spawnParticles: SpawnParticle[]=[]
 private spawnRingProgress: number[]=[]

 constructor(scene: Phaser.Scene,agent: PhaserMapAgent,x: number,y: number) {
  super(scene,x,y)

  this.agentData=agent

  this.spawnGlow=scene.add.graphics()
  this.add(this.spawnGlow)

  this.spawnRings=scene.add.graphics()
  this.add(this.spawnRings)

  this.spawnParticleGraphics=scene.add.graphics()
  this.add(this.spawnParticleGraphics)

  this.workGlow=scene.add.graphics()
  this.add(this.workGlow)

  this.initSpawnEffects()

  this.waitingCircle=scene.add.graphics()
  this.add(this.waitingCircle)

  const textureKey=generateCharacterTexture(scene,agent.type,agent.status==='running',0)
  this.sprite=scene.add.sprite(0,-SIZES.AGENT_OFFSET_Y,textureKey)
  this.sprite.setScale(SIZES.AGENT_SCALE)
  this.add(this.sprite)

  const config=getAgentDisplayConfig(agent.type)
  this.label=scene.add.text(0,SIZES.AGENT_LABEL_OFFSET_Y,config.label,{
   fontFamily: 'system-ui, sans-serif',
   fontSize: '14px',
   fontStyle: 'bold',
   color: '#222222',
  })
  this.label.setOrigin(0.5,0)
  this.label.setResolution(2)
  this.add(this.label)

  this.pendingZzz=scene.add.text(
   SIZES.PENDING_ZZZ_OFFSET_X,
   -SIZES.PENDING_ZZZ_OFFSET_Y,
   'zzz',
   {
    fontFamily: 'system-ui, sans-serif',
    fontSize: '11px',
    fontStyle: 'italic',
    color: COLORS.TEXT_SECONDARY,
   }
)
  this.pendingZzz.setOrigin(0,0.5)
  this.pendingZzz.setResolution(2)
  this.pendingZzz.setVisible(false)
  this.add(this.pendingZzz)

  if (agent.bubble) {
   this.bubble=new BubbleContainer(scene,0,-SIZES.BUBBLE_OFFSET_Y,agent.bubble,agent.bubbleType)
   this.add(this.bubble)
  }

  scene.add.existing(this)
  this.updateVisuals()
 }

 updateAgent(agent: PhaserMapAgent): void {
  const statusChanged=this.agentData.status!==agent.status
  const bubbleChanged=this.agentData.bubble!==agent.bubble

  this.agentData=agent

  if (statusChanged||bubbleChanged) {
   this.updateVisuals()
  }

  if (bubbleChanged) {
   if (this.bubble) {
    this.bubble.destroy()
    this.bubble=null
   }
   if (agent.bubble) {
    this.bubble=new BubbleContainer(this.scene,0,-SIZES.BUBBLE_OFFSET_Y,agent.bubble,agent.bubbleType)
    this.add(this.bubble)
   }
  }
 }

 update(): void {
  this.frameCount++
  const { status,spawnProgress }=this.agentData
  const isSpawning=spawnProgress<1

  const textureKey=generateCharacterTexture(
   this.scene,
   this.agentData.type,
   status==='running',
   this.frameCount
)
  this.sprite.setTexture(textureKey)

  let alpha=isSpawning ? spawnProgress : 1
  if (status==='failed'||status==='blocked') {
   alpha*=0.5
  }
  this.sprite.setAlpha(alpha)
  this.label.setAlpha(1)

  if (isSpawning) {
   const glowSize=SIZES.AGENT_SPAWN_GLOW_RADIUS*(1-spawnProgress*ANIMATION.SPAWN_GLOW_SHRINK)
   this.spawnGlow.clear()
   this.spawnGlow.fillStyle(0xC49060,0.4*(1-spawnProgress))
   this.spawnGlow.fillCircle(0,-SIZES.AGENT_OFFSET_Y,glowSize)
   this.spawnGlow.setVisible(true)
   this.updateSpawnEffects()
  } else {
   this.spawnGlow.setVisible(false)
   this.spawnRings.setVisible(false)
   this.spawnParticleGraphics.setVisible(false)
  }

  if (status==='running') {
   const intensity=ANIMATION.AGENT_WORK_GLOW_BASE+
    Math.sin(this.frameCount*ANIMATION.AGENT_WORK_GLOW_SPEED)*ANIMATION.AGENT_WORK_GLOW_AMPLITUDE
   this.workGlow.clear()
   this.workGlow.fillStyle(0xC49060,intensity)
   this.workGlow.fillCircle(0,-SIZES.AGENT_OFFSET_Y,SIZES.AGENT_WORK_GLOW_RADIUS)
   this.workGlow.setVisible(true)

   const bobY=Math.sin(this.frameCount*ANIMATION.AGENT_BOB_SPEED)*ANIMATION.AGENT_BOB_AMPLITUDE
   this.sprite.y=-SIZES.AGENT_OFFSET_Y+bobY
  } else {
   this.workGlow.setVisible(false)
   this.sprite.y=-SIZES.AGENT_OFFSET_Y
  }

  if (status==='waiting_approval') {
   this.waitingCircle.clear()
   this.waitingCircle.lineStyle(1.5,0x9A7A5A)

   const dashLength=SIZES.WAITING_DASH_ON+SIZES.WAITING_DASH_OFF
   const circumference=2*Math.PI*SIZES.AGENT_WAITING_CIRCLE_RADIUS
   const dashCount=Math.floor(circumference/dashLength)
   const offset=-this.frameCount*ANIMATION.WAITING_DASH_SPEED

   for (let i=0;i<dashCount;i++) {
    const startAngle=(i*dashLength/circumference)*Math.PI*2+offset
    const endAngle=startAngle+(SIZES.WAITING_DASH_ON/circumference)*Math.PI*2
    this.waitingCircle.beginPath()
    this.waitingCircle.arc(0,-SIZES.AGENT_OFFSET_Y,SIZES.AGENT_WAITING_CIRCLE_RADIUS,startAngle,endAngle)
    this.waitingCircle.strokePath()
   }
   this.waitingCircle.setVisible(true)
  } else {
   this.waitingCircle.setVisible(false)
  }

  if (status==='pending') {
   const zOffset=Math.sin(this.frameCount*ANIMATION.PENDING_ZZZ_SPEED)*ANIMATION.PENDING_ZZZ_AMPLITUDE
   this.pendingZzz.y=-SIZES.PENDING_ZZZ_OFFSET_Y+zOffset
   this.pendingZzz.setVisible(true)
  } else {
   this.pendingZzz.setVisible(false)
  }

  if (this.bubble) {
   this.bubble.update(this.frameCount)
  }
 }

 private updateVisuals(): void {
  const { status }=this.agentData

  this.workGlow.setVisible(status==='running')
  this.waitingCircle.setVisible(status==='waiting_approval')
  this.pendingZzz.setVisible(status==='pending')
 }

 private initSpawnEffects(): void {
  for (let i=0;i<ANIMATION.SPAWN_RING_COUNT;i++) {
   this.spawnRingProgress.push(i*ANIMATION.SPAWN_RING_INTERVAL)
  }
  for (let i=0;i<8;i++) {
   const angle=Math.random()*Math.PI*2
   const speed=0.5+Math.random()*1
   this.spawnParticles.push({
    x: 0,
    y: 0,
    vx: Math.cos(angle)*speed,
    vy:-Math.abs(Math.sin(angle)*speed)-ANIMATION.SPAWN_PARTICLE_RISE_SPEED,
    alpha: 1,
    size: 2+Math.random()*2,
   })
  }
 }

 private updateSpawnEffects(): void {
  const { spawnProgress }=this.agentData
  if (spawnProgress>=1) {
   this.spawnRings.setVisible(false)
   this.spawnParticleGraphics.setVisible(false)
   return
  }

  this.spawnRings.clear()
  this.spawnRings.setVisible(true)
  for (let i=0;i<this.spawnRingProgress.length;i++) {
   this.spawnRingProgress[i]+=ANIMATION.SPAWN_RING_EXPAND_SPEED
   if (this.spawnRingProgress[i]>1) {
    this.spawnRingProgress[i]-=1
   }
   const progress=this.spawnRingProgress[i]
   const radius=10+progress*40
   const alpha=(1-progress)*0.5*(1-spawnProgress)
   this.spawnRings.lineStyle(1.5,0xC49060,alpha)
   this.spawnRings.strokeCircle(0,-SIZES.AGENT_OFFSET_Y,radius)
  }

  this.spawnParticleGraphics.clear()
  this.spawnParticleGraphics.setVisible(true)
  for (const p of this.spawnParticles) {
   p.x+=p.vx
   p.y+=p.vy
   p.vy+=0.03
   p.alpha-=ANIMATION.SPAWN_PARTICLE_FADE_SPEED
   if (p.alpha<=0) {
    const angle=Math.random()*Math.PI*2
    const speed=0.5+Math.random()*1
    p.x=0
    p.y=0
    p.vx=Math.cos(angle)*speed
    p.vy=-Math.abs(Math.sin(angle)*speed)-ANIMATION.SPAWN_PARTICLE_RISE_SPEED
    p.alpha=1-spawnProgress
   }
   this.spawnParticleGraphics.fillStyle(0xC49060,p.alpha*(1-spawnProgress))
   this.spawnParticleGraphics.fillCircle(p.x,p.y-SIZES.AGENT_OFFSET_Y,p.size)
  }
 }

 getAgentId(): string {
  return this.agentData.id
 }

 destroy(fromScene?: boolean): void {
  if (this.bubble) {
   this.bubble.destroy()
  }
  super.destroy(fromScene)
 }
}
