import{useState,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Save,Eye,EyeOff,FolderOpen,RefreshCw}from'lucide-react'
import{QualityCheckSettingsPanel}from'@/components/settings/QualityCheckSettingsPanel'
import{AutoApprovalSettings}from'@/components/settings/AutoApprovalSettings'
import{AIProviderSettings}from'@/components/settings/AIProviderSettings'

interface ConfigSection{
 id:string
 label:string
}

const configSections:ConfigSection[]=[
 {id:'ai-providers',label:'AI Provider設定'},
 {id:'auto-approval',label:'自動承認設定'},
 {id:'api',label:'API設定'},
 {id:'model',label:'モデル設定'},
 {id:'cost',label:'コスト設定'},
 {id:'output',label:'出力設定'},
 {id:'project',label:'プロジェクト設定'},
 {id:'agent-quality',label:'エージェント品質設定'},
 {id:'display',label:'表示設定'}
]

export default function ConfigView():JSX.Element{
 const[activeSection,setActiveSection]=useState('ai-providers')
 const[showApiKey,setShowApiKey]=useState(false)

 const[config,setConfig]=useState({
  apiProvider:'anthropic',
  apiKey:'',
  modelId:'claude-3-opus-20240229',
  temperature:0.7,
  maxTokens:4096,
  outputDir:'./output',
  autoSave:true,
  projectTemplate:'rpg',
  language:'ja',
  budgetLimit:10.0,
  alertThreshold:80,
  stopOnBudgetExceeded:true,
  inputTokenPrice:0.003,
  outputTokenPrice:0.015,
  letterSpacing:'normal'as'tight'|'normal'|'wide',
  lineHeight:1.0,
  padding:4
 })

 const handleLetterSpacingChange=(value:'tight'|'normal'|'wide')=>{
  setConfig({...config,letterSpacing:value})
  document.documentElement.setAttribute('data-tracking',value)
 }

 const handleLineHeightChange=(value:number)=>{
  setConfig({...config,lineHeight:value})
  document.documentElement.style.setProperty('--leading-base',String(value))
 }

 const handlePaddingChange=(value:number)=>{
  setConfig({...config,padding:value})
  document.documentElement.style.setProperty('--padding-card',`${value}px`)
  document.documentElement.style.setProperty('--padding-section',`${value+8}px`)
  document.documentElement.style.setProperty('--gap-base',`${value}px`)
 }

 useEffect(()=>{
  document.documentElement.setAttribute('data-tracking',config.letterSpacing)
  document.documentElement.style.setProperty('--leading-base',String(config.lineHeight))
  document.documentElement.style.setProperty('--padding-card',`${config.padding}px`)
  document.documentElement.style.setProperty('--padding-section',`${config.padding+8}px`)
  document.documentElement.style.setProperty('--gap-base',`${config.padding}px`)
 },[])

 const handleSave=()=>{
  console.log('Config saved:',config)
  //TODO: Implement actual save
 }

 return(
  <div className="p-4 animate-nier-fade-in">
   {/*Header*/}
   <div className="nier-page-header-row">
    <div className="nier-page-header-left">
     <h1 className="nier-page-title">CONFIG</h1>
     <span className="nier-page-subtitle">-システム設定</span>
    </div>
    <div className="nier-page-header-right">
     <Button variant="primary" size="sm" onClick={handleSave}>
      <Save size={14}/>
      <span className="ml-1.5">保存</span>
     </Button>
    </div>
   </div>

   <div className="grid grid-cols-4 gap-3">
    {/*Section Navigation*/}
    <Card>
     <CardHeader>
      <DiamondMarker>設定カテゴリ</DiamondMarker>
     </CardHeader>
     <CardContent className="p-0">
      <div className="divide-y divide-nier-border-light">
       {configSections.map(section=>(
        <button
         key={section.id}
         className={cn(
          'w-full px-4 py-3 text-left text-nier-small tracking-nier transition-colors',
          activeSection===section.id
           ?'bg-nier-bg-selected text-nier-text-main'
           : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
         onClick={()=>setActiveSection(section.id)}
        >
         {section.label}
        </button>
))}
      </div>
     </CardContent>
    </Card>

    {/*Config Content*/}
    <div className="col-span-3 space-y-4">
     {/*AI Provider Settings*/}
     {activeSection==='ai-providers'&&<AIProviderSettings/>}

     {/*Auto Approval Settings*/}
     {activeSection==='auto-approval'&&<AutoApprovalSettings/>}

     {/*API Settings*/}
     {activeSection==='api'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>API設定</DiamondMarker>
       </CardHeader>
       <CardContent className="space-y-4">
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          APIプロバイダー
         </label>
         <select
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={config.apiProvider}
          onChange={(e)=>setConfig({...config,apiProvider:e.target.value})}
         >
          <option value="anthropic">Anthropic (Claude)</option>
          <option value="openai">OpenAI (GPT)</option>
          <option value="google">Google (Gemini)</option>
         </select>
        </div>

        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          APIキー
         </label>
         <div className="flex gap-2">
          <input
           type={showApiKey?'text' : 'password'}
           className="flex-1 bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
           placeholder="sk-..."
           value={config.apiKey}
           onChange={(e)=>setConfig({...config,apiKey:e.target.value})}
          />
          <button
           className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors"
           onClick={()=>setShowApiKey(!showApiKey)}
          >
           {showApiKey?<EyeOff size={16}/>:<Eye size={16}/>}
          </button>
         </div>
         <p className="mt-1 text-nier-caption text-nier-text-light">
          APIキーは暗号化されてローカルに保存されます
         </p>
        </div>

        <div>
         <Button variant="ghost" size="sm">
          <RefreshCw size={14}/>
          <span className="ml-1.5">接続テスト</span>
         </Button>
        </div>
       </CardContent>
      </Card>
)}

     {/*Model Settings*/}
     {activeSection==='model'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>モデル設定</DiamondMarker>
       </CardHeader>
       <CardContent className="space-y-4">
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          使用モデル
         </label>
         <select
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={config.modelId}
          onChange={(e)=>setConfig({...config,modelId:e.target.value})}
         >
          <optgroup label="Anthropic">
           <option value="claude-3-opus-20240229">Claude 3 Opus (最高品質)</option>
           <option value="claude-3-sonnet-20240229">Claude 3 Sonnet (バランス)</option>
           <option value="claude-3-haiku-20240307">Claude 3 Haiku (高速)</option>
          </optgroup>
          <optgroup label="OpenAI">
           <option value="gpt-4-turbo">GPT-4 Turbo</option>
           <option value="gpt-4">GPT-4</option>
           <option value="gpt-3.5-turbo">GPT-3.5 Turbo</option>
          </optgroup>
         </select>
        </div>

        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          Temperature: {config.temperature}
         </label>
         <input
          type="range"
          min="0"
          max="1"
          step="0.1"
          className="w-full"
          value={config.temperature}
          onChange={(e)=>setConfig({...config,temperature:parseFloat(e.target.value)})}
         />
         <div className="flex justify-between text-nier-caption text-nier-text-light">
          <span>0 (確定的)</span>
          <span>1 (創造的)</span>
         </div>
        </div>

        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          最大トークン数
         </label>
         <input
          type="number"
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={config.maxTokens}
          onChange={(e)=>setConfig({...config,maxTokens:parseInt(e.target.value)})}
         />
        </div>
       </CardContent>
      </Card>
)}

     {/*Cost Settings*/}
     {activeSection==='cost'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>コスト設定</DiamondMarker>
       </CardHeader>
       <CardContent className="space-y-4">
        <div className="p-3 bg-nier-bg-panel border border-nier-border-light text-nier-caption text-nier-text-light">
         <p>APIの使用上限はAPIダッシュボードで設定してください。ここでの設定はアプリ内での警告・停止用です。</p>
        </div>

        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          予算上限 (USD)
         </label>
         <input
          type="number"
          step="0.01"
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={config.budgetLimit}
          onChange={(e)=>setConfig({...config,budgetLimit:parseFloat(e.target.value)})}
         />
         <p className="mt-1 text-nier-caption text-nier-text-light">
          プロジェクトあたりの予算上限
         </p>
        </div>

        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          警告閾値: {config.alertThreshold}%
         </label>
         <input
          type="range"
          min="50"
          max="100"
          step="5"
          className="w-full"
          value={config.alertThreshold}
          onChange={(e)=>setConfig({...config,alertThreshold:parseInt(e.target.value)})}
         />
         <div className="flex justify-between text-nier-caption text-nier-text-light">
          <span>50%</span>
          <span>100%</span>
         </div>
         <p className="mt-1 text-nier-caption text-nier-text-light">
          この割合に達したら警告を表示
         </p>
        </div>

        <div className="flex items-center gap-2">
         <input
          type="checkbox"
          id="stopOnBudget"
          checked={config.stopOnBudgetExceeded}
          onChange={(e)=>setConfig({...config,stopOnBudgetExceeded:e.target.checked})}
          className="w-4 h-4"
         />
         <label htmlFor="stopOnBudget" className="text-nier-small">
          予算超過時に自動停止
         </label>
        </div>

        <div className="border-t border-nier-border-light pt-4 mt-4">
         <h4 className="text-nier-small font-medium mb-3">トークン単価設定 (1Kトークンあたり)</h4>
         <div className="grid grid-cols-2 gap-4">
          <div>
           <label className="block text-nier-caption text-nier-text-light mb-1">
            入力トークン単価 (USD)
           </label>
           <input
            type="number"
            step="0.001"
            className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
            value={config.inputTokenPrice}
            onChange={(e)=>setConfig({...config,inputTokenPrice:parseFloat(e.target.value)})}
           />
          </div>
          <div>
           <label className="block text-nier-caption text-nier-text-light mb-1">
            出力トークン単価 (USD)
           </label>
           <input
            type="number"
            step="0.001"
            className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
            value={config.outputTokenPrice}
            onChange={(e)=>setConfig({...config,outputTokenPrice:parseFloat(e.target.value)})}
           />
          </div>
         </div>
         <p className="mt-2 text-nier-caption text-nier-text-light">
          Claude 3.5 Sonnet: 入力 $0.003/1K,出力 $0.015/1K
         </p>
        </div>
       </CardContent>
      </Card>
)}

     {/*Output Settings*/}
     {activeSection==='output'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>出力設定</DiamondMarker>
       </CardHeader>
       <CardContent className="space-y-4">
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          出力ディレクトリ
         </label>
         <div className="flex gap-2">
          <input
           type="text"
           className="flex-1 bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
           value={config.outputDir}
           onChange={(e)=>setConfig({...config,outputDir:e.target.value})}
          />
          <button className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors">
           <FolderOpen size={16}/>
          </button>
         </div>
        </div>

        <div className="flex items-center gap-2">
         <input
          type="checkbox"
          id="autoSave"
          checked={config.autoSave}
          onChange={(e)=>setConfig({...config,autoSave:e.target.checked})}
          className="w-4 h-4"
         />
         <label htmlFor="autoSave" className="text-nier-small">
          自動保存を有効にする
         </label>
        </div>

        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          出力言語
         </label>
         <select
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={config.language}
          onChange={(e)=>setConfig({...config,language:e.target.value})}
         >
          <option value="ja">日本語</option>
          <option value="en">English</option>
          <option value="zh">中文</option>
          <option value="ko">한국어</option>
         </select>
        </div>
       </CardContent>
      </Card>
)}

     {/*Project Settings*/}
     {activeSection==='project'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>プロジェクト設定</DiamondMarker>
       </CardHeader>
       <CardContent className="space-y-4">
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          プロジェクトテンプレート
         </label>
         <select
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={config.projectTemplate}
          onChange={(e)=>setConfig({...config,projectTemplate:e.target.value})}
         >
          <option value="rpg">RPG (ロールプレイングゲーム)</option>
          <option value="action">アクションゲーム</option>
          <option value="adventure">アドベンチャーゲーム</option>
          <option value="puzzle">パズルゲーム</option>
          <option value="simulation">シミュレーションゲーム</option>
          <option value="custom">カスタム</option>
         </select>
        </div>

        <div className="p-3 bg-nier-bg-panel border border-nier-border-light">
         <h4 className="text-nier-small font-medium mb-2">RPGテンプレート概要</h4>
         <ul className="text-nier-caption text-nier-text-light space-y-1">
          <li>• Phase 1: コンセプト → デザイン → シナリオ → キャラクター → ワールド → タスク分割</li>
          <li>• Phase 2: アセット生成 (画像、音楽、効果音)</li>
          <li>• Phase 3: コード生成 (ゲームロジック、UI、データ)</li>
          <li>• Phase 4: 統合&テスト</li>
         </ul>
        </div>
       </CardContent>
      </Card>
)}

     {/*Agent Quality Settings*/}
     {activeSection==='agent-quality'&&(
      <QualityCheckSettingsPanel projectId="proj-001"/>
)}

     {/*Display Settings*/}
     {activeSection==='display'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>表示設定</DiamondMarker>
       </CardHeader>
       <CardContent className="space-y-6">
        {/*Letter Spacing*/}
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-2">
          文字間隔
         </label>
         <div className="flex gap-2">
          {(['tight','normal','wide']as const).map((spacing)=>(
           <button
            key={spacing}
            className={cn(
             'px-4 py-2 border text-nier-small transition-colors',
             config.letterSpacing===spacing
              ?'border-nier-border-dark bg-nier-bg-selected text-nier-text-main'
              : 'border-nier-border-light hover:bg-nier-bg-panel'
)}
            onClick={()=>handleLetterSpacingChange(spacing)}
           >
            {spacing==='tight'&&'タイト'}
            {spacing==='normal'&&'標準'}
            {spacing==='wide'&&'ワイド'}
           </button>
))}
         </div>
        </div>

        {/*Line Height*/}
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-2">
          行間: {config.lineHeight.toFixed(1)}
         </label>
         <input
          type="range"
          min="0.2"
          max="2.5"
          step="0.1"
          className="w-full"
          value={config.lineHeight}
          onChange={(e)=>handleLineHeightChange(parseFloat(e.target.value))}
         />
         <div className="flex justify-between text-nier-caption text-nier-text-light mt-1">
          <span>0.2 (最小)</span>
          <span>2.5 (広い)</span>
         </div>
        </div>

        {/*Padding*/}
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-2">
          余白: {config.padding}px
         </label>
         <input
          type="range"
          min="0"
          max="15"
          step="1"
          className="w-full"
          value={config.padding}
          onChange={(e)=>handlePaddingChange(parseInt(e.target.value))}
         />
         <div className="flex justify-between text-nier-caption text-nier-text-light mt-1">
          <span>0px (最小)</span>
          <span>15px (最大)</span>
         </div>
        </div>

        {/*Preview*/}
        <div className="nier-card border border-nier-border-light" style={{padding:`${config.padding}px`}}>
         <h4 className="text-nier-small font-medium mb-2">プレビュー</h4>
         <p className="text-nier-body">
          SYSTEM LOGS-Real-time Monitor
         </p>
         <p className="text-nier-small text-nier-text-light mt-1">
          エージェント別トークン消費についての説明文です。複数行にわたるテキストで行間の確認ができます。
         </p>
        </div>
       </CardContent>
      </Card>
)}
    </div>
   </div>
  </div>
)
}
