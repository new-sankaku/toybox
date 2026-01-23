import type { AgentType,AgentStatus } from '@/types/agent'

export interface DemoEvent {
 time: number
 type: 'spawn'|'status_change'|'task_update'|'complete'|'despawn'|'phase_change'|'llm_call'|'approval_request'|'approval_granted'
 agentId: string
 agentType?: AgentType
 parentId?: string|null
 status?: AgentStatus
 task?: string
 sound?: 'spawn'|'complete'|'approval'|'error'|'phase'
 aiService?: 'claude'|'openai'|'gemini'
 phase?: number
 metadata?: {
  step?: number
  totalSteps?: number
  action?: string
  detail?: string
  llmTokens?: number
  fileName?: string
  retryCount?: number
 }
}

export interface DemoScenario {
 name: string
 description: string
 events: DemoEvent[]
 totalDuration: number
}

let idCounter=0
function genId(prefix: string): string {
 return `demo-${prefix}-${++idCounter}`
}

function formatTask(step: number,total: number,action: string,detail: string): string {
 return `[${step}/${total}] ${action}: ${detail}`
}

const ACTIONS={
 INIT: '初期化',
 LLM_CALL: 'LLM呼び出し',
 LLM_WAIT: 'LLM応答待ち',
 FILE_READ: 'ファイル読み込み',
 FILE_SAVE: 'ファイル保存',
 VALIDATE: '検証',
 WAIT: '待機',
 ERROR: 'エラー処理',
 COMPLETE: '完了',
}

interface AgentDef {
 id: string
 type: AgentType
 name: string
 parentId: string|null
 steps: Array<{action: string; detail: string; duration: number; aiService?: 'claude'|'openai'|'gemini'}>
}

function createAgentWorkflow(
 agent: AgentDef,
 startTime: number,
 events: DemoEvent[]
): number {
 let t=startTime
 const totalSteps=agent.steps.length

 events.push({
  time: t,
  type: 'spawn',
  agentId: agent.id,
  agentType: agent.type,
  parentId: agent.parentId,
  status: 'running',
  task: formatTask(1,totalSteps,agent.steps[0].action,agent.steps[0].detail),
  sound: 'spawn',
  metadata: { step: 1,totalSteps,action: agent.steps[0].action,detail: agent.steps[0].detail },
 })

 for (let i=0;i<agent.steps.length;i++) {
  const step=agent.steps[i]
  if (i>0) {
   events.push({
    time: t,
    type: 'task_update',
    agentId: agent.id,
    task: formatTask(i+1,totalSteps,step.action,step.detail),
    metadata: { step: i+1,totalSteps,action: step.action,detail: step.detail },
   })
  }

  if (step.aiService) {
   events.push({
    time: t+100,
    type: 'llm_call',
    agentId: agent.id,
    aiService: step.aiService,
   })
  }

  t+=step.duration
 }

 return t
}

export function createFullDemoScenario(): DemoScenario {
 idCounter=0
 const events: DemoEvent[]=[]
 let t=0

 const orchId=genId('orch')

 events.push({
  time: t,
  type: 'phase_change',
  agentId: orchId,
  phase: 0,
  sound: 'phase',
 })

 events.push({
  time: t,
  type: 'spawn',
  agentId: orchId,
  agentType: 'orchestrator',
  parentId: null,
  status: 'running',
  task: formatTask(1,3,ACTIONS.INIT,'プロジェクト情報を読み込み中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 3,action: ACTIONS.INIT,detail: 'プロジェクト情報を読み込み中' },
 })

 t+=1500
 events.push({
  time: t,
  type: 'task_update',
  agentId: orchId,
  task: formatTask(2,3,ACTIONS.LLM_CALL,'プロジェクト分析中'),
  metadata: { step: 2,totalSteps: 3,action: ACTIONS.LLM_CALL,detail: 'プロジェクト分析中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: orchId,
  aiService: 'claude',
 })

 t+=2000

 const conceptId=genId('concept')
 t=createAgentWorkflow({
  id: conceptId,
  type: 'concept',
  name: 'コンセプト',
  parentId: orchId,
  steps: [
   { action: ACTIONS.INIT,detail: 'プロジェクト設定を読み込み中',duration: 800 },
   { action: ACTIONS.LLM_CALL,detail: 'ゲームコンセプトを生成中',duration: 2500,aiService: 'claude' },
   { action: ACTIONS.VALIDATE,detail: '出力形式をチェック中',duration: 600 },
   { action: ACTIONS.FILE_SAVE,detail: 'concept.md を保存中',duration: 400 },
  ],
 },t,events)

 events.push({
  time: t,
  type: 'status_change',
  agentId: conceptId,
  status: 'completed',
  task: formatTask(4,4,ACTIONS.COMPLETE,'コンセプト生成完了'),
  sound: 'complete',
 })

 t+=500
 events.push({
  time: t,
  type: 'task_update',
  agentId: orchId,
  task: formatTask(3,3,ACTIONS.COMPLETE,'Phase0完了、Phase1へ移行'),
  metadata: { step: 3,totalSteps: 3,action: ACTIONS.COMPLETE,detail: 'Phase0完了、Phase1へ移行' },
 })

 t+=1000
 events.push({
  time: t,
  type: 'phase_change',
  agentId: orchId,
  phase: 1,
  sound: 'phase',
 })

 const dir1Id=genId('dir1')
 events.push({
  time: t,
  type: 'spawn',
  agentId: dir1Id,
  agentType: 'director_phase1',
  parentId: orchId,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'Phase1開始: 企画フェーズ'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: 'Phase1開始: 企画フェーズ' },
 })

 events.push({
  time: t+200,
  type: 'status_change',
  agentId: orchId,
  status: 'pending',
  task: 'DIRECTORに委譲',
 })

 t+=1000
 events.push({
  time: t,
  type: 'task_update',
  agentId: dir1Id,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'LEADER編成を計画中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: 'LEADER編成を計画中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: dir1Id,
  aiService: 'claude',
 })

 t+=1500

 const scenarioLeaderId=genId('scenario-leader')
 events.push({
  time: t,
  type: 'spawn',
  agentId: scenarioLeaderId,
  agentType: 'leader_scenario',
  parentId: dir1Id,
  status: 'running',
  task: formatTask(1,5,ACTIONS.INIT,'コンセプト情報を読み込み中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 5,action: ACTIONS.INIT,detail: 'コンセプト情報を読み込み中' },
 })

 t+=800
 const taskSplitLeaderId=genId('tasksplit-leader')
 events.push({
  time: t,
  type: 'spawn',
  agentId: taskSplitLeaderId,
  agentType: 'leader_task_split',
  parentId: dir1Id,
  status: 'running',
  task: formatTask(1,5,ACTIONS.INIT,'プロジェクト構造を分析中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 5,action: ACTIONS.INIT,detail: 'プロジェクト構造を分析中' },
 })

 events.push({
  time: t,
  type: 'task_update',
  agentId: dir1Id,
  task: formatTask(3,4,ACTIONS.WAIT,'LEADER作業を監視中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.WAIT,detail: 'LEADER作業を監視中' },
 })

 t+=500
 events.push({
  time: t,
  type: 'task_update',
  agentId: scenarioLeaderId,
  task: formatTask(2,5,ACTIONS.LLM_CALL,'シナリオ構成を計画中'),
  metadata: { step: 2,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: 'シナリオ構成を計画中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: scenarioLeaderId,
  aiService: 'claude',
 })

 t+=500
 events.push({
  time: t,
  type: 'task_update',
  agentId: taskSplitLeaderId,
  task: formatTask(2,5,ACTIONS.LLM_CALL,'タスク分解を実行中'),
  metadata: { step: 2,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: 'タスク分解を実行中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: taskSplitLeaderId,
  aiService: 'claude',
 })

 t+=1000

 const scenarioWorkers: string[]=[]
 for (let i=0;i<2;i++) {
  const workerId=genId(`scenario-worker-${i}`)
  scenarioWorkers.push(workerId)
  events.push({
   time: t+i*400,
   type: 'spawn',
   agentId: workerId,
   agentType: 'worker_scenario',
   parentId: scenarioLeaderId,
   status: 'running',
   task: formatTask(1,4,ACTIONS.INIT,`シナリオパート${i+1}を準備中`),
   sound: 'spawn',
   metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: `シナリオパート${i+1}を準備中` },
  })
 }

 events.push({
  time: t+200,
  type: 'task_update',
  agentId: scenarioLeaderId,
  task: formatTask(3,5,ACTIONS.WAIT,'WORKER完了を待機中'),
  metadata: { step: 3,totalSteps: 5,action: ACTIONS.WAIT,detail: 'WORKER完了を待機中' },
 })

 t+=1200

 for (let i=0;i<scenarioWorkers.length;i++) {
  events.push({
   time: t+i*300,
   type: 'task_update',
   agentId: scenarioWorkers[i],
   task: formatTask(2,4,ACTIONS.LLM_CALL,`シナリオパート${i+1}を生成中`),
   metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: `シナリオパート${i+1}を生成中` },
  })
  events.push({
   time: t+i*300+100,
   type: 'llm_call',
   agentId: scenarioWorkers[i],
   aiService: i===0?'openai':'gemini',
  })
 }

 t+=2000
 const taskSplitWorkers: string[]=[]
 for (let i=0;i<2;i++) {
  const workerId=genId(`tasksplit-worker-${i}`)
  taskSplitWorkers.push(workerId)
  events.push({
   time: t+i*300,
   type: 'spawn',
   agentId: workerId,
   agentType: 'worker_task_split',
   parentId: taskSplitLeaderId,
   status: 'running',
   task: formatTask(1,4,ACTIONS.INIT,`タスク分析${i+1}を準備中`),
   sound: 'spawn',
   metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: `タスク分析${i+1}を準備中` },
  })
 }

 events.push({
  time: t+100,
  type: 'task_update',
  agentId: taskSplitLeaderId,
  task: formatTask(3,5,ACTIONS.WAIT,'WORKER完了を待機中'),
  metadata: { step: 3,totalSteps: 5,action: ACTIONS.WAIT,detail: 'WORKER完了を待機中' },
 })

 t+=1500

 for (let i=0;i<scenarioWorkers.length;i++) {
  events.push({
   time: t+i*200,
   type: 'task_update',
   agentId: scenarioWorkers[i],
   task: formatTask(3,4,ACTIONS.VALIDATE,`シナリオパート${i+1}を検証中`),
   metadata: { step: 3,totalSteps: 4,action: ACTIONS.VALIDATE,detail: `シナリオパート${i+1}を検証中` },
  })
 }

 t+=800
 for (let i=0;i<scenarioWorkers.length;i++) {
  events.push({
   time: t+i*200,
   type: 'task_update',
   agentId: scenarioWorkers[i],
   task: formatTask(4,4,ACTIONS.FILE_SAVE,`scenario_part${i+1}.md を保存中`),
   metadata: { step: 4,totalSteps: 4,action: ACTIONS.FILE_SAVE,detail: `scenario_part${i+1}.md を保存中`,fileName: `scenario_part${i+1}.md` },
  })
 }

 t+=600
 for (let i=0;i<scenarioWorkers.length;i++) {
  events.push({
   time: t+i*300,
   type: 'status_change',
   agentId: scenarioWorkers[i],
   status: 'completed',
   task: formatTask(4,4,ACTIONS.COMPLETE,`シナリオパート${i+1}完了`),
   sound: 'complete',
  })
 }

 t+=800
 events.push({
  time: t,
  type: 'task_update',
  agentId: scenarioLeaderId,
  task: formatTask(4,5,ACTIONS.LLM_CALL,'成果物を統合中'),
  metadata: { step: 4,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: '成果物を統合中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: scenarioLeaderId,
  aiService: 'claude',
 })

 t+=1500
 events.push({
  time: t,
  type: 'task_update',
  agentId: scenarioLeaderId,
  task: formatTask(5,5,'Human承認','シナリオ承認を提出中'),
  metadata: { step: 5,totalSteps: 5,action: 'Human承認',detail: 'シナリオ承認を提出中' },
 })
 events.push({
  time: t+200,
  type: 'status_change',
  agentId: scenarioLeaderId,
  status: 'waiting_approval',
  task: 'シナリオ承認待ち',
  sound: 'approval',
 })

 t+=1000

 for (let i=0;i<taskSplitWorkers.length;i++) {
  events.push({
   time: t+i*200,
   type: 'task_update',
   agentId: taskSplitWorkers[i],
   task: formatTask(2,4,ACTIONS.LLM_CALL,`タスク分析${i+1}を実行中`),
   metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: `タスク分析${i+1}を実行中` },
  })
  events.push({
   time: t+i*200+100,
   type: 'llm_call',
   agentId: taskSplitWorkers[i],
   aiService: 'openai',
  })
 }

 t+=1500

 for (let i=0;i<taskSplitWorkers.length;i++) {
  events.push({
   time: t+i*300,
   type: 'status_change',
   agentId: taskSplitWorkers[i],
   status: 'completed',
   task: formatTask(4,4,ACTIONS.COMPLETE,`タスク分析${i+1}完了`),
   sound: 'complete',
  })
 }

 t+=800
 events.push({
  time: t,
  type: 'task_update',
  agentId: taskSplitLeaderId,
  task: formatTask(4,5,ACTIONS.LLM_CALL,'タスク一覧を統合中'),
  metadata: { step: 4,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: 'タスク一覧を統合中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: taskSplitLeaderId,
  aiService: 'claude',
 })

 t+=1200
 events.push({
  time: t,
  type: 'task_update',
  agentId: taskSplitLeaderId,
  task: formatTask(5,5,'Human承認','タスク分解承認を提出中'),
  metadata: { step: 5,totalSteps: 5,action: 'Human承認',detail: 'タスク分解承認を提出中' },
 })
 events.push({
  time: t+200,
  type: 'status_change',
  agentId: taskSplitLeaderId,
  status: 'waiting_approval',
  task: 'タスク分解承認待ち',
  sound: 'approval',
 })

 t+=2500
 events.push({
  time: t,
  type: 'approval_granted',
  agentId: scenarioLeaderId,
  sound: 'complete',
 })
 events.push({
  time: t,
  type: 'status_change',
  agentId: scenarioLeaderId,
  status: 'completed',
  task: 'シナリオ承認済み',
 })

 t+=500
 events.push({
  time: t,
  type: 'approval_granted',
  agentId: taskSplitLeaderId,
  sound: 'complete',
 })
 events.push({
  time: t,
  type: 'status_change',
  agentId: taskSplitLeaderId,
  status: 'completed',
  task: 'タスク分解承認済み',
 })

 t+=500
 events.push({
  time: t,
  type: 'task_update',
  agentId: dir1Id,
  task: formatTask(4,4,ACTIONS.COMPLETE,'Phase1完了'),
  metadata: { step: 4,totalSteps: 4,action: ACTIONS.COMPLETE,detail: 'Phase1完了' },
 })
 events.push({
  time: t+200,
  type: 'status_change',
  agentId: dir1Id,
  status: 'completed',
  task: 'Phase1完了',
  sound: 'complete',
 })

 t+=1000
 events.push({
  time: t,
  type: 'status_change',
  agentId: orchId,
  status: 'running',
  task: formatTask(1,2,ACTIONS.INIT,'Phase2準備中'),
  metadata: { step: 1,totalSteps: 2,action: ACTIONS.INIT,detail: 'Phase2準備中' },
 })

 t+=500
 events.push({
  time: t,
  type: 'phase_change',
  agentId: orchId,
  phase: 2,
  sound: 'phase',
 })

 const dir2Id=genId('dir2')
 events.push({
  time: t,
  type: 'spawn',
  agentId: dir2Id,
  agentType: 'director_phase2',
  parentId: orchId,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'Phase2開始: 開発フェーズ'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: 'Phase2開始: 開発フェーズ' },
 })

 events.push({
  time: t+200,
  type: 'status_change',
  agentId: orchId,
  status: 'pending',
  task: 'DIRECTORに委譲',
 })

 t+=1000
 events.push({
  time: t,
  type: 'task_update',
  agentId: dir2Id,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'並列実行計画を策定中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: '並列実行計画を策定中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: dir2Id,
  aiService: 'claude',
 })

 t+=1500

 const worldId=genId('world')
 const characterId=genId('character')
 const designId=genId('design')
 const codeLeaderId=genId('code-leader')
 const assetLeaderId=genId('asset-leader')

 events.push({
  time: t,
  type: 'spawn',
  agentId: worldId,
  agentType: 'world',
  parentId: dir2Id,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'世界観情報を読み込み中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: '世界観情報を読み込み中' },
 })

 events.push({
  time: t+300,
  type: 'spawn',
  agentId: characterId,
  agentType: 'character',
  parentId: dir2Id,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'キャラクター設計を準備中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: 'キャラクター設計を準備中' },
 })

 events.push({
  time: t+600,
  type: 'spawn',
  agentId: designId,
  agentType: 'game_design',
  parentId: dir2Id,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'ゲームメカニクスを分析中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: 'ゲームメカニクスを分析中' },
 })

 events.push({
  time: t+900,
  type: 'spawn',
  agentId: codeLeaderId,
  agentType: 'leader_code',
  parentId: dir2Id,
  status: 'running',
  task: formatTask(1,5,ACTIONS.INIT,'コード実装計画を策定中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 5,action: ACTIONS.INIT,detail: 'コード実装計画を策定中' },
 })

 events.push({
  time: t+1200,
  type: 'spawn',
  agentId: assetLeaderId,
  agentType: 'leader_asset',
  parentId: dir2Id,
  status: 'running',
  task: formatTask(1,5,ACTIONS.INIT,'アセット制作計画を策定中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 5,action: ACTIONS.INIT,detail: 'アセット制作計画を策定中' },
 })

 events.push({
  time: t+500,
  type: 'task_update',
  agentId: dir2Id,
  task: formatTask(3,4,ACTIONS.WAIT,'並列実行を監視中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.WAIT,detail: '並列実行を監視中' },
 })

 t+=1500

 events.push({
  time: t,
  type: 'task_update',
  agentId: worldId,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'世界観設定を生成中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: '世界観設定を生成中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: worldId,
  aiService: 'claude',
 })

 events.push({
  time: t+200,
  type: 'task_update',
  agentId: characterId,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'キャラクター設定を生成中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: 'キャラクター設定を生成中' },
 })
 events.push({
  time: t+300,
  type: 'llm_call',
  agentId: characterId,
  aiService: 'openai',
 })

 events.push({
  time: t+400,
  type: 'task_update',
  agentId: designId,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'ゲームデザインを生成中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: 'ゲームデザインを生成中' },
 })
 events.push({
  time: t+500,
  type: 'llm_call',
  agentId: designId,
  aiService: 'gemini',
 })

 events.push({
  time: t+600,
  type: 'task_update',
  agentId: codeLeaderId,
  task: formatTask(2,5,ACTIONS.LLM_CALL,'コード構成を分析中'),
  metadata: { step: 2,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: 'コード構成を分析中' },
 })
 events.push({
  time: t+700,
  type: 'llm_call',
  agentId: codeLeaderId,
  aiService: 'claude',
 })

 events.push({
  time: t+800,
  type: 'task_update',
  agentId: assetLeaderId,
  task: formatTask(2,5,ACTIONS.LLM_CALL,'アセット一覧を生成中'),
  metadata: { step: 2,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: 'アセット一覧を生成中' },
 })
 events.push({
  time: t+900,
  type: 'llm_call',
  agentId: assetLeaderId,
  aiService: 'openai',
 })

 t+=2000

 const codeWorkers: string[]=[]
 for (let i=0;i<3;i++) {
  const workerId=genId(`code-worker-${i}`)
  codeWorkers.push(workerId)
  events.push({
   time: t+i*400,
   type: 'spawn',
   agentId: workerId,
   agentType: 'worker_code',
   parentId: codeLeaderId,
   status: 'running',
   task: formatTask(1,6,ACTIONS.INIT,`コードモジュール${i+1}を準備中`),
   sound: 'spawn',
   metadata: { step: 1,totalSteps: 6,action: ACTIONS.INIT,detail: `コードモジュール${i+1}を準備中` },
  })
 }

 events.push({
  time: t+200,
  type: 'task_update',
  agentId: codeLeaderId,
  task: formatTask(3,5,ACTIONS.WAIT,'WORKER完了を待機中'),
  metadata: { step: 3,totalSteps: 5,action: ACTIONS.WAIT,detail: 'WORKER完了を待機中' },
 })

 const assetWorkers: string[]=[]
 for (let i=0;i<2;i++) {
  const workerId=genId(`asset-worker-${i}`)
  assetWorkers.push(workerId)
  events.push({
   time: t+1200+i*400,
   type: 'spawn',
   agentId: workerId,
   agentType: 'worker_asset',
   parentId: assetLeaderId,
   status: 'running',
   task: formatTask(1,4,ACTIONS.INIT,`アセット${i+1}を準備中`),
   sound: 'spawn',
   metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: `アセット${i+1}を準備中` },
  })
 }

 events.push({
  time: t+1400,
  type: 'task_update',
  agentId: assetLeaderId,
  task: formatTask(3,5,ACTIONS.WAIT,'WORKER完了を待機中'),
  metadata: { step: 3,totalSteps: 5,action: ACTIONS.WAIT,detail: 'WORKER完了を待機中' },
 })

 t+=2500

 events.push({
  time: t,
  type: 'task_update',
  agentId: worldId,
  task: formatTask(3,4,ACTIONS.VALIDATE,'世界観設定を検証中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.VALIDATE,detail: '世界観設定を検証中' },
 })

 events.push({
  time: t+200,
  type: 'task_update',
  agentId: characterId,
  task: formatTask(3,4,ACTIONS.VALIDATE,'キャラクター設定を検証中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.VALIDATE,detail: 'キャラクター設定を検証中' },
 })

 events.push({
  time: t+400,
  type: 'task_update',
  agentId: designId,
  task: formatTask(3,4,ACTIONS.VALIDATE,'ゲームデザインを検証中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.VALIDATE,detail: 'ゲームデザインを検証中' },
 })

 t+=1000

 events.push({
  time: t,
  type: 'status_change',
  agentId: worldId,
  status: 'completed',
  task: formatTask(4,4,ACTIONS.COMPLETE,'世界観生成完了'),
  sound: 'complete',
 })

 events.push({
  time: t+300,
  type: 'status_change',
  agentId: characterId,
  status: 'completed',
  task: formatTask(4,4,ACTIONS.COMPLETE,'キャラクター設計完了'),
  sound: 'complete',
 })

 events.push({
  time: t+600,
  type: 'status_change',
  agentId: designId,
  status: 'completed',
  task: formatTask(4,4,ACTIONS.COMPLETE,'ゲームデザイン完了'),
  sound: 'complete',
 })

 t+=1000

 for (let i=0;i<codeWorkers.length;i++) {
  events.push({
   time: t+i*300,
   type: 'task_update',
   agentId: codeWorkers[i],
   task: formatTask(2,6,ACTIONS.LLM_CALL,`module${i+1}.ts を生成中`),
   metadata: { step: 2,totalSteps: 6,action: ACTIONS.LLM_CALL,detail: `module${i+1}.ts を生成中`,fileName: `module${i+1}.ts` },
  })
  events.push({
   time: t+i*300+100,
   type: 'llm_call',
   agentId: codeWorkers[i],
   aiService: i===0?'claude':(i===1?'openai':'gemini'),
  })
 }

 for (let i=0;i<assetWorkers.length;i++) {
  events.push({
   time: t+i*400,
   type: 'task_update',
   agentId: assetWorkers[i],
   task: formatTask(2,4,ACTIONS.LLM_CALL,`asset${i+1}.png を生成中`),
   metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: `asset${i+1}.png を生成中`,fileName: `asset${i+1}.png` },
  })
  events.push({
   time: t+i*400+100,
   type: 'llm_call',
   agentId: assetWorkers[i],
   aiService: 'openai',
  })
 }

 t+=3000

 for (let i=0;i<codeWorkers.length;i++) {
  events.push({
   time: t+i*400,
   type: 'status_change',
   agentId: codeWorkers[i],
   status: 'completed',
   task: formatTask(6,6,ACTIONS.COMPLETE,`コードモジュール${i+1}完了`),
   sound: 'complete',
  })
 }

 for (let i=0;i<assetWorkers.length;i++) {
  events.push({
   time: t+i*300,
   type: 'status_change',
   agentId: assetWorkers[i],
   status: 'completed',
   task: formatTask(4,4,ACTIONS.COMPLETE,`アセット${i+1}完了`),
   sound: 'complete',
  })
 }

 t+=1500

 events.push({
  time: t,
  type: 'task_update',
  agentId: codeLeaderId,
  task: formatTask(4,5,ACTIONS.LLM_CALL,'コードを統合中'),
  metadata: { step: 4,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: 'コードを統合中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: codeLeaderId,
  aiService: 'claude',
 })

 events.push({
  time: t+200,
  type: 'task_update',
  agentId: assetLeaderId,
  task: formatTask(4,5,ACTIONS.LLM_CALL,'アセットを統合中'),
  metadata: { step: 4,totalSteps: 5,action: ACTIONS.LLM_CALL,detail: 'アセットを統合中' },
 })
 events.push({
  time: t+300,
  type: 'llm_call',
  agentId: assetLeaderId,
  aiService: 'openai',
 })

 t+=1500

 events.push({
  time: t,
  type: 'task_update',
  agentId: codeLeaderId,
  task: formatTask(5,5,'Human承認','コード実装承認を提出中'),
  metadata: { step: 5,totalSteps: 5,action: 'Human承認',detail: 'コード実装承認を提出中' },
 })
 events.push({
  time: t+200,
  type: 'status_change',
  agentId: codeLeaderId,
  status: 'waiting_approval',
  task: 'コード実装承認待ち',
  sound: 'approval',
 })

 events.push({
  time: t+400,
  type: 'task_update',
  agentId: assetLeaderId,
  task: formatTask(5,5,'Human承認','アセット制作承認を提出中'),
  metadata: { step: 5,totalSteps: 5,action: 'Human承認',detail: 'アセット制作承認を提出中' },
 })
 events.push({
  time: t+600,
  type: 'status_change',
  agentId: assetLeaderId,
  status: 'waiting_approval',
  task: 'アセット制作承認待ち',
  sound: 'approval',
 })

 t+=3000

 events.push({
  time: t,
  type: 'approval_granted',
  agentId: codeLeaderId,
  sound: 'complete',
 })
 events.push({
  time: t,
  type: 'status_change',
  agentId: codeLeaderId,
  status: 'completed',
  task: 'コード実装承認済み',
 })

 events.push({
  time: t+500,
  type: 'approval_granted',
  agentId: assetLeaderId,
  sound: 'complete',
 })
 events.push({
  time: t+500,
  type: 'status_change',
  agentId: assetLeaderId,
  status: 'completed',
  task: 'アセット制作承認済み',
 })

 t+=1000

 events.push({
  time: t,
  type: 'task_update',
  agentId: dir2Id,
  task: formatTask(4,4,ACTIONS.COMPLETE,'Phase2完了'),
  metadata: { step: 4,totalSteps: 4,action: ACTIONS.COMPLETE,detail: 'Phase2完了' },
 })
 events.push({
  time: t+200,
  type: 'status_change',
  agentId: dir2Id,
  status: 'completed',
  task: 'Phase2完了',
  sound: 'complete',
 })

 t+=1000
 events.push({
  time: t,
  type: 'status_change',
  agentId: orchId,
  status: 'running',
  task: formatTask(1,2,ACTIONS.INIT,'Phase3準備中'),
  metadata: { step: 1,totalSteps: 2,action: ACTIONS.INIT,detail: 'Phase3準備中' },
 })

 t+=500
 events.push({
  time: t,
  type: 'phase_change',
  agentId: orchId,
  phase: 3,
  sound: 'phase',
 })

 const dir3Id=genId('dir3')
 events.push({
  time: t,
  type: 'spawn',
  agentId: dir3Id,
  agentType: 'director_phase3',
  parentId: orchId,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'Phase3開始: 品質フェーズ'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: 'Phase3開始: 品質フェーズ' },
 })

 events.push({
  time: t+200,
  type: 'status_change',
  agentId: orchId,
  status: 'pending',
  task: 'DIRECTORに委譲',
 })

 t+=1000

 const integratorId=genId('integrator')
 events.push({
  time: t,
  type: 'spawn',
  agentId: integratorId,
  agentType: 'integrator',
  parentId: dir3Id,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'成果物を収集中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: '成果物を収集中' },
 })

 events.push({
  time: t+200,
  type: 'task_update',
  agentId: dir3Id,
  task: formatTask(2,4,ACTIONS.WAIT,'統合処理を監視中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.WAIT,detail: '統合処理を監視中' },
 })

 t+=800
 events.push({
  time: t,
  type: 'task_update',
  agentId: integratorId,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'統合処理を実行中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: '統合処理を実行中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: integratorId,
  aiService: 'claude',
 })

 t+=2000
 events.push({
  time: t,
  type: 'task_update',
  agentId: integratorId,
  task: formatTask(3,4,ACTIONS.VALIDATE,'統合結果をチェック中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.VALIDATE,detail: '統合結果をチェック中' },
 })

 t+=800
 events.push({
  time: t,
  type: 'status_change',
  agentId: integratorId,
  status: 'completed',
  task: formatTask(4,4,ACTIONS.COMPLETE,'統合完了'),
  sound: 'complete',
 })

 t+=500

 const testerId=genId('tester')
 events.push({
  time: t,
  type: 'spawn',
  agentId: testerId,
  agentType: 'unit_test',
  parentId: dir3Id,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'テスト環境を準備中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: 'テスト環境を準備中' },
 })

 t+=800
 events.push({
  time: t,
  type: 'task_update',
  agentId: testerId,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'テストを実行中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: 'テストを実行中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: testerId,
  aiService: 'claude',
 })

 t+=2000
 events.push({
  time: t,
  type: 'task_update',
  agentId: testerId,
  task: formatTask(3,4,ACTIONS.VALIDATE,'テスト結果を検証中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.VALIDATE,detail: 'テスト結果を検証中' },
 })

 t+=800
 events.push({
  time: t,
  type: 'status_change',
  agentId: testerId,
  status: 'completed',
  task: formatTask(4,4,ACTIONS.COMPLETE,'テスト完了'),
  sound: 'complete',
 })

 t+=500

 const reviewerId=genId('reviewer')
 events.push({
  time: t,
  type: 'spawn',
  agentId: reviewerId,
  agentType: 'reviewer',
  parentId: dir3Id,
  status: 'running',
  task: formatTask(1,4,ACTIONS.INIT,'レビュー対象を収集中'),
  sound: 'spawn',
  metadata: { step: 1,totalSteps: 4,action: ACTIONS.INIT,detail: 'レビュー対象を収集中' },
 })

 t+=800
 events.push({
  time: t,
  type: 'task_update',
  agentId: reviewerId,
  task: formatTask(2,4,ACTIONS.LLM_CALL,'コードレビューを実行中'),
  metadata: { step: 2,totalSteps: 4,action: ACTIONS.LLM_CALL,detail: 'コードレビューを実行中' },
 })
 events.push({
  time: t+100,
  type: 'llm_call',
  agentId: reviewerId,
  aiService: 'claude',
 })

 t+=2000
 events.push({
  time: t,
  type: 'task_update',
  agentId: reviewerId,
  task: formatTask(3,4,ACTIONS.FILE_SAVE,'review_report.md を保存中'),
  metadata: { step: 3,totalSteps: 4,action: ACTIONS.FILE_SAVE,detail: 'review_report.md を保存中',fileName: 'review_report.md' },
 })

 t+=500
 events.push({
  time: t,
  type: 'status_change',
  agentId: reviewerId,
  status: 'completed',
  task: formatTask(4,4,ACTIONS.COMPLETE,'レビュー完了'),
  sound: 'complete',
 })

 t+=1000
 events.push({
  time: t,
  type: 'task_update',
  agentId: dir3Id,
  task: formatTask(4,4,ACTIONS.COMPLETE,'Phase3完了'),
  metadata: { step: 4,totalSteps: 4,action: ACTIONS.COMPLETE,detail: 'Phase3完了' },
 })
 events.push({
  time: t+200,
  type: 'status_change',
  agentId: dir3Id,
  status: 'completed',
  task: 'Phase3完了',
  sound: 'complete',
 })

 t+=1000
 events.push({
  time: t,
  type: 'status_change',
  agentId: orchId,
  status: 'running',
  task: formatTask(2,2,ACTIONS.COMPLETE,'プロジェクト完了処理中'),
  metadata: { step: 2,totalSteps: 2,action: ACTIONS.COMPLETE,detail: 'プロジェクト完了処理中' },
 })

 t+=1000
 events.push({
  time: t,
  type: 'status_change',
  agentId: orchId,
  status: 'completed',
  task: 'プロジェクト完了',
  sound: 'complete',
 })

 return {
  name: 'フルプロジェクトデモ',
  description: 'Phase0〜3の全ワークフロー: ORCHESTRATOR → DIRECTOR → LEADER → WORKER',
  events: events.sort((a,b)=>a.time-b.time),
  totalDuration: t+3000,
 }
}

export function createPhase1Scenario(): DemoScenario {
 return createFullDemoScenario()
}

export class DemoRunner {
 private scenario: DemoScenario
 private startTime: number=0
 private eventIndex: number=0
 private isRunning: boolean=false
 private onEvent: (event: DemoEvent)=>void
 private onComplete: ()=>void
 private rafId: number|null=null

 constructor(
  scenario: DemoScenario,
  onEvent: (event: DemoEvent)=>void,
  onComplete: ()=>void
 ) {
  this.scenario=scenario
  this.onEvent=onEvent
  this.onComplete=onComplete
 }

 start(): void {
  this.startTime=performance.now()
  this.eventIndex=0
  this.isRunning=true
  this.tick()
 }

 stop(): void {
  this.isRunning=false
  if (this.rafId!==null) {
   cancelAnimationFrame(this.rafId)
   this.rafId=null
  }
 }

 reset(): void {
  this.stop()
  this.eventIndex=0
 }

 private tick=(): void=>{
  if (!this.isRunning) return

  const elapsed=performance.now()-this.startTime

  while (
   this.eventIndex<this.scenario.events.length&&
   this.scenario.events[this.eventIndex].time<=elapsed
) {
   this.onEvent(this.scenario.events[this.eventIndex])
   this.eventIndex++
  }

  if (this.eventIndex>=this.scenario.events.length) {
   this.isRunning=false
   this.onComplete()
   return
  }

  this.rafId=requestAnimationFrame(this.tick)
 }

 getProgress(): number {
  if (!this.isRunning) return 0
  const elapsed=performance.now()-this.startTime
  return Math.min(1,elapsed/this.scenario.totalDuration)
 }
}
