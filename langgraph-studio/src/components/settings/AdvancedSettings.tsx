import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{Save}from'lucide-react'
import{
 projectSettingsApi,projectApi,
 type AdvancedSettingsResponse
}from'@/services/apiService'

interface AdvancedSettingsProps{
 projectId:string
}

export function AdvancedSettings({projectId}:AdvancedSettingsProps):JSX.Element{
 const[settings,setSettings]=useState<AdvancedSettingsResponse|null>(null)
 const[originalSettings,setOriginalSettings]=useState<AdvancedSettingsResponse|null>(null)
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState(false)

 const loadSettings=useCallback(async()=>{
  setLoading(true)
  try{
   const data=await projectSettingsApi.getAdvancedSettings(projectId)
   setSettings(data)
   setOriginalSettings(data)
  }catch(e){
   console.error('Failed to load advanced settings:',e)
  }finally{
   setLoading(false)
  }
 },[projectId])

 useEffect(()=>{loadSettings()},[loadSettings])

 const hasChanges=settings&&originalSettings&&JSON.stringify(settings)!==JSON.stringify(originalSettings)

 const handleSaveToProject=async()=>{
  if(!settings)return
  setSaving(true)
  try{
   const updated=await projectSettingsApi.updateAdvancedSettings(projectId,settings)
   setSettings(updated)
   setOriginalSettings(updated)
  }catch(e){
   console.error('Failed to save advanced settings:',e)
  }finally{
   setSaving(false)
  }
 }

 const handleSaveToAllProjects=async()=>{
  if(!settings)return
  setSaving(true)
  try{
   const projects=await projectApi.list()
   for(const project of projects){
    await projectSettingsApi.updateAdvancedSettings(project.id,settings)
   }
   setOriginalSettings(settings)
  }catch(e){
   console.error('Failed to save to all projects:',e)
  }finally{
   setSaving(false)
  }
 }

 if(loading){
  return<div className="nier-surface-panel text-center py-8">読み込み中...</div>
 }

 if(!settings){
  return<div className="nier-surface-panel text-center py-8">設定を取得できませんでした</div>
 }

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <DiamondMarker>品質チェック設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     <div className="grid grid-cols-2 gap-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">品質閾値 (0.0-1.0)</label>
       <input
        type="number"
        min={0}
        max={1}
        step={0.1}
        className="nier-input w-full"
        value={settings.qualityCheck.quality_threshold}
        onChange={(e)=>setSettings({...settings,qualityCheck:{...settings.qualityCheck,quality_threshold:parseFloat(e.target.value)||0}})}
       />
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">エスカレーション</label>
       <select
        className="nier-input w-full"
        value={settings.qualityCheck.escalation.enabled?'enabled':'disabled'}
        onChange={(e)=>setSettings({...settings,qualityCheck:{...settings.qualityCheck,escalation:{...settings.qualityCheck.escalation,enabled:e.target.value==='enabled'}}})}
       >
        <option value="enabled">有効</option>
        <option value="disabled">無効</option>
       </select>
      </div>
     </div>
     {settings.qualityCheck.escalation.enabled&&(
      <div className="grid grid-cols-2 gap-4 pl-4 border-l-2 border-nier-border-light">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">エスカレーション下限スコア</label>
        <input
         type="number"
         min={0}
         max={1}
         step={0.1}
         className="nier-input w-full"
         value={settings.qualityCheck.escalation.tier2_score_min}
         onChange={(e)=>setSettings({...settings,qualityCheck:{...settings.qualityCheck,escalation:{...settings.qualityCheck.escalation,tier2_score_min:parseFloat(e.target.value)||0}}})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">エスカレーション上限スコア</label>
        <input
         type="number"
         min={0}
         max={1}
         step={0.1}
         className="nier-input w-full"
         value={settings.qualityCheck.escalation.tier2_score_max}
         onChange={(e)=>setSettings({...settings,qualityCheck:{...settings.qualityCheck,escalation:{...settings.qualityCheck.escalation,tier2_score_max:parseFloat(e.target.value)||0}}})}
        />
       </div>
      </div>
)}
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <DiamondMarker>トークン予算設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     <div className="grid grid-cols-3 gap-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">最大トークン数</label>
       <input
        type="number"
        min={0}
        step={10000}
        className="nier-input w-full"
        value={settings.tokenBudget.default_limit}
        onChange={(e)=>setSettings({...settings,tokenBudget:{...settings.tokenBudget,default_limit:parseInt(e.target.value)||0}})}
       />
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">警告閾値 (%)</label>
       <input
        type="number"
        min={0}
        max={100}
        className="nier-input w-full"
        value={settings.tokenBudget.warning_threshold_percent}
        onChange={(e)=>setSettings({...settings,tokenBudget:{...settings.tokenBudget,warning_threshold_percent:parseInt(e.target.value)||0}})}
       />
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">制限モード</label>
       <select
        className="nier-input w-full"
        value={settings.tokenBudget.enforcement}
        onChange={(e)=>setSettings({...settings,tokenBudget:{...settings.tokenBudget,enforcement:e.target.value as'hard'|'soft'}})}
       >
        <option value="hard">ハード（超過時停止）</option>
        <option value="soft">ソフト（警告のみ）</option>
       </select>
      </div>
     </div>
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <DiamondMarker>実行制限設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     <div className="grid grid-cols-2 gap-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">DAG並列実行</label>
       <select
        className="nier-input w-full"
        value={settings.dagExecution.enabled?'enabled':'disabled'}
        onChange={(e)=>setSettings({...settings,dagExecution:{...settings.dagExecution,enabled:e.target.value==='enabled'}})}
       >
        <option value="enabled">有効（並列）</option>
        <option value="disabled">無効（逐次）</option>
       </select>
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">最大イテレーション数</label>
       <input
        type="number"
        min={1}
        max={200}
        className="nier-input w-full"
        value={settings.toolExecution.max_iterations}
        onChange={(e)=>setSettings({...settings,toolExecution:{...settings.toolExecution,max_iterations:parseInt(e.target.value)||50}})}
       />
      </div>
     </div>
     <div className="grid grid-cols-2 gap-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">タイムアウト (秒)</label>
       <input
        type="number"
        min={30}
        max={600}
        className="nier-input w-full"
        value={settings.toolExecution.timeout_seconds}
        onChange={(e)=>setSettings({...settings,toolExecution:{...settings.toolExecution,timeout_seconds:parseInt(e.target.value)||300}})}
       />
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">ループ検出閾値</label>
       <input
        type="number"
        min={2}
        max={10}
        className="nier-input w-full"
        value={settings.toolExecution.loop_detection_threshold}
        onChange={(e)=>setSettings({...settings,toolExecution:{...settings.toolExecution,loop_detection_threshold:parseInt(e.target.value)||3}})}
       />
      </div>
     </div>
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <DiamondMarker>Temperature設定</DiamondMarker>
    </CardHeader>
    <CardContent>
     <div className="grid grid-cols-3 gap-4">
      {Object.entries(settings.temperatureDefaults).map(([role,value])=>(
       <div key={role}>
        <label className="block text-nier-caption text-nier-text-light mb-1">{role}</label>
        <input
         type="number"
         min={0}
         max={2}
         step={0.1}
         className="nier-input w-full"
         value={value}
         onChange={(e)=>setSettings({...settings,temperatureDefaults:{...settings.temperatureDefaults,[role]:parseFloat(e.target.value)||0}})}
        />
       </div>
))}
     </div>
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <DiamondMarker>コンテキストポリシー設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     <div className="grid grid-cols-2 gap-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">自動要約閾値 (文字数)</label>
       <input
        type="number"
        min={1000}
        step={1000}
        className="nier-input w-full"
        value={settings.contextPolicy.auto_downgrade_threshold}
        onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,auto_downgrade_threshold:parseInt(e.target.value)||15000}})}
       />
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">要約最大長 (文字数)</label>
       <input
        type="number"
        min={1000}
        step={1000}
        className="nier-input w-full"
        value={settings.contextPolicy.summary_max_length}
        onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,summary_max_length:parseInt(e.target.value)||10000}})}
       />
      </div>
     </div>
     <div className="grid grid-cols-2 gap-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">Leader出力→Worker最大長</label>
       <input
        type="number"
        min={500}
        step={500}
        className="nier-input w-full"
        value={settings.contextPolicy.leader_output_max_for_worker}
        onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,leader_output_max_for_worker:parseInt(e.target.value)||5000}})}
       />
      </div>
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">リトライ時前回出力最大長</label>
       <input
        type="number"
        min={500}
        step={500}
        className="nier-input w-full"
        value={settings.contextPolicy.retry_previous_output_max}
        onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,retry_previous_output_max:parseInt(e.target.value)||3000}})}
       />
      </div>
     </div>
     <div className="border-t border-nier-border-light pt-4">
      <label className="block text-nier-caption text-nier-text-light mb-2">LLM要約設定</label>
      <div className="grid grid-cols-3 gap-4 pl-4 border-l-2 border-nier-border-light">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">LLM要約</label>
        <select
         className="nier-input w-full"
         value={settings.contextPolicy.llm_summary.enabled?'enabled':'disabled'}
         onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,llm_summary:{...settings.contextPolicy.llm_summary,enabled:e.target.value==='enabled'}}})}
        >
         <option value="enabled">有効</option>
         <option value="disabled">無効（切り詰め）</option>
        </select>
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">最大出力トークン</label>
        <input
         type="number"
         min={256}
         step={256}
         className="nier-input w-full"
         value={settings.contextPolicy.llm_summary.max_tokens}
         onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,llm_summary:{...settings.contextPolicy.llm_summary,max_tokens:parseInt(e.target.value)||2048}}})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">入力最大長</label>
        <input
         type="number"
         min={1000}
         step={1000}
         className="nier-input w-full"
         value={settings.contextPolicy.llm_summary.input_max_length}
         onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,llm_summary:{...settings.contextPolicy.llm_summary,input_max_length:parseInt(e.target.value)||30000}}})}
        />
       </div>
      </div>
     </div>
    </CardContent>
   </Card>

   {hasChanges&&(
    <div className="flex gap-2 justify-end">
     <Button variant="secondary" onClick={handleSaveToProject} disabled={saving}>
      <Save size={14}/>
      <span className="ml-1">{saving?'保存中...':'このプロジェクトに保存'}</span>
     </Button>
     <Button variant="primary" onClick={handleSaveToAllProjects} disabled={saving}>
      <Save size={14}/>
      <span className="ml-1">{saving?'保存中...':'全てのプロジェクトに保存'}</span>
     </Button>
    </div>
)}
  </div>
)
}
