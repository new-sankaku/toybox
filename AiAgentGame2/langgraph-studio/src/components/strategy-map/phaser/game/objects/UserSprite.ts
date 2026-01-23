import Phaser from 'phaser'
import { SIZES,COLORS,ANIMATION } from '../../../strategyMapConfig'
import type { PhaserUserNode } from '../../types/phaserTypes'
import { generateUserTexture } from '../utils/CharacterTextures'

export class UserSprite extends Phaser.GameObjects.Container {
 private sprite: Phaser.GameObjects.Sprite
 private label: Phaser.GameObjects.Text
 private alertGlow: Phaser.GameObjects.Graphics

 private userData: PhaserUserNode
 private frameCount: number=0

 constructor(scene: Phaser.Scene,user: PhaserUserNode) {
  super(scene,user.x,user.y)

  this.userData=user

  this.alertGlow=scene.add.graphics()
  this.add(this.alertGlow)

  const hasQueue=user.queue.length>0
  const textureKey=generateUserTexture(scene,hasQueue,0)
  this.sprite=scene.add.sprite(0,0,textureKey)
  this.sprite.setScale(SIZES.AGENT_SCALE)
  this.add(this.sprite)

  const dpr=Math.min(window.devicePixelRatio||1,2)
  this.label=scene.add.text(0,SIZES.AGENT_LABEL_OFFSET_Y,'USER',{
   fontFamily: 'system-ui, sans-serif',
   fontSize: '12px',
   color: COLORS.TEXT_PRIMARY,
  })
  this.label.setOrigin(0.5,0)
  this.label.setResolution(dpr)
  this.add(this.label)

  scene.add.existing(this)
 }

 updateUser(user: PhaserUserNode): void {
  this.userData=user
  this.setPosition(user.x,user.y)
 }

 update(): void {
  this.frameCount++
  const hasQueue=this.userData.queue.length>0

  const textureKey=generateUserTexture(this.scene,hasQueue,this.frameCount)
  this.sprite.setTexture(textureKey)

  if (hasQueue) {
   const alertIntensity=ANIMATION.USER_ALERT_BASE+
    Math.sin(this.frameCount*ANIMATION.USER_ALERT_SPEED)*ANIMATION.USER_ALERT_AMPLITUDE
   this.alertGlow.clear()
   this.alertGlow.fillStyle(0x9A5A5A,alertIntensity)
   this.alertGlow.fillCircle(0,0,40)
   this.alertGlow.setVisible(true)
  } else {
   this.alertGlow.setVisible(false)
  }
 }
}
