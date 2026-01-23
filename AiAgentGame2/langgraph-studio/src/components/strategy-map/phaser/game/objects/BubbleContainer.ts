import Phaser from 'phaser'
import { SIZES,COLORS,ANIMATION } from '../../../strategyMapConfig'
import type { BubbleType } from '../../../strategyMapTypes'

interface BubbleStyle {
 bg: number
 border: number
}

const BUBBLE_STYLES: Record<BubbleType,BubbleStyle>={
 info: { bg: 0xF8F6F0,border: 0x454138 },
 success: { bg: 0xE8F0E8,border: 0x5A8A5A },
 question: { bg: 0xF8F0E8,border: 0x9A7A5A },
 warning: { bg: 0xF8E8E8,border: 0x9A5A5A },
}

const FONT_SIZE=14
const FONT_FAMILY='system-ui, sans-serif'
const PADDING_X=16
const PADDING_Y=12
const MIN_WIDTH=40

export class BubbleContainer extends Phaser.GameObjects.Container {
 private graphics: Phaser.GameObjects.Graphics
 private textObj: Phaser.GameObjects.Text
 private bubbleText: string
 private bubbleType: BubbleType
 private baseY: number

 constructor(
  scene: Phaser.Scene,
  x: number,
  y: number,
  text: string,
  type: BubbleType|null
) {
  super(scene,x,y)

  this.baseY=y
  this.bubbleText=text
  this.bubbleType=type||'info'

  this.graphics=scene.add.graphics()
  this.add(this.graphics)

  this.textObj=scene.add.text(0,0,this.bubbleText,{
   fontFamily: FONT_FAMILY,
   fontSize: `${FONT_SIZE}px`,
   color: '#222222',
  })
  this.textObj.setOrigin(0.5,0.5)
  this.textObj.setResolution(2)
  this.add(this.textObj)

  this.renderBubble()
 }

 update(frame: number): void {
  const floatOffset=Math.sin(frame*ANIMATION.BUBBLE_FLOAT_SPEED)*ANIMATION.BUBBLE_FLOAT_AMPLITUDE
  this.y=this.baseY+floatOffset
 }

 private renderBubble(): void {
  const style=BUBBLE_STYLES[this.bubbleType]

  const textW=Math.max(this.textObj.width,MIN_WIDTH)
  const textH=this.textObj.height||FONT_SIZE

  const w=textW+PADDING_X*2
  const h=textH+PADDING_Y*2

  this.graphics.clear()

  this.graphics.fillStyle(style.bg)
  this.graphics.lineStyle(1,style.border)

  this.graphics.fillRoundedRect(-w/2,-h/2,w,h,SIZES.BUBBLE_BORDER_RADIUS)
  this.graphics.strokeRoundedRect(-w/2,-h/2,w,h,SIZES.BUBBLE_BORDER_RADIUS)

  this.graphics.fillStyle(style.bg)
  this.graphics.beginPath()
  this.graphics.moveTo(-SIZES.BUBBLE_TAIL_WIDTH,h/2)
  this.graphics.lineTo(0,h/2+SIZES.BUBBLE_TAIL_HEIGHT)
  this.graphics.lineTo(SIZES.BUBBLE_TAIL_WIDTH,h/2)
  this.graphics.closePath()
  this.graphics.fillPath()

  this.graphics.lineStyle(1,style.border)
  this.graphics.beginPath()
  this.graphics.moveTo(-SIZES.BUBBLE_TAIL_WIDTH,h/2)
  this.graphics.lineTo(0,h/2+SIZES.BUBBLE_TAIL_HEIGHT)
  this.graphics.lineTo(SIZES.BUBBLE_TAIL_WIDTH,h/2)
  this.graphics.strokePath()
 }

 setText(text: string,type: BubbleType|null): void {
  this.bubbleText=text
  this.bubbleType=type||'info'
  this.textObj.setText(this.bubbleText)
  this.renderBubble()
 }
}
