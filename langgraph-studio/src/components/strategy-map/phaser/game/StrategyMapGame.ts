import Phaser from 'phaser'
import { StrategyMapScene } from './scenes/StrategyMapScene'
import { COLORS } from '../../strategyMapConfig'

export interface GameConfig {
 parent: HTMLElement
 width: number
 height: number
}

export function createStrategyMapGame(config: GameConfig): Phaser.Game {
 const bgColor=COLORS.BACKGROUND.replace('#','0x')
 const dpr=Math.min(window.devicePixelRatio||1,2)

 const gameConfig: Phaser.Types.Core.GameConfig={
  type: Phaser.CANVAS,
  parent: config.parent,
  width: config.width*dpr,
  height: config.height*dpr,
  backgroundColor: parseInt(bgColor,16),
  pixelArt: false,
  antialias: true,
  roundPixels: false,
  scale: {
   mode: Phaser.Scale.NONE,
   autoCenter: Phaser.Scale.NO_CENTER,
   zoom: 1/dpr,
  },
  scene: [StrategyMapScene],
  render: {
   pixelArt: false,
   antialias: true,
   roundPixels: false,
  },
 }

 return new Phaser.Game(gameConfig)
}
