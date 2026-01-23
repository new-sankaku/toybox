import Phaser from 'phaser'
import { TIMING,PHYSICS,COLORS } from '../../../strategyMapConfig'

interface ParticleData {
 vx: number
 vy: number
 life: number
 maxLife: number
}

export class ParticleManager {
 private scene: Phaser.Scene
 private particles: Phaser.GameObjects.Graphics[]=[]
 private particleData: Map<Phaser.GameObjects.Graphics,ParticleData>=new Map()

 constructor(scene: Phaser.Scene) {
  this.scene=scene
 }

 private colorToNumber(color: string): number {
  if (color.startsWith('#')) {
   return parseInt(color.slice(1),16)
  }
  return 0x808080
 }

 spawnParticles(
  x: number,
  y: number,
  color: string|number,
  count: number,
  spread: number
): void {
  const colorNum=typeof color==='string' ? this.colorToNumber(color) : color

  for (let i=0;i<count;i++) {
   const angle=Math.random()*Math.PI*2
   const speed=Math.random()*spread+spread*0.5
   const size=1.5+Math.random()*1.5

   const graphics=this.scene.add.graphics()
   graphics.fillStyle(colorNum,1)
   graphics.fillCircle(0,0,size)
   graphics.setPosition(x,y)
   graphics.setDepth(100)

   const data: ParticleData={
    vx: Math.cos(angle)*speed,
    vy: Math.sin(angle)*speed,
    life: TIMING.PARTICLE_INITIAL_LIFE,
    maxLife: TIMING.PARTICLE_INITIAL_LIFE,
   }

   this.particles.push(graphics)
   this.particleData.set(graphics,data)
  }
 }

 spawnSpawnParticles(x: number,y: number): void {
  this.spawnParticles(
   x,y,
   COLORS.SPAWN_PARTICLE,
   TIMING.SPAWN_PARTICLE_COUNT,
   TIMING.SPAWN_PARTICLE_SPREAD
)
 }

 spawnDespawnParticles(x: number,y: number): void {
  this.spawnParticles(
   x,y,
   COLORS.DESPAWN_PARTICLE,
   TIMING.DESPAWN_PARTICLE_COUNT,
   TIMING.DESPAWN_PARTICLE_SPREAD
)
 }

 spawnPacketArrivalParticles(x: number,y: number,color: number): void {
  this.spawnParticles(
   x,y,
   color,
   TIMING.PACKET_ARRIVAL_PARTICLES,
   TIMING.PACKET_ARRIVAL_SPREAD
)
 }

 update(): void {
  const toRemove: Phaser.GameObjects.Graphics[]=[]

  for (const graphics of this.particles) {
   const data=this.particleData.get(graphics)
   if (!data) continue

   data.vx*=PHYSICS.PARTICLE_FRICTION
   data.vy+=TIMING.PARTICLE_GRAVITY
   data.life--

   graphics.x+=data.vx
   graphics.y+=data.vy

   const alpha=data.life/data.maxLife
   graphics.setAlpha(alpha)
   graphics.setScale(alpha)

   if (data.life<=0) {
    toRemove.push(graphics)
   }
  }

  for (const graphics of toRemove) {
   this.removeParticle(graphics)
  }
 }

 private removeParticle(graphics: Phaser.GameObjects.Graphics): void {
  const index=this.particles.indexOf(graphics)
  if (index>-1) {
   this.particles.splice(index,1)
  }
  this.particleData.delete(graphics)
  graphics.destroy()
 }

 destroy(): void {
  for (const graphics of this.particles) {
   graphics.destroy()
  }
  this.particles=[]
  this.particleData.clear()
 }
}
