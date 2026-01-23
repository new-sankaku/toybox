export type CharacterType=
 |'wizard'|'knight'|'ninja'|'samurai'|'archer'
 |'princess'|'bard'|'druid'|'alchemist'|'engineer'
 |'cat'|'owl'|'fox'|'fairy'|'phoenix'
 |'mermaid'|'wolf'|'golem'|'puppet'|'clockwork'
 |'mech'|'dragon'|'turtle'

export interface AgentDisplayConfig{
 label:string
 bodyColor:string
 accentColor:string
 characterType:CharacterType
}

export function getAgentDisplayConfig(agentType:string):AgentDisplayConfig{
 const configs:Record<string,AgentDisplayConfig>={
  orchestrator:{label:'ORCHESTRATOR',bodyColor:'#8b0000',accentColor:'#ff4040',characterType:'dragon'},
  director_phase1:{label:'DIRECTOR (企画)',bodyColor:'#4a0080',accentColor:'#9040c0',characterType:'wizard'},
  director_phase2:{label:'DIRECTOR (開発)',bodyColor:'#004080',accentColor:'#4080c0',characterType:'mech'},
  director_phase3:{label:'DIRECTOR (品質)',bodyColor:'#006040',accentColor:'#40a080',characterType:'golem'},
  leader_concept:{label:'LEADER (コンセプト)',bodyColor:'#602080',accentColor:'#a050c0',characterType:'princess'},
  leader_scenario:{label:'LEADER (シナリオ)',bodyColor:'#403080',accentColor:'#7060b0',characterType:'bard'},
  leader_design:{label:'LEADER (設計)',bodyColor:'#604020',accentColor:'#a08050',characterType:'alchemist'},
  leader_task_split:{label:'LEADER (タスク分割)',bodyColor:'#204060',accentColor:'#5080a0',characterType:'engineer'},
  leader_code:{label:'LEADER (コード)',bodyColor:'#304060',accentColor:'#6080b0',characterType:'knight'},
  leader_asset:{label:'LEADER (アセット)',bodyColor:'#604030',accentColor:'#a08060',characterType:'druid'},
  worker_concept:{label:'WORKER (コンセプト)',bodyColor:'#805090',accentColor:'#b080c0',characterType:'fairy'},
  worker_scenario:{label:'WORKER (シナリオ)',bodyColor:'#504080',accentColor:'#8070b0',characterType:'puppet'},
  worker_design:{label:'WORKER (設計)',bodyColor:'#705030',accentColor:'#b09060',characterType:'fox'},
  worker_task_split:{label:'WORKER (タスク分割)',bodyColor:'#305070',accentColor:'#6090b0',characterType:'owl'},
  worker_code:{label:'WORKER (コード)',bodyColor:'#405070',accentColor:'#7090b0',characterType:'ninja'},
  worker_asset:{label:'WORKER (アセット)',bodyColor:'#705040',accentColor:'#b09070',characterType:'cat'},
  character:{label:'WORKER (キャラ)',bodyColor:'#804050',accentColor:'#c07080',characterType:'princess'},
  integrator:{label:'WORKER (統合)',bodyColor:'#306050',accentColor:'#60a080',characterType:'clockwork'},
  reviewer:{label:'WORKER (検証)',bodyColor:'#405050',accentColor:'#709090',characterType:'samurai'},
  concept:{label:'WORKER (コンセプト)',bodyColor:'#1a4080',accentColor:'#4080c0',characterType:'wizard'},
  task_split_1:{label:'WORKER (分割1)',bodyColor:'#704010',accentColor:'#b08040',characterType:'knight'},
  task_split_2:{label:'WORKER (分割2)',bodyColor:'#302050',accentColor:'#6050a0',characterType:'ninja'},
  task_split_3:{label:'WORKER (分割3)',bodyColor:'#801020',accentColor:'#c04060',characterType:'samurai'},
  task_split_4:{label:'WORKER (分割4)',bodyColor:'#205030',accentColor:'#408060',characterType:'archer'},
  concept_detail:{label:'WORKER (詳細企画)',bodyColor:'#a02050',accentColor:'#e070a0',characterType:'princess'},
  scenario:{label:'WORKER (シナリオ)',bodyColor:'#502080',accentColor:'#9060c0',characterType:'bard'},
  world:{label:'WORKER (世界観)',bodyColor:'#106030',accentColor:'#40a060',characterType:'druid'},
  game_design:{label:'WORKER (ゲーム設計)',bodyColor:'#806010',accentColor:'#c0a030',characterType:'alchemist'},
  tech_spec:{label:'WORKER (技術仕様)',bodyColor:'#105070',accentColor:'#3090b0',characterType:'engineer'},
  asset_character:{label:'WORKER (キャラ素材)',bodyColor:'#904020',accentColor:'#d08050',characterType:'cat'},
  asset_background:{label:'WORKER (背景素材)',bodyColor:'#304060',accentColor:'#6080b0',characterType:'owl'},
  asset_ui:{label:'WORKER (UI素材)',bodyColor:'#804010',accentColor:'#c08040',characterType:'fox'},
  asset_effect:{label:'WORKER (エフェクト)',bodyColor:'#603080',accentColor:'#a060c0',characterType:'fairy'},
  asset_bgm:{label:'WORKER (BGM)',bodyColor:'#802010',accentColor:'#c06040',characterType:'phoenix'},
  asset_voice:{label:'WORKER (ボイス)',bodyColor:'#106060',accentColor:'#40a0a0',characterType:'mermaid'},
  asset_sfx:{label:'WORKER (効果音)',bodyColor:'#404050',accentColor:'#707090',characterType:'wolf'},
  code:{label:'WORKER (コード)',bodyColor:'#303060',accentColor:'#6060a0',characterType:'golem'},
  event:{label:'WORKER (イベント)',bodyColor:'#503050',accentColor:'#906090',characterType:'puppet'},
  ui_integration:{label:'WORKER (UI統合)',bodyColor:'#504030',accentColor:'#908060',characterType:'clockwork'},
  asset_integration:{label:'WORKER (素材統合)',bodyColor:'#204050',accentColor:'#508090',characterType:'mech'},
  unit_test:{label:'WORKER (単体テスト)',bodyColor:'#106020',accentColor:'#40a050',characterType:'dragon'},
  integration_test:{label:'WORKER (結合テスト)',bodyColor:'#205040',accentColor:'#409070',characterType:'turtle'},
 }
 return configs[agentType]||{label:'Agent',bodyColor:'#505050',accentColor:'#808080',characterType:'wizard'}
}

export function drawPixelCharacter(
 ctx:CanvasRenderingContext2D,
 centerX:number,
 centerY:number,
 agentType:string,
 isWorking:boolean,
 frame:number,
 scale:number=1
):void{
 const config=getAgentDisplayConfig(agentType)
 const px=2*scale
 const offsetX=centerX-14*px
 const offsetY=centerY-14*px

 const drawPx=(x:number,y:number,w:number=1,h:number=1)=>{
  ctx.fillRect(offsetX+x*px,offsetY+y*px,w*px,h*px)
 }

 const baseY=isWorking?2+Math.sin(frame*0.1)*0.5:2

 ctx.save()

 switch(config.characterType){
  case'wizard':drawWizard(ctx,drawPx,config,isWorking,frame,baseY);break
  case'knight':drawKnight(ctx,drawPx,config,isWorking,frame,baseY);break
  case'ninja':drawNinja(ctx,drawPx,config,isWorking,frame,baseY);break
  case'samurai':drawSamurai(ctx,drawPx,config,isWorking,frame,baseY);break
  case'archer':drawArcher(ctx,drawPx,config,isWorking,frame,baseY);break
  case'princess':drawPrincess(ctx,drawPx,config,isWorking,frame,baseY);break
  case'bard':drawBard(ctx,drawPx,config,isWorking,frame,baseY);break
  case'druid':drawDruid(ctx,drawPx,config,isWorking,frame,baseY);break
  case'alchemist':drawAlchemist(ctx,drawPx,config,isWorking,frame,baseY);break
  case'engineer':drawEngineer(ctx,drawPx,config,isWorking,frame,baseY);break
  case'cat':drawCat(ctx,drawPx,config,isWorking,frame,baseY);break
  case'owl':drawOwl(ctx,drawPx,config,isWorking,frame,baseY);break
  case'fox':drawFox(ctx,drawPx,config,isWorking,frame,baseY);break
  case'fairy':drawFairy(ctx,drawPx,config,isWorking,frame,baseY);break
  case'phoenix':drawPhoenix(ctx,drawPx,config,isWorking,frame,baseY);break
  case'mermaid':drawMermaid(ctx,drawPx,config,isWorking,frame,baseY);break
  case'wolf':drawWolf(ctx,drawPx,config,isWorking,frame,baseY);break
  case'golem':drawGolem(ctx,drawPx,config,isWorking,frame,baseY);break
  case'puppet':drawPuppet(ctx,drawPx,config,isWorking,frame,baseY);break
  case'clockwork':drawClockwork(ctx,drawPx,config,isWorking,frame,baseY);break
  case'mech':drawMech(ctx,drawPx,config,isWorking,frame,baseY);break
  case'dragon':drawDragon(ctx,drawPx,config,isWorking,frame,baseY);break
  case'turtle':drawTurtle(ctx,drawPx,config,isWorking,frame,baseY);break
 }

 if(isWorking){
  ctx.fillStyle=`rgba(255,220,100,${0.3+Math.sin(frame*0.2)*0.2})`
  const sparkleX=14+Math.cos(frame*0.12)*10
  const sparkleY=14+Math.sin(frame*0.17)*8
  drawPx(sparkleX,sparkleY,1,1)
 }

 ctx.restore()
}

type DrawPx=(x:number,y:number,w?:number,h?:number)=>void

function drawWizard(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const float=Math.sin(frame*0.08)*1.5
 const staffGlow=isWorking?0.5+Math.sin(frame*0.2)*0.3:0.3

 ctx.fillStyle='rgba(0,0,0,0.12)'
 drawPx(centerX-4,26,8,1)
 ctx.fillStyle='#5a3a20'
 drawPx(centerX+6,baseY+4+float,1,14)

 ctx.fillStyle=`rgba(${parseInt(config.accentColor.slice(1,3),16)},${parseInt(config.accentColor.slice(3,5),16)},${parseInt(config.accentColor.slice(5,7),16)},${staffGlow})`
 drawPx(centerX+5,baseY+2+float,3,3)
 ctx.fillStyle=config.accentColor
 drawPx(centerX+6,baseY+3+float,1,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-1,baseY+float,2,2)
 drawPx(centerX-2,baseY+2+float,4,2)
 drawPx(centerX-4,baseY+4+float,8,2)

 ctx.fillStyle='#e8d4c4'
 drawPx(centerX-3,baseY+6+float,6,4)

 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-2,baseY+7+float,1,1)
 drawPx(centerX+1,baseY+7+float,1,1)

 ctx.fillStyle='#d0d0d0'
 drawPx(centerX-2,baseY+9+float,4,2)
 drawPx(centerX-1,baseY+11+float,2,3)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+10+float,8,8)
 drawPx(centerX-5,baseY+14+float,10,6)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-1,baseY+11+float,2,6)
}

function drawKnight(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const anim=isWorking?Math.sin(frame*0.12):0

 ctx.fillStyle='rgba(0,0,0,0.15)'
 drawPx(centerX-5,26,10,1)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-1,baseY,2,3)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+2,6,5)

 ctx.fillStyle='#1a1a1a'
 drawPx(centerX-2,baseY+4,4,2)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+5,1,1)
 drawPx(centerX+1,baseY+5,1,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-5,baseY+7,10,6)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+8,4,3)
 ctx.fillStyle='#808080'
 drawPx(centerX+6,baseY+5+anim*2,1,10)
 ctx.fillStyle=config.accentColor
 drawPx(centerX+5,baseY+14+anim*2,3,2)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-8,baseY+8-anim,3,6)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-7,baseY+10-anim,1,2)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+13,2,6)
 drawPx(centerX+1,baseY+13,2,6)
 ctx.fillStyle='#404040'
 drawPx(centerX-4,baseY+18,3,2)
 drawPx(centerX+1,baseY+18,3,2)
}

function drawNinja(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const anim=isWorking?Math.sin(frame*0.25)*2:0
 const jump=isWorking?Math.abs(Math.sin(frame*0.15))*3:0

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-3,26,6,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+2-jump,6,5)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+4-jump,4,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+7-jump,8,6)
 drawPx(centerX-6,baseY+7-jump+anim,2,5)
 drawPx(centerX+4,baseY+7-jump-anim,2,5)
 ctx.fillStyle='#606060'
 drawPx(centerX+5,baseY+4-jump-anim,1,4)
 ctx.fillStyle=config.accentColor
 drawPx(centerX+3,baseY+5-jump,3+anim,2)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+13-jump,2,5)
 drawPx(centerX+1,baseY+13-jump,2,5)
}

function drawSamurai(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const anim=isWorking?Math.sin(frame*0.15):0

 ctx.fillStyle='rgba(0,0,0,0.12)'
 drawPx(centerX-5,26,10,1)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-4,baseY,2,3)
 drawPx(centerX+2,baseY,2,3)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+3,8,4)

 ctx.fillStyle='#d0c0b0'
 drawPx(centerX-2,baseY+5,4,3)
 ctx.fillStyle='#1a1a1a'
 drawPx(centerX-1,baseY+6,1,1)
 drawPx(centerX+1,baseY+6,1,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-5,baseY+8,10,6)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-5,baseY+8,10,1)
 ctx.fillStyle='#808080'
 drawPx(centerX+5+anim,baseY+6,1,12)
 ctx.fillStyle='#2a2a2a'
 drawPx(centerX+4+anim,baseY+16,3,2)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+14,8,6)
}

function drawArcher(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const drawAnim=isWorking?Math.sin(frame*0.1)*2:0

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-4,26,8,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+1,6,4)
 drawPx(centerX-4,baseY+3,8,2)

 ctx.fillStyle='#e8d4c4'
 drawPx(centerX-2,baseY+4,4,4)
 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-1,baseY+5,1,1)
 drawPx(centerX+1,baseY+5,1,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+8,8,6)
 ctx.fillStyle='#6a4a30'
 drawPx(centerX-7,baseY+4,1,12)
 ctx.fillStyle='#d0d0d0'
 drawPx(centerX-6,baseY+4,1,1)
 drawPx(centerX-5-drawAnim,baseY+10,1,1)
 drawPx(centerX-6,baseY+15,1,1)
 if(isWorking){
  ctx.fillStyle='#808080'
  drawPx(centerX-4-drawAnim,baseY+10,4,1)
 }
 ctx.fillStyle=config.accentColor
 drawPx(centerX+4,baseY+8,2,8)

 ctx.fillStyle='#4a3a2a'
 drawPx(centerX-2,baseY+14,2,5)
 drawPx(centerX+1,baseY+14,2,5)
}

function drawPrincess(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const sway=Math.sin(frame*0.08)*0.5

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-4,26,8,1)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+1,4,2)
 drawPx(centerX-1,baseY,2,1)

 ctx.fillStyle='#5a4030'
 drawPx(centerX-4,baseY+2,8,6)
 drawPx(centerX-5,baseY+5,2,8)
 drawPx(centerX+3,baseY+5,2,8)

 ctx.fillStyle='#f0dcc8'
 drawPx(centerX-3,baseY+3,6,5)
 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-2,baseY+5,1.5,1.5)
 drawPx(centerX+0.5,baseY+5,1.5,1.5)

 ctx.fillStyle='#c08080'
 drawPx(centerX-0.5,baseY+7,1,0.5)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+8,8,4)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-5,baseY+12+sway,10,8)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-1,baseY+9,2,2)
 drawPx(centerX-4,baseY+14+sway,8,1)
}

function drawBard(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const strum=isWorking?Math.sin(frame*0.3)*1.5:0
 const noteY=isWorking?(frame*0.5)%10:0

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-4,26,8,1)
 if(isWorking){
  ctx.fillStyle=config.accentColor
  drawPx(centerX+5,baseY+2-noteY,2,2)
 }
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+2,6,3)

 ctx.fillStyle=config.accentColor
 drawPx(centerX+2,baseY,2,3)

 ctx.fillStyle='#e8d4c4'
 drawPx(centerX-2,baseY+4,4,4)
 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-1,baseY+5,1,1)
 drawPx(centerX+1,baseY+5,1,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+8,8,6)
 ctx.fillStyle='#8a6a40'
 drawPx(centerX-7,baseY+10+strum,4,6)
 ctx.fillStyle='#6a4a30'
 drawPx(centerX-6,baseY+8+strum,2,3)
 ctx.fillStyle='#d0d0d0'
 drawPx(centerX-5,baseY+11+strum,1,4)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-2,baseY+14,2,5)
 drawPx(centerX+1,baseY+14,2,5)
}

function drawDruid(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const leafSway=Math.sin(frame*0.1)*1

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-4,26,8,1)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+1+leafSway,2,2)
 drawPx(centerX+1,baseY+1-leafSway,2,2)
 drawPx(centerX-1,baseY,2,2)
 ctx.fillStyle='#6a5a4a'
 drawPx(centerX-3,baseY+2,6,5)
 drawPx(centerX-4,baseY+5,2,6)
 drawPx(centerX+2,baseY+5,2,6)

 ctx.fillStyle='#e8d4c4'
 drawPx(centerX-2,baseY+4,4,4)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-1,baseY+5,1,1)
 drawPx(centerX+1,baseY+5,1,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+8,8,6)
 drawPx(centerX-5,baseY+12,10,8)
 ctx.fillStyle='#5a4a30'
 drawPx(centerX+5,baseY+4,1,14)

 ctx.fillStyle=config.accentColor
 drawPx(centerX+4,baseY+2,3,3)
}

function drawAlchemist(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const bubble=isWorking?Math.sin(frame*0.3)*2:0

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-4,26,8,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+1,6,4)

 ctx.fillStyle='#e8d4c4'
 drawPx(centerX-2,baseY+4,4,4)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+5,1.5,1.5)
 drawPx(centerX+0.5,baseY+5,1.5,1.5)
 ctx.fillStyle='#e0e0e0'
 drawPx(centerX-4,baseY+8,8,8)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+9,6,6)
 ctx.fillStyle='#90c0d0'
 drawPx(centerX+4,baseY+10,3,5)

 if(isWorking){
  ctx.fillStyle=config.accentColor
  drawPx(centerX+5,baseY+8-bubble,1,1)
  drawPx(centerX+4,baseY+6-bubble,1,1)
 }

 ctx.fillStyle='#4a4a4a'
 drawPx(centerX-2,baseY+16,2,4)
 drawPx(centerX+1,baseY+16,2,4)
}

function drawEngineer(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const wrench=isWorking?Math.sin(frame*0.2)*2:0

 ctx.fillStyle='rgba(0,0,0,0.12)'
 drawPx(centerX-4,26,8,1)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+1,6,4)

 ctx.fillStyle=isWorking?'#ffff00':'#808080'
 drawPx(centerX-1,baseY+2,2,1)

 ctx.fillStyle='#e8d4c4'
 drawPx(centerX-2,baseY+4,4,4)
 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-1,baseY+5,1,1)
 drawPx(centerX+1,baseY+5,1,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+8,8,7)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+10,2,2)
 drawPx(centerX+1,baseY+10,2,2)
 ctx.fillStyle='#606060'
 drawPx(centerX+5,baseY+8+wrench,2,6)
 ctx.fillStyle='#808080'
 drawPx(centerX+4,baseY+7+wrench,4,2)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+15,2,4)
 drawPx(centerX+1,baseY+15,2,4)
}

function drawCat(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const anim=isWorking?Math.sin(frame*0.2)*2:0

 ctx.fillStyle='rgba(0,0,0,0.12)'
 drawPx(centerX-5,25,10,1)

 ctx.fillStyle=config.bodyColor
 const tailWave=Math.sin(frame*0.1)*2
 drawPx(centerX+5,baseY+8+tailWave,2,6)
 drawPx(centerX+6,baseY+6+tailWave,2,3)

 drawPx(centerX-5,baseY+10,10,6)

 drawPx(centerX-4,baseY+2,8,8)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY,2,3)
 drawPx(centerX+2,baseY,2,3)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+1,1,1)
 drawPx(centerX+2,baseY+1,1,1)

 ctx.fillStyle='#40a040'
 drawPx(centerX-3,baseY+5,2,2)
 drawPx(centerX+1,baseY+5,2,2)

 ctx.fillStyle='#1a1a1a'
 drawPx(centerX-2.5,baseY+5.5,1,1)
 drawPx(centerX+1.5,baseY+5.5,1,1)

 ctx.fillStyle='#ff9090'
 drawPx(centerX-0.5,baseY+7,1,1)

 ctx.fillStyle='#ffffff'
 drawPx(centerX-6,baseY+7,2,0.5)
 drawPx(centerX+4,baseY+7,2,0.5)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+16,2,4+anim)
 drawPx(centerX+2,baseY+16,2,4-anim)
}

function drawOwl(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const blink=Math.floor(frame/30)%5===0
 const headTilt=Math.sin(frame*0.05)*1

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-4,26,8,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+10,8,10)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4+headTilt,baseY+2,8,8)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-4+headTilt,baseY+1,2,3)
 drawPx(centerX+2+headTilt,baseY+1,2,3)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-3+headTilt,baseY+4,6,4)
 ctx.fillStyle='#ffcc00'
 drawPx(centerX-2+headTilt,baseY+5,2,2)
 drawPx(centerX+1+headTilt,baseY+5,2,2)
 if(!blink){
  ctx.fillStyle='#1a1a1a'
  drawPx(centerX-1.5+headTilt,baseY+5.5,1,1)
  drawPx(centerX+1.5+headTilt,baseY+5.5,1,1)
 }

 ctx.fillStyle='#e0a020'
 drawPx(centerX-0.5+headTilt,baseY+7,1,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-6,baseY+11,2,6)
 drawPx(centerX+4,baseY+11,2,6)

 ctx.fillStyle='#e0a020'
 drawPx(centerX-2,baseY+18,1,2)
 drawPx(centerX+1,baseY+18,1,2)
}

function drawFox(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const tailWag=isWorking?Math.sin(frame*0.2)*3:0

 ctx.fillStyle='rgba(0,0,0,0.1)'
 drawPx(centerX-5,26,10,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX+4+tailWag,baseY+10,4,6)
 ctx.fillStyle='#ffffff'
 drawPx(centerX+6+tailWag,baseY+14,2,2)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+12,8,6)

 drawPx(centerX-4,baseY+4,8,8)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-5,baseY+2,3,4)
 drawPx(centerX+2,baseY+2,3,4)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-4,baseY+3,1,2)
 drawPx(centerX+3,baseY+3,1,2)
 ctx.fillStyle='#ffffff'
 drawPx(centerX-2,baseY+6,4,5)

 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-2,baseY+6,1.5,1.5)
 drawPx(centerX+0.5,baseY+6,1.5,1.5)

 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-0.5,baseY+9,1,1)

 ctx.fillStyle='#2a2a2a'
 drawPx(centerX-3,baseY+18,2,2)
 drawPx(centerX+1,baseY+18,2,2)
}

function drawFairy(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const float=Math.sin(frame*0.12)*3
 const wingFlap=Math.sin(frame*0.3)*2
 ctx.fillStyle=`rgba(${parseInt(config.accentColor.slice(1,3),16)},${parseInt(config.accentColor.slice(3,5),16)},${parseInt(config.accentColor.slice(5,7),16)},0.2)`
 drawPx(centerX-6,baseY+4+float,12,12)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-7,baseY+6+float-wingFlap,3,6)
 drawPx(centerX+4,baseY+6+float-wingFlap,3,6)
 drawPx(centerX-6,baseY+10+float+wingFlap,2,4)
 drawPx(centerX+4,baseY+10+float+wingFlap,2,4)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-2,baseY+3+float,4,4)

 ctx.fillStyle='#f0e0d0'
 drawPx(centerX-1,baseY+5+float,2,3)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-1,baseY+6+float,0.5,0.5)
 drawPx(centerX+0.5,baseY+6+float,0.5,0.5)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-2,baseY+8+float,4,4)
 drawPx(centerX-3,baseY+11+float,6,3)
 if(isWorking){
  ctx.fillStyle='#ffffff'
  const sparkle=(frame*0.2)%6
  drawPx(centerX-4+sparkle,baseY+4+float,1,1)
  drawPx(centerX+2-sparkle,baseY+8+float,1,1)
 }
}

function drawPhoenix(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const fly=isWorking?Math.sin(frame*0.15)*2:0
 const wingFlap=isWorking?Math.abs(Math.sin(frame*0.25))*4:0
 const flame=Math.sin(frame*0.3)*1
 if(isWorking){
  ctx.fillStyle='rgba(255,150,50,0.3)'
  drawPx(centerX-5,baseY+4+fly,10,14)
 }
 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+14+fly+flame,4,6)
 drawPx(centerX-1,baseY+18+fly+flame,2,3)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-8,baseY+8+fly-wingFlap,4,4)
 drawPx(centerX+4,baseY+8+fly-wingFlap,4,4)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-7,baseY+10+fly-wingFlap,2,2)
 drawPx(centerX+5,baseY+10+fly-wingFlap,2,2)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+6+fly,6,8)

 drawPx(centerX-2,baseY+2+fly,4,5)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-1,baseY+fly,2,3)

 ctx.fillStyle='#ffcc00'
 drawPx(centerX-1,baseY+4+fly,1,1)
 drawPx(centerX+1,baseY+4+fly,1,1)

 ctx.fillStyle='#e0a020'
 drawPx(centerX-0.5,baseY+6+fly,1,1)
}

function drawMermaid(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const swim=Math.sin(frame*0.1)*1.5
 const tailWave=Math.sin(frame*0.15)*2

 ctx.fillStyle='rgba(0,0,0,0.08)'
 drawPx(centerX-4,26,8,1)
 ctx.fillStyle='#4a6060'
 drawPx(centerX-4,baseY+2+swim,8,6)
 drawPx(centerX-5,baseY+6+swim,2,8)
 drawPx(centerX+3,baseY+6+swim,2,8)

 ctx.fillStyle='#f0e8e0'
 drawPx(centerX-2,baseY+3+swim,4,4)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-1,baseY+4+swim,1,1)
 drawPx(centerX+1,baseY+4+swim,1,1)
 ctx.fillStyle='#f0e8e0'
 drawPx(centerX-3,baseY+7+swim,6,4)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+8+swim,1.5,1.5)
 drawPx(centerX+0.5,baseY+8+swim,1.5,1.5)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-2,baseY+11+swim,4,4)
 drawPx(centerX-1,baseY+15+swim+tailWave,2,3)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+17+swim+tailWave,2,3)
 drawPx(centerX+1,baseY+17+swim+tailWave,2,3)
}

function drawWolf(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const howl=isWorking&&Math.floor(frame/20)%3===0

 ctx.fillStyle='rgba(0,0,0,0.12)'
 drawPx(centerX-5,26,10,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX+4,baseY+10,3,4)
 drawPx(centerX+5,baseY+8,2,3)

 drawPx(centerX-4,baseY+12,8,6)

 if(howl){
  drawPx(centerX-3,baseY+4,6,4)
  drawPx(centerX-1,baseY+2,2,3)
  ctx.fillStyle='#1a1a1a'
  drawPx(centerX-0.5,baseY+2,1,2)
 }else{
  drawPx(centerX-3,baseY+5,6,6)
  ctx.fillStyle=config.accentColor
  drawPx(centerX-1,baseY+8,2,3)
  ctx.fillStyle='#1a1a1a'
  drawPx(centerX-0.5,baseY+9,1,1)
 }

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+3,2,3)
 drawPx(centerX+2,baseY+3,2,3)

 ctx.fillStyle='#c0a000'
 drawPx(centerX-2,baseY+6,1.5,1.5)
 drawPx(centerX+0.5,baseY+6,1.5,1.5)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+18,2,2)
 drawPx(centerX+1,baseY+18,2,2)
}

function drawGolem(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const stomp=isWorking?Math.abs(Math.sin(frame*0.1))*1:0

 ctx.fillStyle='rgba(0,0,0,0.2)'
 drawPx(centerX-6,26,12,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+2+stomp,6,5)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+4+stomp,1.5,1.5)
 drawPx(centerX+0.5,baseY+4+stomp,1.5,1.5)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-5,baseY+7+stomp,10,8)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-1,baseY+9+stomp,2,4)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-8,baseY+8+stomp,3,8)
 drawPx(centerX+5,baseY+8+stomp,3,8)

 drawPx(centerX-9,baseY+15+stomp,4,3)
 drawPx(centerX+5,baseY+15+stomp,4,3)
 drawPx(centerX-4,baseY+15,3,5)
 drawPx(centerX+1,baseY+15,3,5)
}

function drawPuppet(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const dangle=Math.sin(frame*0.15)*2
 const armSwing=Math.sin(frame*0.2)*3
 ctx.fillStyle='#808080'
 drawPx(centerX,baseY,1,4)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+3+dangle,6,5)

 ctx.fillStyle='#1a1a1a'
 drawPx(centerX-2,baseY+5+dangle,1.5,1.5)
 drawPx(centerX+0.5,baseY+5+dangle,1.5,1.5)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-1,baseY+7+dangle,2,0.5)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+8+dangle,6,6)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+9+dangle,4,2)
 ctx.fillStyle='#808080'
 drawPx(centerX-5,baseY+2,1,6+armSwing)
 drawPx(centerX+4,baseY+2,1,6-armSwing)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-6,baseY+8+dangle+armSwing,2,4)
 drawPx(centerX+4,baseY+8+dangle-armSwing,2,4)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-2,baseY+14+dangle,2,4)
 drawPx(centerX+1,baseY+14+dangle,2,4)
}

function drawClockwork(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const gearRotate=(frame*2)%360
 const tick=Math.floor(frame/10)%2

 ctx.fillStyle='rgba(0,0,0,0.12)'
 drawPx(centerX-5,26,10,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+2,8,6)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+3,6,4)

 ctx.fillStyle='#1a1a1a'
 drawPx(centerX,baseY+4,1,2)
 drawPx(centerX-1+tick,baseY+5,2,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-5,baseY+8,10,8)

 ctx.fillStyle=config.accentColor
 const gx=Math.cos(gearRotate*0.02)*0.5
 const gy=Math.sin(gearRotate*0.02)*0.5
 drawPx(centerX-2+gx,baseY+10+gy,4,4)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-1,baseY+11,2,2)
 ctx.fillStyle='#606060'
 drawPx(centerX-7,baseY+9,2,5)
 drawPx(centerX+5,baseY+9,2,5)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-7,baseY+13,2,1)
 drawPx(centerX+5,baseY+13,2,1)

 ctx.fillStyle='#606060'
 drawPx(centerX-3,baseY+16,2,4)
 drawPx(centerX+1,baseY+16,2,4)
}

function drawMech(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const walk=isWorking?Math.sin(frame*0.12)*1:0

 ctx.fillStyle='rgba(0,0,0,0.15)'
 drawPx(centerX-6,26,12,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+2,6,4)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+3,4,2)

 ctx.fillStyle=isWorking?'#00ff00':'#404040'
 drawPx(centerX-1,baseY+4,1,1)
 drawPx(centerX+1,baseY+4,1,1)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+6,8,7)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+7,6,4)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-7,baseY+6,3,3)
 drawPx(centerX+4,baseY+6,3,3)

 ctx.fillStyle='#606060'
 drawPx(centerX-7,baseY+9,2,6)
 drawPx(centerX+5,baseY+9,2,6)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-8,baseY+14,3,2)
 drawPx(centerX+5,baseY+14,3,2)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+13+walk,3,5)
 drawPx(centerX+1,baseY+13-walk,3,5)
 ctx.fillStyle='#606060'
 drawPx(centerX-5,baseY+17+walk,4,3)
 drawPx(centerX+1,baseY+17-walk,4,3)
}

function drawDragon(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const breathe=Math.sin(frame*0.08)*0.5
 const wingFlap=isWorking?Math.sin(frame*0.2)*3:0
 if(isWorking&&Math.floor(frame/15)%2===0){
  ctx.fillStyle=config.accentColor
  drawPx(centerX+4,baseY+8,4,2)
  drawPx(centerX+6,baseY+7,2,1)
 }

 ctx.fillStyle=config.accentColor
 drawPx(centerX-9,baseY+6-wingFlap,4,5)
 drawPx(centerX+5,baseY+6-wingFlap,4,5)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-6,baseY+14,3,3)
 drawPx(centerX-8,baseY+16,2,2)
 ctx.fillStyle=config.accentColor
 drawPx(centerX-9,baseY+17,2,2)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-4,baseY+10+breathe,8,8)

 drawPx(centerX-2,baseY+4+breathe,6,6)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-2,baseY+2+breathe,2,3)
 drawPx(centerX+2,baseY+2+breathe,2,3)

 ctx.fillStyle='#ff6600'
 drawPx(centerX,baseY+6+breathe,2,2)
 ctx.fillStyle='#1a1a1a'
 drawPx(centerX+0.5,baseY+6.5+breathe,1,1)
 ctx.fillStyle='#1a1a1a'
 drawPx(centerX+2,baseY+8+breathe,1,1)

 ctx.fillStyle=config.bodyColor
 drawPx(centerX-3,baseY+17,2,3)
 drawPx(centerX+1,baseY+17,2,3)
}

function drawTurtle(ctx:CanvasRenderingContext2D,drawPx:DrawPx,config:AgentDisplayConfig,isWorking:boolean,frame:number,baseY:number){
 const centerX=14
 const crawl=isWorking?Math.sin(frame*0.08)*1:0

 ctx.fillStyle='rgba(0,0,0,0.15)'
 drawPx(centerX-6,26,12,1)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-6,baseY+16,2,2)
 ctx.fillStyle=config.bodyColor
 drawPx(centerX-5,baseY+8,10,8)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-3,baseY+10,2,2)
 drawPx(centerX+1,baseY+10,2,2)
 drawPx(centerX-1,baseY+13,2,2)

 ctx.fillStyle=config.accentColor
 drawPx(centerX+3,baseY+10+crawl,4,4)
 ctx.fillStyle='#1a1a1a'
 drawPx(centerX+5,baseY+11+crawl,1,1)

 ctx.fillStyle=config.accentColor
 drawPx(centerX-5,baseY+16+crawl,2,2)
 drawPx(centerX+3,baseY+16-crawl,2,2)
 drawPx(centerX-5,baseY+10-crawl,2,2)
 drawPx(centerX+3,baseY+10+crawl,2,2)
}
