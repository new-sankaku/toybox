import Phaser from 'phaser'
import { SIZES,COLORS,LAYOUT,ZOOM } from '../../../strategyMapConfig'
import { eventBridge } from '../utils/EventBridge'
import { PhysicsSystem } from '../systems/PhysicsSystem'
import { ParticleManager } from '../systems/ParticleManager'
import { ConnectionRenderer } from '../systems/ConnectionRenderer'
import { AgentSprite } from '../objects/AgentSprite'
import { UserSprite } from '../objects/UserSprite'
import type { PhaserMapAgent,PhaserUserNode,PhaserConnection } from '../../types/phaserTypes'

export class StrategyMapScene extends Phaser.Scene {
 private physicsSystem!: PhysicsSystem
 private particleManager!: ParticleManager
 private connectionRenderer!: ConnectionRenderer

 private agentSprites: Map<string,AgentSprite>=new Map()
 private userSprite!: UserSprite
 private gridGraphics!: Phaser.GameObjects.Graphics
 private zoneLabels!: Phaser.GameObjects.Graphics
 private emptyStateText!: Phaser.GameObjects.Text
 private emptyStateSubtext!: Phaser.GameObjects.Text

 private agents: PhaserMapAgent[]=[]
 private user: PhaserUserNode={ x: 0,y: 0,queue: [] }
 private connections: PhaserConnection[]=[]

 private isDragging: boolean=false
 private dragStartX: number=0
 private dragStartY: number=0

 constructor() {
  super({ key: 'StrategyMapScene' })
 }

 create(): void {
  this.physicsSystem=new PhysicsSystem()
  this.particleManager=new ParticleManager(this)
  this.connectionRenderer=new ConnectionRenderer(this,this.particleManager)

  this.gridGraphics=this.add.graphics()
  this.gridGraphics.setDepth(0)

  this.zoneLabels=this.add.graphics()
  this.zoneLabels.setDepth(1)

  const dpr=Math.min(window.devicePixelRatio||1,2)

  this.emptyStateText=this.add.text(0,0,'エージェントがいません',{
   fontFamily: 'system-ui, sans-serif',
   fontSize: '12px',
   color: COLORS.TEXT_MUTED,
  })
  this.emptyStateText.setOrigin(0.5,0.5)
  this.emptyStateText.setDepth(5)
  this.emptyStateText.setResolution(dpr)
  this.emptyStateText.setVisible(false)

  this.emptyStateSubtext=this.add.text(0,20,'タスクを開始するとここに表示されます',{
   fontFamily: 'system-ui, sans-serif',
   fontSize: '10px',
   color: COLORS.TEXT_MUTED,
  })
  this.emptyStateSubtext.setOrigin(0.5,0.5)
  this.emptyStateSubtext.setDepth(5)
  this.emptyStateSubtext.setResolution(dpr)
  this.emptyStateSubtext.setVisible(false)

  const dims=eventBridge.getDimensions()
  this.user=eventBridge.getUser()
  this.physicsSystem.setDimensions(dims.width,dims.height)

  this.userSprite=new UserSprite(this,this.user)
  this.userSprite.setDepth(10)

  this.setupEventListeners()
  this.setupInputHandlers()

  this.renderGrid(dims.width,dims.height)
  this.renderZoneLabels(dims.width,dims.height)

  this.cameras.main.setBackgroundColor(COLORS.BACKGROUND)
  this.cameras.main.setBounds(-1000,-1000,dims.width+2000,dims.height+2000)
 }

 private setupEventListeners(): void {
  eventBridge.on('agents-updated',(agents)=>{
   this.agents=agents
  })

  eventBridge.on('user-updated',(user)=>{
   this.user=user
   this.userSprite.updateUser(user)
  })

  eventBridge.on('connections-updated',(connections)=>{
   this.connections=connections
  })

  eventBridge.on('resize',({ width,height })=>{
   if (!this.cameras?.main) return
   this.physicsSystem.setDimensions(width,height)
   this.renderGrid(width,height)
   this.renderZoneLabels(width,height)
   this.updateEmptyStatePosition(width,height)
   this.cameras.main.setBounds(-1000,-1000,width+2000,height+2000)
  })
 }

 private setupInputHandlers(): void {
  this.input.on('wheel',(_pointer: Phaser.Input.Pointer,_gameObjects: any[],_deltaX: number,deltaY: number)=>{
   const factor=deltaY>0 ? 1-ZOOM.STEP : 1+ZOOM.STEP
   const newZoom=Phaser.Math.Clamp(
    this.cameras.main.zoom*factor,
    ZOOM.MIN,
    ZOOM.MAX
)
   this.cameras.main.setZoom(newZoom)
  })

  this.input.on('pointerdown',(pointer: Phaser.Input.Pointer)=>{
   this.isDragging=true
   this.dragStartX=pointer.x
   this.dragStartY=pointer.y
  })

  this.input.on('pointermove',(pointer: Phaser.Input.Pointer)=>{
   if (!this.isDragging) return

   const dx=pointer.x-this.dragStartX
   const dy=pointer.y-this.dragStartY

   this.cameras.main.scrollX-=dx/this.cameras.main.zoom
   this.cameras.main.scrollY-=dy/this.cameras.main.zoom

   this.dragStartX=pointer.x
   this.dragStartY=pointer.y
  })

  this.input.on('pointerup',()=>{
   this.isDragging=false
  })

  this.input.on('pointerupoutside',()=>{
   this.isDragging=false
  })
 }

 update(_time: number,_delta: number): void {
  const removedPositions=this.physicsSystem.getRemovedPositions(
   new Set(this.agents.map(a=>a.id))
)

  removedPositions.forEach((pos,id)=>{
   this.particleManager.spawnDespawnParticles(pos.x,pos.y)
   const sprite=this.agentSprites.get(id)
   if (sprite) {
    sprite.destroy()
    this.agentSprites.delete(id)
   }
  })

  const newAgentIds=this.physicsSystem.updatePositions(this.agents,this.user)

  for (const agent of this.agents) {
   const pos=this.physicsSystem.getPosition(agent.id)
   if (!pos) continue

   let sprite=this.agentSprites.get(agent.id)

   if (!sprite) {
    sprite=new AgentSprite(this,agent,pos.x,pos.y)
    sprite.setDepth(20)
    this.agentSprites.set(agent.id,sprite)

    if (newAgentIds.has(agent.id)) {
     this.particleManager.spawnSpawnParticles(pos.x,pos.y)
    }
   } else {
    sprite.setPosition(pos.x,pos.y)
    sprite.updateAgent(agent)
   }

   sprite.update()
  }

  const currentIds=new Set(this.agents.map(a=>a.id))
  this.agentSprites.forEach((sprite,id)=>{
   if (!currentIds.has(id)) {
    sprite.destroy()
    this.agentSprites.delete(id)
   }
  })

  this.userSprite.update()

  this.connectionRenderer.update(
   this.connections,
   this.physicsSystem.getAllPositions(),
   this.user
)

  this.particleManager.update()

  const dims=eventBridge.getDimensions()
  if (this.agents.length===0) {
   this.emptyStateText.setVisible(true)
   this.emptyStateSubtext.setVisible(true)
   this.updateEmptyStatePosition(dims.width,dims.height)
  } else {
   this.emptyStateText.setVisible(false)
   this.emptyStateSubtext.setVisible(false)
  }
 }

 private renderGrid(width: number,height: number): void {
  this.gridGraphics.clear()

  this.gridGraphics.fillStyle(0x454138,0.12)

  const gridSize=SIZES.GRID_SIZE
  for (let x=gridSize;x<width;x+=gridSize) {
   for (let y=gridSize;y<height;y+=gridSize) {
    this.gridGraphics.fillCircle(x,y,SIZES.GRID_DOT_SIZE)
   }
  }
 }

 private renderZoneLabels(width: number,height: number): void {
  this.zoneLabels.clear()

  const userZoneY=height*LAYOUT.USER_ZONE_Y

  this.zoneLabels.lineStyle(1,0x454138,0.15)

  const dashLength=8
  for (let x=0;x<width;x+=dashLength) {
   if (Math.floor(x/dashLength)%2===0) {
    this.zoneLabels.lineBetween(x,userZoneY-50,Math.min(x+dashLength/2,width),userZoneY-50)
   }
  }
 }

 private updateEmptyStatePosition(width: number,height: number): void {
  const centerY=height*0.4
  this.emptyStateText.setPosition(width/2,centerY)
  this.emptyStateSubtext.setPosition(width/2,centerY+20)
 }

 shutdown(): void {
  this.physicsSystem.destroy()
  this.particleManager.destroy()
  this.connectionRenderer.destroy()

  this.agentSprites.forEach(sprite=>sprite.destroy())
  this.agentSprites.clear()

  eventBridge.destroy()
 }
}
