import{useState,useEffect,useMemo,useCallback}from'react'
import{Card,CardContent}from'@/components/ui/Card'
import{useProjectStore}from'@/stores/projectStore'
import{AIField2D}from'@/components/ai-game'
import type{CharacterState,AIServiceType,AIRequest,CharacterEmotion}from'@/components/ai-game/types'
import{SERVICE_CONFIG}from'@/components/ai-game/types'
import{FolderOpen,Pause}from'lucide-react'
import{Button}from'@/components/ui/Button'
import type{AgentType}from'@/types/agent'

const AGENT_SERVICE_MAP:Record<AgentType,AIServiceType>={
 concept:'llm',
 task_split_1:'llm',
 concept_detail:'llm',
 scenario:'llm',
 world:'llm',
 game_design:'llm',
 tech_spec:'llm',
 task_split_2:'llm',
 task_split_3:'llm',
 task_split_4:'llm',
 code:'llm',
 event:'llm',
 ui_integration:'llm',
 asset_integration:'llm',
 unit_test:'llm',
 integration_test:'llm',
 asset_character:'image',
 asset_background:'image',
 asset_ui:'image',
 asset_effect:'image',
 asset_bgm:'music',
 asset_voice:'audio',
 asset_sfx:'audio'
}

const SERVICE_DURATION:Record<AIServiceType,{min:number;max:number}>={
 llm:{min:3000,max:8000},
 image:{min:10000,max:20000},
 music:{min:30000,max:60000},
 audio:{min:5000,max:15000}
}

const AGENT_TASKS:Record<AgentType,string[]>={
 concept:[
  'ゲームの基本コンセプトを策定',
  'ターゲットユーザー分析を実施',
  'コアゲームループの定義'
],
 task_split_1:['Phase1タスクの分割と依存関係整理'],
 concept_detail:['コンセプトドキュメントの詳細化'],
 scenario:[
  'メインストーリーの執筆',
  'ステージ1〜5のシナリオ作成',
  'キャラクター会話スクリプト作成'
],
 world:[
  '世界観設定ドキュメント作成',
  '地域・マップ構成の設計'
],
 game_design:[
  'ゲームメカニクスの詳細設計',
  'バランス調整パラメータ定義',
  'レベルデザインガイドライン作成'
],
 tech_spec:[
  '技術仕様書の作成',
  'システムアーキテクチャ設計'
],
 task_split_2:['Phase2タスクの分割'],
 task_split_3:['Phase3タスクの分割'],
 task_split_4:['Phase4タスクの分割'],
 asset_character:[
  'プレイヤーキャラクターのデザイン',
  'NPC立ち絵の生成',
  '敵キャラクターのコンセプトアート'
],
 asset_background:[
  '草原ステージの背景画像生成',
  'ダンジョン背景の作成',
  'タイトル画面背景のデザイン'
],
 asset_ui:[
  'ボタンUIのデザイン',
  'ステータスバーの作成',
  'メニュー画面UIの生成'
],
 asset_effect:[
  '攻撃エフェクトの作成',
  'パーティクル素材の生成'
],
 asset_bgm:[
  '草原ステージBGMの作曲',
  'ボス戦BGMの生成',
  'タイトル画面BGMの作成'
],
 asset_voice:[
  'ナレーション音声の生成',
  'キャラクターボイスの合成'
],
 asset_sfx:[
  '攻撃効果音の生成',
  'UI操作音の作成',
  '環境音の合成'
],
 code:[
  'プレイヤー移動処理の実装',
  '当たり判定システムの実装',
  'セーブ・ロード機能の実装'
],
 event:[
  'イベントトリガーシステムの実装',
  'カットシーン制御の実装'
],
 ui_integration:[
  'UIコンポーネントの統合',
  'メニュー画面の実装'
],
 asset_integration:[
  'アセットのインポートと配置',
  'アニメーション設定'
],
 unit_test:[
  'プレイヤークラスの単体テスト',
  'アイテムシステムのテスト'
],
 integration_test:[
  'ステージ1の統合テスト',
  'セーブ・ロードの結合テスト'
]
}

const mockRequests:AIRequest[]=[
 {
  id:'ai-001',
  serviceType:'llm',
  serviceName:'Claude 3.5 Sonnet',
  agentId:'agent-concept',
  agentType:'concept',
  input:'ゲームの基本コンセプトを策定',
  output:'# ゲームコンセプト\n\n## 概要\nボールを操作してゴールを目指すパズルゲーム',
  status:'completed',
  tokensUsed:1250,
  cost:0.015,
  duration:5200,
  createdAt:new Date(Date.now()-300000).toISOString(),
  completedAt:new Date(Date.now()-294800).toISOString()
 },
 {
  id:'ai-002',
  serviceType:'llm',
  serviceName:'Claude 3.5 Sonnet',
  agentId:'agent-scenario',
  agentType:'scenario',
  input:'ステージ1〜5のシナリオ作成',
  output:'# ステージシナリオ\n\n## ステージ1: はじまりの草原',
  status:'completed',
  tokensUsed:2100,
  cost:0.025,
  duration:6500,
  createdAt:new Date(Date.now()-250000).toISOString(),
  completedAt:new Date(Date.now()-243500).toISOString()
 },
 {
  id:'ai-003',
  serviceType:'llm',
  serviceName:'Claude 3.5 Sonnet',
  agentId:'agent-game_design',
  agentType:'game_design',
  input:'ゲームメカニクスの詳細設計',
  output:'# ゲームメカニクス設計書',
  status:'completed',
  tokensUsed:1800,
  cost:0.022,
  duration:7200,
  createdAt:new Date(Date.now()-200000).toISOString(),
  completedAt:new Date(Date.now()-192800).toISOString()
 },
 {
  id:'ai-010',
  serviceType:'image',
  serviceName:'DALL-E 3',
  agentId:'agent-asset_character',
  agentType:'asset_character',
  input:'プレイヤーキャラクターのデザイン',
  output:'/assets/character_player_001.png',
  status:'completed',
  cost:0.04,
  duration:15000,
  createdAt:new Date(Date.now()-180000).toISOString(),
  completedAt:new Date(Date.now()-165000).toISOString()
 },
 {
  id:'ai-011',
  serviceType:'image',
  serviceName:'DALL-E 3',
  agentId:'agent-asset_background',
  agentType:'asset_background',
  input:'草原ステージの背景画像生成',
  output:'/assets/bg_grassland_001.png',
  status:'completed',
  cost:0.04,
  duration:18000,
  createdAt:new Date(Date.now()-160000).toISOString(),
  completedAt:new Date(Date.now()-142000).toISOString()
 },
 {
  id:'ai-020',
  serviceType:'music',
  serviceName:'Suno AI',
  agentId:'agent-asset_bgm',
  agentType:'asset_bgm',
  input:'草原ステージBGMの作曲',
  output:'/assets/bgm_grassland.mp3',
  status:'completed',
  cost:0.10,
  duration:45000,
  createdAt:new Date(Date.now()-400000).toISOString(),
  completedAt:new Date(Date.now()-355000).toISOString()
 },
 {
  id:'ai-030',
  serviceType:'audio',
  serviceName:'ElevenLabs',
  agentId:'agent-asset_voice',
  agentType:'asset_voice',
  input:'ナレーション音声の生成',
  output:'/assets/audio/narration_001.mp3',
  status:'completed',
  cost:0.02,
  duration:8000,
  createdAt:new Date(Date.now()-150000).toISOString(),
  completedAt:new Date(Date.now()-142000).toISOString()
 }
]

export default function AIView():JSX.Element{
 const{currentProject}=useProjectStore()
 const[requests,setRequests]=useState<AIRequest[]>([])
 const[activeAgents,setActiveAgents]=useState<Set<AgentType>>(new Set())
 const[selectedCharacter,setSelectedCharacter]=useState<CharacterState|null>(null)

 useEffect(()=>{
  if(!currentProject){
   setRequests([])
   setActiveAgents(new Set())
   return
  }
  setRequests(mockRequests)

  const initialAgents=new Set<AgentType>([
   'concept',
   'scenario',
   'game_design',
   'asset_character',
   'asset_background',
   'asset_bgm',
   'asset_voice'
])
  setActiveAgents(initialAgents)
 },[currentProject?.id])

 useEffect(()=>{
  if(!currentProject)return

  const simulateActivity=()=>{
   setActiveAgents((currentActiveAgents)=>{
    const activeAgentList=Array.from(currentActiveAgents)
    if(activeAgentList.length===0)return currentActiveAgents

    const randomAgent=activeAgentList[Math.floor(Math.random()*activeAgentList.length)]

    setRequests((prevRequests)=>{
     const isAlreadyProcessing=prevRequests.some(
      (r)=>r.agentType===randomAgent&&r.status==='processing'
)

     if(isAlreadyProcessing){
      return prevRequests
     }

     const serviceType=AGENT_SERVICE_MAP[randomAgent]
     const serviceConfig=SERVICE_CONFIG[serviceType]

     const tasks=AGENT_TASKS[randomAgent]||[`${randomAgent}のタスク実行`]
     const taskInput=tasks[Math.floor(Math.random()*tasks.length)]

     const newRequest:AIRequest={
      id:`ai-auto-${Date.now()}-${Math.random().toString(36).substr(2,9)}`,
      serviceType,
      serviceName:serviceConfig.description,
      agentId:`agent-${randomAgent}`,
      agentType:randomAgent,
      input:taskInput,
      status:'processing',
      createdAt:new Date().toISOString()
     }

     const duration=SERVICE_DURATION[serviceType]
     const completionTime=duration.min+Math.random()*(duration.max-duration.min)

     setTimeout(()=>{
      setRequests((prev)=>
       prev.map((r)=>
        r.id===newRequest.id
         ?{
          ...r,
          status:'completed',
          completedAt:new Date().toISOString(),
          output:`${taskInput}-完了`,
          tokensUsed:serviceType==='llm'?Math.floor(500+Math.random()*2000) : undefined,
          cost:serviceType==='llm'?Math.random()*0.05 :
           serviceType==='image'?0.02+Math.random()*0.02 :
            serviceType==='music'?0.05+Math.random()*0.10 :
             0.01+Math.random()*0.02,
          duration:completionTime
         }
         : r
)
)
     },completionTime)

     return[...prevRequests,newRequest]
    })

    return currentActiveAgents
   })
  }

  const intervalId=setInterval(simulateActivity,3000+Math.random()*3000)

  const initialTimeoutId=setTimeout(simulateActivity,1000)

  return()=>{
   clearInterval(intervalId)
   clearTimeout(initialTimeoutId)
  }
 },[currentProject?.id])

 const characters=useMemo(():CharacterState[]=>{
  const characterMap=new Map<string,CharacterState>()

  activeAgents.forEach((agentType)=>{
   const agentId=`agent-${agentType}`

   const processingRequest=requests.find(
    (r)=>r.agentType===agentType&&r.status==='processing'
)

   let status:CharacterState['status']='idle'
   let emotion:CharacterEmotion='idle'
   let targetService:AIServiceType|undefined=undefined

   if(processingRequest){
    status='working'
    emotion='working'
    targetService=processingRequest.serviceType
   }

   characterMap.set(agentId,{
    agentId,
    agentType,
    status,
    emotion,
    targetService,
    request:processingRequest,
    position:{x:0,y:0}
   })
  })

  return Array.from(characterMap.values())
 },[activeAgents,requests])

 const removeAgent=useCallback((agentType:AgentType)=>{
  setActiveAgents((prev)=>{
   const next=new Set(prev)
   next.delete(agentType)
   return next
  })
 },[])

 const handleCharacterClick=useCallback((character:CharacterState)=>{
  setSelectedCharacter(character)
 },[])

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <div className="nier-page-header-row">
     <div className="nier-page-header-left">
      <h1 className="nier-page-title">AI</h1>
      <span className="nier-page-subtitle">-外部AI連携</span>
     </div>
     <div className="nier-page-header-right"/>
    </div>
    <Card>
     <CardContent>
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
       <p className="text-nier-body">プロジェクトを選択してください</p>
      </div>
     </CardContent>
    </Card>
   </div>
)
 }

 return(
  <div className="p-4 animate-nier-fade-in">
   {/*Header*/}
   <div className="nier-page-header-row">
    <div className="nier-page-header-left">
     <h1 className="nier-page-title">AI</h1>
     <span className="nier-page-subtitle">-外部AI連携</span>
    </div>
    <div className="nier-page-header-right"/>
   </div>

   {/*2D AIフィールド*/}
   <Card className="mb-4">
    <CardContent className="p-0">
     <div className="h-[500px] rounded-lg overflow-hidden">
      <AIField2D
       characters={characters}
       onCharacterClick={handleCharacterClick}
      />
     </div>
    </CardContent>
   </Card>

   {/*選択されたキャラクターの詳細パネル*/}
   {selectedCharacter&&(
    <Card className="mt-4">
     <CardContent>
      <div className="flex items-start justify-between">
       <div>
        <h3 className="text-nier-body font-medium text-nier-text-main">
         {selectedCharacter.agentType.toUpperCase().replace(/_/g,' ')}
        </h3>
        <p className="text-nier-small text-nier-text-light mt-1">
         ステータス: {selectedCharacter.status==='idle'?'待機中' :
          selectedCharacter.status==='working'?'作業中' :
           selectedCharacter.status==='departing'?'移動中' : '帰還中'}
        </p>
        {selectedCharacter.targetService&&(
         <p className="text-nier-small text-nier-text-light">
          サービス: {selectedCharacter.targetService.toUpperCase()}
         </p>
)}
        {selectedCharacter.request&&(
         <p className="text-nier-small text-nier-text-light mt-1 truncate max-w-md">
          タスク: {selectedCharacter.request.input}
         </p>
)}
       </div>
       <div className="flex gap-2 items-center">
        {selectedCharacter.status==='working'&&(
         <span className="text-nier-small text-nier-accent-orange flex items-center">
          <Pause size={14} className="mr-1 animate-pulse"/>
          処理中...
         </span>
)}
        {selectedCharacter.status==='idle'&&(
         <span className="text-nier-small text-nier-text-light">
          自動タスク割り当て待ち
         </span>
)}
        <Button
         size="sm"
         variant="danger"
         onClick={()=>{
          removeAgent(selectedCharacter.agentType)
          setSelectedCharacter(null)
         }}
        >
         削除
        </Button>
       </div>
      </div>
     </CardContent>
    </Card>
)}
  </div>
)
}
