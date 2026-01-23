import Phaser from 'phaser'
import { TIMING,SIZES } from '../../../strategyMapConfig'
import type { PhaserConnection,PhaserUserNode,PhysicsBody,PacketData } from '../../types/phaserTypes'
import type { ConnectionType } from '../../../strategyMapTypes'
import type { ParticleManager } from './ParticleManager'

const CONNECTION_COLORS: Record<ConnectionType,number>={
 instruction: 0x5A7A9A,
 confirm: 0x9A7A5A,
 delivery: 0x5A8A5A,
 'user-contact': 0x9A5A5A,
}

export class ConnectionRenderer {
 private scene: Phaser.Scene
 private packets: PacketData[]=[]
 private packetGraphics: Map<string,Phaser.GameObjects.Graphics>=new Map()
 private particleManager: ParticleManager
 private frameCount: number=0

 constructor(scene: Phaser.Scene,particleManager: ParticleManager) {
  this.scene=scene
  this.particleManager=particleManager
 }

 update(
  connections: readonly PhaserConnection[],
  positions: Map<string,PhysicsBody>,
  user: PhaserUserNode
): void {
  this.frameCount++

  if (this.frameCount%TIMING.PACKET_SPAWN_INTERVAL===0) {
   this.spawnConnectionPackets(connections,positions,user)
  }

  this.updatePackets(positions,user)
 }

 private spawnConnectionPackets(
  connections: readonly PhaserConnection[],
  positions: Map<string,PhysicsBody>,
  user: PhaserUserNode
): void {
  for (const conn of connections) {
   if (!conn.active) continue

   const fromPos=positions.get(conn.fromId)
   if (!fromPos) continue

   let toX=0
   let toY=0
   const toPos=positions.get(conn.toId)

   if (toPos) {
    toX=toPos.x
    toY=toPos.y
   } else if (conn.toId==='user') {
    toX=user.x
    toY=user.y
   } else {
    continue
   }

   const color=CONNECTION_COLORS[conn.type]
   this.spawnPacket(fromPos.x,fromPos.y,toX,toY,color)
  }
 }

 private spawnPacket(
  fromX: number,
  fromY: number,
  toX: number,
  toY: number,
  color: number
): void {
  const id=`${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
  const packet: PacketData={
   id,
   fromX,
   fromY,
   toX,
   toY,
   color,
   progress: 0,
  }
  this.packets.push(packet)

  const graphics=this.scene.add.graphics()
  graphics.setDepth(50)
  this.packetGraphics.set(id,graphics)
  this.renderPacket(graphics,packet)
 }

 private updatePackets(
  _positions: Map<string,PhysicsBody>,
  _user: PhaserUserNode
): void {
  const toRemove: PacketData[]=[]

  for (const packet of this.packets) {
   packet.progress+=TIMING.PACKET_SPEED

   if (packet.progress>=1) {
    this.particleManager.spawnPacketArrivalParticles(
     packet.toX,
     packet.toY,
     packet.color
)
    toRemove.push(packet)
   } else {
    const graphics=this.packetGraphics.get(packet.id)
    if (graphics) {
     this.renderPacket(graphics,packet)
    }
   }
  }

  for (const packet of toRemove) {
   this.removePacket(packet)
  }
 }

 private renderPacket(graphics: Phaser.GameObjects.Graphics,packet: PacketData): void {
  const t=packet.progress
  const x=packet.fromX+(packet.toX-packet.fromX)*t
  const y=packet.fromY+(packet.toY-packet.fromY)*t

  graphics.clear()
  graphics.fillStyle(packet.color)
  graphics.fillCircle(x,y,SIZES.PACKET_SIZE/2)
  graphics.fillStyle(0xffffff)
  graphics.fillCircle(x,y,1)
 }

 private removePacket(packet: PacketData): void {
  const index=this.packets.indexOf(packet)
  if (index>-1) {
   this.packets.splice(index,1)
  }

  const graphics=this.packetGraphics.get(packet.id)
  if (graphics) {
   graphics.destroy()
   this.packetGraphics.delete(packet.id)
  }
 }

 destroy(): void {
  this.packetGraphics.forEach(g=>g.destroy())
  this.packetGraphics.clear()
  this.packets=[]
 }
}
