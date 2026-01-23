import Phaser from 'phaser'
import type { CharacterType,AgentDisplayConfig } from '../../../../ai-game/pixelCharacters'
import { getAgentDisplayConfig } from '../../../../ai-game/pixelCharacters'

const TEXTURE_SIZE=64
const PIXEL_SCALE=2

function colorToNumber(color: string): number {
 if (color.startsWith('#')) {
  return parseInt(color.slice(1),16)
 }
 if (color.startsWith('rgba')) {
  const match=color.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/)
  if (match) {
   return (parseInt(match[1])<<16)|(parseInt(match[2])<<8)|parseInt(match[3])
  }
 }
 return 0x808080
}


type DrawPx=(g: Phaser.GameObjects.Graphics,x: number,y: number,w?: number,h?: number)=>void

function createDrawPx(offsetX: number,offsetY: number,px: number): DrawPx {
 return (g,x,y,w=1,h=1)=>{
  g.fillRect(offsetX+x*px,offsetY+y*px,w*px,h*px)
 }
}

function drawWizard(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const float=Math.sin(frame*0.08)*1.5
 const staffGlow=isWorking ? 0.5+Math.sin(frame*0.2)*0.3 : 0.3

 g.fillStyle(0x000000,0.12)
 drawPx(g,centerX-4,26,8,1)
 g.fillStyle(0x5a3a20)
 drawPx(g,centerX+6,baseY+4+float,1,14)

 g.fillStyle(colorToNumber(config.accentColor),staffGlow)
 drawPx(g,centerX+5,baseY+2+float,3,3)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX+6,baseY+3+float,1,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-1,baseY+float,2,2)
 drawPx(g,centerX-2,baseY+2+float,4,2)
 drawPx(g,centerX-4,baseY+4+float,8,2)

 g.fillStyle(0xe8d4c4)
 drawPx(g,centerX-3,baseY+6+float,6,4)

 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-2,baseY+7+float,1,1)
 drawPx(g,centerX+1,baseY+7+float,1,1)

 g.fillStyle(0xd0d0d0)
 drawPx(g,centerX-2,baseY+9+float,4,2)
 drawPx(g,centerX-1,baseY+11+float,2,3)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+10+float,8,8)
 drawPx(g,centerX-5,baseY+14+float,10,6)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-1,baseY+11+float,2,6)
}

function drawKnight(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const anim=isWorking ? Math.sin(frame*0.12) : 0

 g.fillStyle(0x000000,0.15)
 drawPx(g,centerX-5,26,10,1)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-1,baseY,2,3)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+2,6,5)

 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX-2,baseY+4,4,2)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+5,1,1)
 drawPx(g,centerX+1,baseY+5,1,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-5,baseY+7,10,6)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+8,4,3)
 g.fillStyle(0x808080)
 drawPx(g,centerX+6,baseY+5+anim*2,1,10)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX+5,baseY+14+anim*2,3,2)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-8,baseY+8-anim,3,6)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-7,baseY+10-anim,1,2)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+13,2,6)
 drawPx(g,centerX+1,baseY+13,2,6)
 g.fillStyle(0x404040)
 drawPx(g,centerX-4,baseY+18,3,2)
 drawPx(g,centerX+1,baseY+18,3,2)
}

function drawNinja(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const anim=isWorking ? Math.sin(frame*0.25)*2 : 0
 const jump=isWorking ? Math.abs(Math.sin(frame*0.15))*3 : 0

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-3,26,6,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+2-jump,6,5)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+4-jump,4,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+7-jump,8,6)
 drawPx(g,centerX-6,baseY+7-jump+anim,2,5)
 drawPx(g,centerX+4,baseY+7-jump-anim,2,5)
 g.fillStyle(0x606060)
 drawPx(g,centerX+5,baseY+4-jump-anim,1,4)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX+3,baseY+5-jump,3+anim,2)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+13-jump,2,5)
 drawPx(g,centerX+1,baseY+13-jump,2,5)
}

function drawSamurai(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const anim=isWorking ? Math.sin(frame*0.15) : 0

 g.fillStyle(0x000000,0.12)
 drawPx(g,centerX-5,26,10,1)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-4,baseY,2,3)
 drawPx(g,centerX+2,baseY,2,3)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+3,8,4)

 g.fillStyle(0xd0c0b0)
 drawPx(g,centerX-2,baseY+5,4,3)
 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX-1,baseY+6,1,1)
 drawPx(g,centerX+1,baseY+6,1,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-5,baseY+8,10,6)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-5,baseY+8,10,1)
 g.fillStyle(0x808080)
 drawPx(g,centerX+5+anim,baseY+6,1,12)
 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX+4+anim,baseY+16,3,2)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+14,8,6)
}

function drawArcher(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const drawAnim=isWorking ? Math.sin(frame*0.1)*2 : 0

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-4,26,8,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+1,6,4)
 drawPx(g,centerX-4,baseY+3,8,2)

 g.fillStyle(0xe8d4c4)
 drawPx(g,centerX-2,baseY+4,4,4)
 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-1,baseY+5,1,1)
 drawPx(g,centerX+1,baseY+5,1,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+8,8,6)
 g.fillStyle(0x6a4a30)
 drawPx(g,centerX-7,baseY+4,1,12)
 g.fillStyle(0xd0d0d0)
 drawPx(g,centerX-6,baseY+4,1,1)
 drawPx(g,centerX-5-drawAnim,baseY+10,1,1)
 drawPx(g,centerX-6,baseY+15,1,1)
 if (isWorking) {
  g.fillStyle(0x808080)
  drawPx(g,centerX-4-drawAnim,baseY+10,4,1)
 }
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX+4,baseY+8,2,8)

 g.fillStyle(0x4a3a2a)
 drawPx(g,centerX-2,baseY+14,2,5)
 drawPx(g,centerX+1,baseY+14,2,5)
}

function drawPrincess(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 _isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const sway=Math.sin(frame*0.08)*0.5

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-4,26,8,1)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+1,4,2)
 drawPx(g,centerX-1,baseY,2,1)

 g.fillStyle(0x5a4030)
 drawPx(g,centerX-4,baseY+2,8,6)
 drawPx(g,centerX-5,baseY+5,2,8)
 drawPx(g,centerX+3,baseY+5,2,8)

 g.fillStyle(0xf0dcc8)
 drawPx(g,centerX-3,baseY+3,6,5)
 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-2,baseY+5,1.5,1.5)
 drawPx(g,centerX+0.5,baseY+5,1.5,1.5)

 g.fillStyle(0xc08080)
 drawPx(g,centerX-0.5,baseY+7,1,0.5)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+8,8,4)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-5,baseY+12+sway,10,8)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-1,baseY+9,2,2)
 drawPx(g,centerX-4,baseY+14+sway,8,1)
}

function drawBard(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const strum=isWorking ? Math.sin(frame*0.3)*1.5 : 0
 const noteY=isWorking ? (frame*0.5)%10 : 0

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-4,26,8,1)
 if (isWorking) {
  g.fillStyle(colorToNumber(config.accentColor))
  drawPx(g,centerX+5,baseY+2-noteY,2,2)
 }
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+2,6,3)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX+2,baseY,2,3)

 g.fillStyle(0xe8d4c4)
 drawPx(g,centerX-2,baseY+4,4,4)
 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-1,baseY+5,1,1)
 drawPx(g,centerX+1,baseY+5,1,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+8,8,6)
 g.fillStyle(0x8a6a40)
 drawPx(g,centerX-7,baseY+10+strum,4,6)
 g.fillStyle(0x6a4a30)
 drawPx(g,centerX-6,baseY+8+strum,2,3)
 g.fillStyle(0xd0d0d0)
 drawPx(g,centerX-5,baseY+11+strum,1,4)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-2,baseY+14,2,5)
 drawPx(g,centerX+1,baseY+14,2,5)
}

function drawDruid(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 _isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const leafSway=Math.sin(frame*0.1)*1

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-4,26,8,1)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+1+leafSway,2,2)
 drawPx(g,centerX+1,baseY+1-leafSway,2,2)
 drawPx(g,centerX-1,baseY,2,2)
 g.fillStyle(0x6a5a4a)
 drawPx(g,centerX-3,baseY+2,6,5)
 drawPx(g,centerX-4,baseY+5,2,6)
 drawPx(g,centerX+2,baseY+5,2,6)

 g.fillStyle(0xe8d4c4)
 drawPx(g,centerX-2,baseY+4,4,4)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-1,baseY+5,1,1)
 drawPx(g,centerX+1,baseY+5,1,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+8,8,6)
 drawPx(g,centerX-5,baseY+12,10,8)
 g.fillStyle(0x5a4a30)
 drawPx(g,centerX+5,baseY+4,1,14)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX+4,baseY+2,3,3)
}

function drawAlchemist(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const bubble=isWorking ? Math.sin(frame*0.3)*2 : 0

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-4,26,8,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+1,6,4)

 g.fillStyle(0xe8d4c4)
 drawPx(g,centerX-2,baseY+4,4,4)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+5,1.5,1.5)
 drawPx(g,centerX+0.5,baseY+5,1.5,1.5)
 g.fillStyle(0xe0e0e0)
 drawPx(g,centerX-4,baseY+8,8,8)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+9,6,6)
 g.fillStyle(0x90c0d0)
 drawPx(g,centerX+4,baseY+10,3,5)

 if (isWorking) {
  g.fillStyle(colorToNumber(config.accentColor))
  drawPx(g,centerX+5,baseY+8-bubble,1,1)
  drawPx(g,centerX+4,baseY+6-bubble,1,1)
 }

 g.fillStyle(0x4a4a4a)
 drawPx(g,centerX-2,baseY+16,2,4)
 drawPx(g,centerX+1,baseY+16,2,4)
}

function drawEngineer(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const wrench=isWorking ? Math.sin(frame*0.2)*2 : 0

 g.fillStyle(0x000000,0.12)
 drawPx(g,centerX-4,26,8,1)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+1,6,4)

 g.fillStyle(isWorking ? 0xffff00 : 0x808080)
 drawPx(g,centerX-1,baseY+2,2,1)

 g.fillStyle(0xe8d4c4)
 drawPx(g,centerX-2,baseY+4,4,4)
 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-1,baseY+5,1,1)
 drawPx(g,centerX+1,baseY+5,1,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+8,8,7)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+10,2,2)
 drawPx(g,centerX+1,baseY+10,2,2)
 g.fillStyle(0x606060)
 drawPx(g,centerX+5,baseY+8+wrench,2,6)
 g.fillStyle(0x808080)
 drawPx(g,centerX+4,baseY+7+wrench,4,2)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+15,2,4)
 drawPx(g,centerX+1,baseY+15,2,4)
}

function drawCat(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const anim=isWorking ? Math.sin(frame*0.2)*2 : 0

 g.fillStyle(0x000000,0.12)
 drawPx(g,centerX-5,25,10,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 const tailWave=Math.sin(frame*0.1)*2
 drawPx(g,centerX+5,baseY+8+tailWave,2,6)
 drawPx(g,centerX+6,baseY+6+tailWave,2,3)

 drawPx(g,centerX-5,baseY+10,10,6)

 drawPx(g,centerX-4,baseY+2,8,8)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY,2,3)
 drawPx(g,centerX+2,baseY,2,3)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+1,1,1)
 drawPx(g,centerX+2,baseY+1,1,1)

 g.fillStyle(0x40a040)
 drawPx(g,centerX-3,baseY+5,2,2)
 drawPx(g,centerX+1,baseY+5,2,2)

 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX-2.5,baseY+5.5,1,1)
 drawPx(g,centerX+1.5,baseY+5.5,1,1)

 g.fillStyle(0xff9090)
 drawPx(g,centerX-0.5,baseY+7,1,1)

 g.fillStyle(0xffffff)
 drawPx(g,centerX-6,baseY+7,2,0.5)
 drawPx(g,centerX+4,baseY+7,2,0.5)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+16,2,4+anim)
 drawPx(g,centerX+2,baseY+16,2,4-anim)
}

function drawOwl(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 _isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const blink=Math.floor(frame/30)%5===0
 const headTilt=Math.sin(frame*0.05)*1

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-4,26,8,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+10,8,10)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4+headTilt,baseY+2,8,8)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-4+headTilt,baseY+1,2,3)
 drawPx(g,centerX+2+headTilt,baseY+1,2,3)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3+headTilt,baseY+4,6,4)
 g.fillStyle(0xffcc00)
 drawPx(g,centerX-2+headTilt,baseY+5,2,2)
 drawPx(g,centerX+1+headTilt,baseY+5,2,2)
 if (!blink) {
  g.fillStyle(0x1a1a1a)
  drawPx(g,centerX-1.5+headTilt,baseY+5.5,1,1)
  drawPx(g,centerX+1.5+headTilt,baseY+5.5,1,1)
 }

 g.fillStyle(0xe0a020)
 drawPx(g,centerX-0.5+headTilt,baseY+7,1,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-6,baseY+11,2,6)
 drawPx(g,centerX+4,baseY+11,2,6)

 g.fillStyle(0xe0a020)
 drawPx(g,centerX-2,baseY+18,1,2)
 drawPx(g,centerX+1,baseY+18,1,2)
}

function drawFox(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const tailWag=isWorking ? Math.sin(frame*0.2)*3 : 0

 g.fillStyle(0x000000,0.1)
 drawPx(g,centerX-5,26,10,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX+4+tailWag,baseY+10,4,6)
 g.fillStyle(0xffffff)
 drawPx(g,centerX+6+tailWag,baseY+14,2,2)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+12,8,6)

 drawPx(g,centerX-4,baseY+4,8,8)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-5,baseY+2,3,4)
 drawPx(g,centerX+2,baseY+2,3,4)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-4,baseY+3,1,2)
 drawPx(g,centerX+3,baseY+3,1,2)
 g.fillStyle(0xffffff)
 drawPx(g,centerX-2,baseY+6,4,5)

 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-2,baseY+6,1.5,1.5)
 drawPx(g,centerX+0.5,baseY+6,1.5,1.5)

 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-0.5,baseY+9,1,1)

 g.fillStyle(0x2a2a2a)
 drawPx(g,centerX-3,baseY+18,2,2)
 drawPx(g,centerX+1,baseY+18,2,2)
}

function drawFairy(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const float=Math.sin(frame*0.12)*3
 const wingFlap=Math.sin(frame*0.3)*2
 g.fillStyle(colorToNumber(config.accentColor),0.2)
 drawPx(g,centerX-6,baseY+4+float,12,12)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-7,baseY+6+float-wingFlap,3,6)
 drawPx(g,centerX+4,baseY+6+float-wingFlap,3,6)
 drawPx(g,centerX-6,baseY+10+float+wingFlap,2,4)
 drawPx(g,centerX+4,baseY+10+float+wingFlap,2,4)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-2,baseY+3+float,4,4)

 g.fillStyle(0xf0e0d0)
 drawPx(g,centerX-1,baseY+5+float,2,3)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-1,baseY+6+float,0.5,0.5)
 drawPx(g,centerX+0.5,baseY+6+float,0.5,0.5)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-2,baseY+8+float,4,4)
 drawPx(g,centerX-3,baseY+11+float,6,3)
 if (isWorking) {
  g.fillStyle(0xffffff)
  const sparkle=(frame*0.2)%6
  drawPx(g,centerX-4+sparkle,baseY+4+float,1,1)
  drawPx(g,centerX+2-sparkle,baseY+8+float,1,1)
 }
}

function drawPhoenix(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const fly=isWorking ? Math.sin(frame*0.15)*2 : 0
 const wingFlap=isWorking ? Math.abs(Math.sin(frame*0.25))*4 : 0
 const flame=Math.sin(frame*0.3)*1
 if (isWorking) {
  g.fillStyle(0xff9632,0.3)
  drawPx(g,centerX-5,baseY+4+fly,10,14)
 }
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+14+fly+flame,4,6)
 drawPx(g,centerX-1,baseY+18+fly+flame,2,3)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-8,baseY+8+fly-wingFlap,4,4)
 drawPx(g,centerX+4,baseY+8+fly-wingFlap,4,4)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-7,baseY+10+fly-wingFlap,2,2)
 drawPx(g,centerX+5,baseY+10+fly-wingFlap,2,2)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+6+fly,6,8)

 drawPx(g,centerX-2,baseY+2+fly,4,5)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-1,baseY+fly,2,3)

 g.fillStyle(0xffcc00)
 drawPx(g,centerX-1,baseY+4+fly,1,1)
 drawPx(g,centerX+1,baseY+4+fly,1,1)

 g.fillStyle(0xe0a020)
 drawPx(g,centerX-0.5,baseY+6+fly,1,1)
}

function drawMermaid(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 _isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const swim=Math.sin(frame*0.1)*1.5
 const tailWave=Math.sin(frame*0.15)*2

 g.fillStyle(0x000000,0.08)
 drawPx(g,centerX-4,26,8,1)
 g.fillStyle(0x4a6060)
 drawPx(g,centerX-4,baseY+2+swim,8,6)
 drawPx(g,centerX-5,baseY+6+swim,2,8)
 drawPx(g,centerX+3,baseY+6+swim,2,8)

 g.fillStyle(0xf0e8e0)
 drawPx(g,centerX-2,baseY+3+swim,4,4)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-1,baseY+4+swim,1,1)
 drawPx(g,centerX+1,baseY+4+swim,1,1)
 g.fillStyle(0xf0e8e0)
 drawPx(g,centerX-3,baseY+7+swim,6,4)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+8+swim,1.5,1.5)
 drawPx(g,centerX+0.5,baseY+8+swim,1.5,1.5)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-2,baseY+11+swim,4,4)
 drawPx(g,centerX-1,baseY+15+swim+tailWave,2,3)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+17+swim+tailWave,2,3)
 drawPx(g,centerX+1,baseY+17+swim+tailWave,2,3)
}

function drawWolf(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const howl=isWorking&&Math.floor(frame/20)%3===0

 g.fillStyle(0x000000,0.12)
 drawPx(g,centerX-5,26,10,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX+4,baseY+10,3,4)
 drawPx(g,centerX+5,baseY+8,2,3)

 drawPx(g,centerX-4,baseY+12,8,6)

 if (howl) {
  drawPx(g,centerX-3,baseY+4,6,4)
  drawPx(g,centerX-1,baseY+2,2,3)
  g.fillStyle(0x1a1a1a)
  drawPx(g,centerX-0.5,baseY+2,1,2)
 } else {
  drawPx(g,centerX-3,baseY+5,6,6)
  g.fillStyle(colorToNumber(config.accentColor))
  drawPx(g,centerX-1,baseY+8,2,3)
  g.fillStyle(0x1a1a1a)
  drawPx(g,centerX-0.5,baseY+9,1,1)
 }

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+3,2,3)
 drawPx(g,centerX+2,baseY+3,2,3)

 g.fillStyle(0xc0a000)
 drawPx(g,centerX-2,baseY+6,1.5,1.5)
 drawPx(g,centerX+0.5,baseY+6,1.5,1.5)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+18,2,2)
 drawPx(g,centerX+1,baseY+18,2,2)
}

function drawGolem(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const stomp=isWorking ? Math.abs(Math.sin(frame*0.1))*1 : 0

 g.fillStyle(0x000000,0.2)
 drawPx(g,centerX-6,26,12,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+2+stomp,6,5)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+4+stomp,1.5,1.5)
 drawPx(g,centerX+0.5,baseY+4+stomp,1.5,1.5)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-5,baseY+7+stomp,10,8)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-1,baseY+9+stomp,2,4)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-8,baseY+8+stomp,3,8)
 drawPx(g,centerX+5,baseY+8+stomp,3,8)

 drawPx(g,centerX-9,baseY+15+stomp,4,3)
 drawPx(g,centerX+5,baseY+15+stomp,4,3)
 drawPx(g,centerX-4,baseY+15,3,5)
 drawPx(g,centerX+1,baseY+15,3,5)
}

function drawPuppet(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 _isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const dangle=Math.sin(frame*0.15)*2
 const armSwing=Math.sin(frame*0.2)*3
 g.fillStyle(0x808080)
 drawPx(g,centerX,baseY,1,4)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+3+dangle,6,5)

 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX-2,baseY+5+dangle,1.5,1.5)
 drawPx(g,centerX+0.5,baseY+5+dangle,1.5,1.5)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-1,baseY+7+dangle,2,0.5)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+8+dangle,6,6)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+9+dangle,4,2)
 g.fillStyle(0x808080)
 drawPx(g,centerX-5,baseY+2,1,6+armSwing)
 drawPx(g,centerX+4,baseY+2,1,6-armSwing)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-6,baseY+8+dangle+armSwing,2,4)
 drawPx(g,centerX+4,baseY+8+dangle-armSwing,2,4)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-2,baseY+14+dangle,2,4)
 drawPx(g,centerX+1,baseY+14+dangle,2,4)
}

function drawClockwork(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 _isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const gearRotate=(frame*2)%360
 const tick=Math.floor(frame/10)%2

 g.fillStyle(0x000000,0.12)
 drawPx(g,centerX-5,26,10,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+2,8,6)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+3,6,4)

 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX,baseY+4,1,2)
 drawPx(g,centerX-1+tick,baseY+5,2,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-5,baseY+8,10,8)

 g.fillStyle(colorToNumber(config.accentColor))
 const gx=Math.cos(gearRotate*0.02)*0.5
 const gy=Math.sin(gearRotate*0.02)*0.5
 drawPx(g,centerX-2+gx,baseY+10+gy,4,4)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-1,baseY+11,2,2)
 g.fillStyle(0x606060)
 drawPx(g,centerX-7,baseY+9,2,5)
 drawPx(g,centerX+5,baseY+9,2,5)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-7,baseY+13,2,1)
 drawPx(g,centerX+5,baseY+13,2,1)

 g.fillStyle(0x606060)
 drawPx(g,centerX-3,baseY+16,2,4)
 drawPx(g,centerX+1,baseY+16,2,4)
}

function drawMech(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const walk=isWorking ? Math.sin(frame*0.12)*1 : 0

 g.fillStyle(0x000000,0.15)
 drawPx(g,centerX-6,26,12,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+2,6,4)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+3,4,2)

 g.fillStyle(isWorking ? 0x00ff00 : 0x404040)
 drawPx(g,centerX-1,baseY+4,1,1)
 drawPx(g,centerX+1,baseY+4,1,1)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+6,8,7)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+7,6,4)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-7,baseY+6,3,3)
 drawPx(g,centerX+4,baseY+6,3,3)

 g.fillStyle(0x606060)
 drawPx(g,centerX-7,baseY+9,2,6)
 drawPx(g,centerX+5,baseY+9,2,6)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-8,baseY+14,3,2)
 drawPx(g,centerX+5,baseY+14,3,2)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+13+walk,3,5)
 drawPx(g,centerX+1,baseY+13-walk,3,5)
 g.fillStyle(0x606060)
 drawPx(g,centerX-5,baseY+17+walk,4,3)
 drawPx(g,centerX+1,baseY+17-walk,4,3)
}

function drawDragon(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const breathe=Math.sin(frame*0.08)*0.5
 const wingFlap=isWorking ? Math.sin(frame*0.2)*3 : 0
 if (isWorking&&Math.floor(frame/15)%2===0) {
  g.fillStyle(colorToNumber(config.accentColor))
  drawPx(g,centerX+4,baseY+8,4,2)
  drawPx(g,centerX+6,baseY+7,2,1)
 }

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-9,baseY+6-wingFlap,4,5)
 drawPx(g,centerX+5,baseY+6-wingFlap,4,5)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-6,baseY+14,3,3)
 drawPx(g,centerX-8,baseY+16,2,2)
 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-9,baseY+17,2,2)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-4,baseY+10+breathe,8,8)

 drawPx(g,centerX-2,baseY+4+breathe,6,6)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-2,baseY+2+breathe,2,3)
 drawPx(g,centerX+2,baseY+2+breathe,2,3)

 g.fillStyle(0xff6600)
 drawPx(g,centerX,baseY+6+breathe,2,2)
 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX+0.5,baseY+6.5+breathe,1,1)
 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX+2,baseY+8+breathe,1,1)

 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-3,baseY+17,2,3)
 drawPx(g,centerX+1,baseY+17,2,3)
}

function drawTurtle(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 config: AgentDisplayConfig,
 isWorking: boolean,
 frame: number,
 baseY: number
): void {
 const centerX=14
 const crawl=isWorking ? Math.sin(frame*0.08)*1 : 0

 g.fillStyle(0x000000,0.15)
 drawPx(g,centerX-6,26,12,1)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-6,baseY+16,2,2)
 g.fillStyle(colorToNumber(config.bodyColor))
 drawPx(g,centerX-5,baseY+8,10,8)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-3,baseY+10,2,2)
 drawPx(g,centerX+1,baseY+10,2,2)
 drawPx(g,centerX-1,baseY+13,2,2)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX+3,baseY+10+crawl,4,4)
 g.fillStyle(0x1a1a1a)
 drawPx(g,centerX+5,baseY+11+crawl,1,1)

 g.fillStyle(colorToNumber(config.accentColor))
 drawPx(g,centerX-5,baseY+16+crawl,2,2)
 drawPx(g,centerX+3,baseY+16-crawl,2,2)
 drawPx(g,centerX-5,baseY+10-crawl,2,2)
 drawPx(g,centerX+3,baseY+10+crawl,2,2)
}

function drawUserCharacter(
 g: Phaser.GameObjects.Graphics,
 drawPx: DrawPx,
 hasQueue: boolean,
 frame: number
): void {
 const baseY=2
 const breath=Math.sin(frame*0.06)*0.5
 const alert=hasQueue ? Math.sin(frame*0.15)*1 : 0

 g.fillStyle(0x000000,0.12)
 drawPx(g,10,26,8,1)

 g.fillStyle(0x3a3020)
 drawPx(g,10,baseY+2,8,5)
 drawPx(g,9,baseY+5,2,6)
 drawPx(g,17,baseY+5,2,6)

 g.fillStyle(0xf0e0c8)
 drawPx(g,11,baseY+4+breath,6,5)

 g.fillStyle(0x2a2a2a)
 drawPx(g,12,baseY+5+breath,1.5,1.5)
 drawPx(g,14.5,baseY+5+breath,1.5,1.5)

 g.fillStyle(0xc09080)
 drawPx(g,13.5,baseY+7+breath,1,0.5)

 g.fillStyle(0xe8e0d8)
 drawPx(g,10,baseY+9,8,8)
 g.fillStyle(0xd0c8c0)
 drawPx(g,12,baseY+10,4,6)

 g.fillStyle(0xf0e0c8)
 drawPx(g,8,baseY+10+alert,2,5)
 drawPx(g,18,baseY+10-alert,2,5)

 g.fillStyle(0x4a4030)
 drawPx(g,11,baseY+17,3,5)
 drawPx(g,14,baseY+17,3,5)

 g.fillStyle(0x3a3020)
 drawPx(g,10,baseY+21,4,2)
 drawPx(g,14,baseY+21,4,2)

 if (hasQueue) {
  g.fillStyle(0xc8a064,0.4+Math.sin(frame*0.12)*0.2)
  drawPx(g,6,baseY+2,2,2)
  drawPx(g,20,baseY+4,2,2)
 }
}

const characterDrawers: Record<CharacterType,typeof drawWizard>={
 wizard: drawWizard,
 knight: drawKnight,
 ninja: drawNinja,
 samurai: drawSamurai,
 archer: drawArcher,
 princess: drawPrincess,
 bard: drawBard,
 druid: drawDruid,
 alchemist: drawAlchemist,
 engineer: drawEngineer,
 cat: drawCat,
 owl: drawOwl,
 fox: drawFox,
 fairy: drawFairy,
 phoenix: drawPhoenix,
 mermaid: drawMermaid,
 wolf: drawWolf,
 golem: drawGolem,
 puppet: drawPuppet,
 clockwork: drawClockwork,
 mech: drawMech,
 dragon: drawDragon,
 turtle: drawTurtle,
}

export function generateCharacterTexture(
 scene: Phaser.Scene,
 agentType: string,
 isWorking: boolean,
 frame: number
): string {
 const key=`char_${agentType}_${isWorking ? 'w' : 'i'}_${frame % 60}`

 if (scene.textures.exists(key)) {
  return key
 }

 const config=getAgentDisplayConfig(agentType)
 const px=PIXEL_SCALE
 const offsetX=14*px
 const offsetY=14*px
 const baseY=isWorking ? 2+Math.sin(frame*0.1)*0.5 : 2

 const graphics=scene.make.graphics({ x: 0,y: 0,add: false } as Phaser.Types.GameObjects.Graphics.Options)
 const drawPx=createDrawPx(offsetX-14*px,offsetY-14*px,px)

 const drawer=characterDrawers[config.characterType]
 if (drawer) {
  drawer(graphics,drawPx,config,isWorking,frame,baseY)
 }

 if (isWorking) {
  graphics.fillStyle(0xffdc64,0.3+Math.sin(frame*0.2)*0.2)
  const sparkleX=14+Math.cos(frame*0.12)*10
  const sparkleY=14+Math.sin(frame*0.17)*8
  drawPx(graphics,sparkleX,sparkleY,1,1)
 }

 graphics.generateTexture(key,TEXTURE_SIZE,TEXTURE_SIZE)
 graphics.destroy()

 return key
}

export function generateUserTexture(
 scene: Phaser.Scene,
 hasQueue: boolean,
 frame: number
): string {
 const key=`user_${hasQueue ? 'q' : 'n'}_${frame % 60}`

 if (scene.textures.exists(key)) {
  return key
 }

 const px=PIXEL_SCALE
 const graphics=scene.make.graphics({ x: 0,y: 0,add: false } as Phaser.Types.GameObjects.Graphics.Options)
 const drawPx=createDrawPx(0,0,px)

 drawUserCharacter(graphics,drawPx,hasQueue,frame)

 graphics.generateTexture(key,TEXTURE_SIZE,TEXTURE_SIZE)
 graphics.destroy()

 return key
}

export { getAgentDisplayConfig }
