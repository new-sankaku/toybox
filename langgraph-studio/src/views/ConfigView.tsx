import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Save,FolderOpen,ChevronDown,ChevronRight,RotateCcw}from'lucide-react'
import{AutoApprovalSettings}from'@/components/settings/AutoApprovalSettings'
import{useProjectStore}from'@/stores/projectStore'
import{useAutoApprovalStore}from'@/stores/autoApprovalStore'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{projectSettingsApi,type AdvancedSettingsResponse,type UsageCategorySetting,type PrincipleInfo}from'@/services/apiService'

interface ConfigSection{
 id:string
 label:string
}

const configSections:ConfigSection[]=[
 {id:'auto-approval',label:'自動承認設定'},
 {id:'output',label:'出力設定'},
 {id:'ai-models',label:'AIモデル設定'},
 {id:'principles',label:'品質原則'},
 {id:'advanced',label:'詳細設定'}
]

function AIModelSettings({projectId}:{projectId:string}):JSX.Element{
 const{master,fetchMaster,masterLoaded,getProviderLabel}=useAIServiceStore()
 const[categories,setCategories]=useState<UsageCategorySetting[]>([])
 const[originalCategories,setOriginalCategories]=useState<UsageCategorySetting[]>([])
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState<Record<string,boolean>>({})

 const loadData=useCallback(async()=>{
  setLoading(true)
  try{
   if(!masterLoaded)await fetchMaster()
   const cats=await projectSettingsApi.getUsageCategories(projectId)
   setCategories(cats)
   setOriginalCategories(JSON.parse(JSON.stringify(cats)))
  }catch(e){
   console.error('Failed to load AI model settings:',e)
  }finally{
   setLoading(false)
  }
 },[projectId,masterLoaded,fetchMaster])

 useEffect(()=>{loadData()},[loadData])

 const handleChange=(catId:string,field:'provider'|'model',value:string)=>{
  setCategories(prev=>prev.map(c=>c.id===catId?{...c,[field]:value}:c))
 }

 const handleSave=async(catId:string)=>{
  const cat=categories.find(c=>c.id===catId)
  if(!cat)return
  setSaving(p=>({...p,[catId]:true}))
  try{
   await projectSettingsApi.updateUsageCategory(projectId,catId,{provider:cat.provider,model:cat.model})
   setOriginalCategories(prev=>prev.map(c=>c.id===catId?{...c,provider:cat.provider,model:cat.model}:c))
  }catch(e){
   console.error('Failed to save:',e)
  }finally{
   setSaving(p=>({...p,[catId]:false}))
  }
 }

 const handleReset=async(catId:string)=>{
  setSaving(p=>({...p,[catId]:true}))
  try{
   const result=await projectSettingsApi.resetUsageCategory(projectId,catId)
   setCategories(prev=>prev.map(c=>c.id===catId?{...c,provider:result.provider,model:result.model}:c))
   setOriginalCategories(prev=>prev.map(c=>c.id===catId?{...c,provider:result.provider,model:result.model}:c))
  }catch(e){
   console.error('Failed to reset:',e)
  }finally{
   setSaving(p=>({...p,[catId]:false}))
  }
 }

 const isChanged=(catId:string)=>{
  const current=categories.find(c=>c.id===catId)
  const original=originalCategories.find(c=>c.id===catId)
  if(!current||!original)return false
  return current.provider!==original.provider||current.model!==original.model
 }

 const getModelsForProvider=(providerId:string)=>{
  if(!master)return[]
  return master.providers[providerId]?.models||[]
 }

 const getProvidersForServiceType=(serviceType:string)=>{
  if(!master)return[]
  return Object.entries(master.providers)
   .filter(([,p])=>p.serviceTypes.includes(serviceType))
   .map(([id])=>id)
 }

 if(loading){
  return<div className="text-center py-8 text-nier-text-light">読み込み中...</div>
 }

 const grouped:{[key:string]:UsageCategorySetting[]}={}
 for(const cat of categories){
  const st=cat.service_type||'other'
  if(!grouped[st])grouped[st]=[]
  grouped[st].push(cat)
 }

 const serviceTypeLabels:Record<string,string>={llm:'LLM',image:'画像生成',audio:'音声生成',music:'音楽生成'}

 return(
  <div className="space-y-4">
   {Object.entries(grouped).map(([serviceType,cats])=>(
    <Card key={serviceType}>
     <CardHeader>
      <DiamondMarker>{serviceTypeLabels[serviceType]||serviceType}</DiamondMarker>
     </CardHeader>
     <CardContent className="space-y-4">
      {cats.map(cat=>{
       const providers=getProvidersForServiceType(cat.service_type)
       const models=getModelsForProvider(cat.provider)
       const changed=isChanged(cat.id)
       return(
        <div key={cat.id} className="grid grid-cols-[1fr_1fr_1fr_auto_auto] gap-2 items-center">
         <div>
          <label className="block text-nier-caption text-nier-text-light mb-1">{cat.label}</label>
         </div>
         <div>
          <select
           className={cn(
            'w-full bg-nier-bg-panel border px-2 py-1 text-nier-small focus:outline-none focus:border-nier-border-dark',
            changed?'border-nier-accent-orange':'border-nier-border-light'
)}
           value={cat.provider}
           onChange={(e)=>{
            handleChange(cat.id,'provider',e.target.value)
            const newModels=getModelsForProvider(e.target.value)
            if(newModels.length>0)handleChange(cat.id,'model',newModels[0].id)
           }}
          >
           {providers.map(pid=>(
            <option key={pid} value={pid}>{getProviderLabel(pid)}</option>
))}
          </select>
         </div>
         <div>
          <select
           className={cn(
            'w-full bg-nier-bg-panel border px-2 py-1 text-nier-small focus:outline-none focus:border-nier-border-dark',
            changed?'border-nier-accent-orange':'border-nier-border-light'
)}
           value={cat.model}
           onChange={(e)=>handleChange(cat.id,'model',e.target.value)}
          >
           {models.map(m=>(
            <option key={m.id} value={m.id}>{m.label||m.id}</option>
))}
          </select>
         </div>
         <Button variant="ghost" size="sm" onClick={()=>handleReset(cat.id)} disabled={!!saving[cat.id]}>
          <RotateCcw size={12}/>
         </Button>
         <Button variant="primary" size="sm" onClick={()=>handleSave(cat.id)} disabled={!changed||!!saving[cat.id]}>
          <Save size={12}/>
         </Button>
        </div>
)
      })}
     </CardContent>
    </Card>
))}
  </div>
)
}

function PrincipleSettings({projectId}:{projectId:string}):JSX.Element{
 const[principles,setPrinciples]=useState<PrincipleInfo[]>([])
 const[enabled,setEnabled]=useState<string[]>([])
 const[originalEnabled,setOriginalEnabled]=useState<string[]>([])
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState(false)

 const loadData=useCallback(async()=>{
  setLoading(true)
  try{
   const[listData,projectData]=await Promise.all([
    projectSettingsApi.getPrinciplesList(),
    projectSettingsApi.getProjectPrinciples(projectId)
])
   setPrinciples(listData.principles)
   const allIds=listData.principles.map(p=>p.id)
   const current=projectData.enabledPrinciples??allIds
   setEnabled(current)
   setOriginalEnabled(current)
  }catch(e){
   console.error('Failed to load principles:',e)
  }finally{
   setLoading(false)
  }
 },[projectId])

 useEffect(()=>{loadData()},[loadData])

 const hasChanges=JSON.stringify(enabled.sort())!==JSON.stringify(originalEnabled.sort())

 const handleToggle=(id:string)=>{
  setEnabled(prev=>prev.includes(id)?prev.filter(p=>p!==id):[...prev,id])
 }

 const handleSave=async()=>{
  setSaving(true)
  try{
   await projectSettingsApi.updateProjectPrinciples(projectId,{enabledPrinciples:enabled})
   setOriginalEnabled([...enabled])
  }catch(e){
   console.error('Failed to save principles:',e)
  }finally{
   setSaving(false)
  }
 }

 const handleReset=()=>{
  const allIds=principles.map(p=>p.id)
  setEnabled(allIds)
 }

 if(loading){
  return<div className="text-center py-8 text-nier-text-light">読み込み中...</div>
 }

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader>
     <DiamondMarker>品質原則の選択</DiamondMarker>
     <span className="text-nier-caption text-nier-text-light ml-2">エージェントが参照する品質基準</span>
    </CardHeader>
    <CardContent className="space-y-3">
     <p className="text-nier-small text-nier-text-light">
      有効にした原則がエージェントのプロンプトに含まれ、出力品質の評価基準となります。
     </p>
     <div className="grid grid-cols-1 gap-2">
      {principles.map(p=>(
       <label key={p.id} className={cn(
        'flex items-start gap-3 p-3 border cursor-pointer transition-colors',
        enabled.includes(p.id)?'border-nier-border-dark bg-nier-bg-selected':'border-nier-border-light bg-nier-bg-panel hover:bg-nier-bg-selected'
)}>
        <input
         type="checkbox"
         className="mt-1"
         checked={enabled.includes(p.id)}
         onChange={()=>handleToggle(p.id)}
        />
        <div className="flex-1 min-w-0">
         <div className="text-nier-small text-nier-text-main font-medium">{p.label}</div>
         <div className="text-nier-caption text-nier-text-light">{p.description}</div>
        </div>
       </label>
))}
     </div>
     <div className="flex gap-2 justify-end pt-2">
      <Button variant="ghost" size="sm" onClick={handleReset}>
       <RotateCcw size={12}/>
       <span className="ml-1">全て有効</span>
      </Button>
      <Button variant="primary" size="sm" onClick={handleSave} disabled={!hasChanges||saving}>
       <Save size={12}/>
       <span className="ml-1">{saving?'保存中...':'保存'}</span>
      </Button>
     </div>
    </CardContent>
   </Card>
  </div>
)
}

function AdvancedSettings({projectId}:{projectId:string}):JSX.Element{
 const[settings,setSettings]=useState<AdvancedSettingsResponse|null>(null)
 const[originalSettings,setOriginalSettings]=useState<AdvancedSettingsResponse|null>(null)
 const[loading,setLoading]=useState(true)
 const[expanded,setExpanded]=useState<Record<string,boolean>>({
  quality:true,
  token:false,
  execution:false,
  temperature:false,
  context:false
 })

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

 const handleSave=async()=>{
  if(!settings)return
  try{
   const updated=await projectSettingsApi.updateAdvancedSettings(projectId,settings)
   setSettings(updated)
   setOriginalSettings(updated)
  }catch(e){
   console.error('Failed to save advanced settings:',e)
  }
 }

 const toggle=(key:string)=>setExpanded(p=>({...p,[key]:!p[key]}))

 if(loading){
  return<div className="text-center py-8 text-nier-text-light">読み込み中...</div>
 }

 if(!settings){
  return<div className="text-center py-8 text-nier-text-light">設定を取得できませんでした</div>
 }

 return(
  <div className="space-y-4">
   <Card>
    <CardHeader className="cursor-pointer" onClick={()=>toggle('quality')}>
     {expanded.quality?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
     <DiamondMarker>品質チェック設定</DiamondMarker>
    </CardHeader>
    {expanded.quality&&(
     <CardContent className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">品質閾値 (0.0-1.0)</label>
        <input
         type="number"
         min={0}
         max={1}
         step={0.1}
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
         value={settings.qualityCheck.quality_threshold}
         onChange={(e)=>setSettings({...settings,qualityCheck:{...settings.qualityCheck,quality_threshold:parseFloat(e.target.value)||0}})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">エスカレーション</label>
        <select
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={settings.qualityCheck.escalation.tier2_score_max}
          onChange={(e)=>setSettings({...settings,qualityCheck:{...settings.qualityCheck,escalation:{...settings.qualityCheck.escalation,tier2_score_max:parseFloat(e.target.value)||0}}})}
         />
        </div>
       </div>
)}
     </CardContent>
)}
   </Card>

   <Card>
    <CardHeader className="cursor-pointer" onClick={()=>toggle('token')}>
     {expanded.token?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
     <DiamondMarker>トークン予算設定</DiamondMarker>
    </CardHeader>
    {expanded.token&&(
     <CardContent className="space-y-4">
      <div className="grid grid-cols-3 gap-4">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">最大トークン数</label>
        <input
         type="number"
         min={0}
         step={10000}
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
         value={settings.tokenBudget.warning_threshold_percent}
         onChange={(e)=>setSettings({...settings,tokenBudget:{...settings.tokenBudget,warning_threshold_percent:parseInt(e.target.value)||0}})}
        />
       </div>
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">制限モード</label>
        <select
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
         value={settings.tokenBudget.enforcement}
         onChange={(e)=>setSettings({...settings,tokenBudget:{...settings.tokenBudget,enforcement:e.target.value as'hard'|'soft'}})}
        >
         <option value="hard">ハード（超過時停止）</option>
         <option value="soft">ソフト（警告のみ）</option>
        </select>
       </div>
      </div>
     </CardContent>
)}
   </Card>

   <Card>
    <CardHeader className="cursor-pointer" onClick={()=>toggle('execution')}>
     {expanded.execution?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
     <DiamondMarker>実行制限設定</DiamondMarker>
    </CardHeader>
    {expanded.execution&&(
     <CardContent className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">DAG並列実行</label>
        <select
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
         value={settings.toolExecution.loop_detection_threshold}
         onChange={(e)=>setSettings({...settings,toolExecution:{...settings.toolExecution,loop_detection_threshold:parseInt(e.target.value)||3}})}
        />
       </div>
      </div>
     </CardContent>
)}
   </Card>

   <Card>
    <CardHeader className="cursor-pointer" onClick={()=>toggle('temperature')}>
     {expanded.temperature?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
     <DiamondMarker>Temperature設定</DiamondMarker>
    </CardHeader>
    {expanded.temperature&&(
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
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={value}
          onChange={(e)=>setSettings({...settings,temperatureDefaults:{...settings.temperatureDefaults,[role]:parseFloat(e.target.value)||0}})}
         />
        </div>
))}
      </div>
     </CardContent>
)}
   </Card>

   <Card>
    <CardHeader className="cursor-pointer" onClick={()=>toggle('context')}>
     {expanded.context?<ChevronDown size={16}/>:<ChevronRight size={16}/>}
     <DiamondMarker>コンテキストポリシー設定</DiamondMarker>
    </CardHeader>
    {expanded.context&&(
     <CardContent className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
       <div>
        <label className="block text-nier-caption text-nier-text-light mb-1">自動要約閾値 (文字数)</label>
        <input
         type="number"
         min={1000}
         step={1000}
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
         className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
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
          className="w-full bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
          value={settings.contextPolicy.llm_summary.input_max_length}
          onChange={(e)=>setSettings({...settings,contextPolicy:{...settings.contextPolicy,llm_summary:{...settings.contextPolicy.llm_summary,input_max_length:parseInt(e.target.value)||30000}}})}
         />
        </div>
       </div>
      </div>
     </CardContent>
)}
   </Card>

   {hasChanges&&(
    <div className="flex justify-end">
     <Button variant="primary" onClick={handleSave}>
      <Save size={14}/>
      <span className="ml-1">詳細設定を保存</span>
     </Button>
    </div>
)}
  </div>
)
}

export default function ConfigView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{saveToServer:saveAutoApproval}=useAutoApprovalStore()
 const[activeSection,setActiveSection]=useState('auto-approval')
 const[outputDir,setOutputDir]=useState('./output')
 const[originalOutputDir,setOriginalOutputDir]=useState('./output')
 const[saving,setSaving]=useState(false)
 const outputDirChanged=outputDir!==originalOutputDir

 const loadOutputSettings=useCallback(async()=>{
  if(!currentProject)return
  try{
   const settings=await projectSettingsApi.getOutputSettings(currentProject.id)
   const dir=settings.default_dir||'./output'
   setOutputDir(dir)
   setOriginalOutputDir(dir)
  }catch(error){
   console.error('Failed to load output settings:',error)
  }
 },[currentProject])

 useEffect(()=>{
  loadOutputSettings()
 },[loadOutputSettings])

 const handleSave=useCallback(async()=>{
  if(!currentProject)return
  setSaving(true)
  try{
   await saveAutoApproval()
   await projectSettingsApi.updateOutputSettings(currentProject.id,{default_dir:outputDir})
   setOriginalOutputDir(outputDir)
  }catch(error){
   console.error('Failed to save settings:',error)
  }finally{
   setSaving(false)
  }
 },[currentProject,saveAutoApproval,outputDir])

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
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
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   <div className="flex-1 flex gap-3 overflow-hidden">
    <div className="w-48 flex-shrink-0 flex flex-col overflow-hidden">
     <Card className="flex flex-col overflow-hidden">
      <CardHeader>
       <DiamondMarker>プロジェクト設定</DiamondMarker>
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
            :'text-nier-text-light hover:bg-nier-bg-panel'
)}
          onClick={()=>setActiveSection(section.id)}
         >
          {section.label}
         </button>
))}
       </div>
       <div className="p-3 border-t border-nier-border-light">
        <Button variant="primary" size="sm" className="w-full" onClick={handleSave} disabled={saving}>
         <Save size={14}/>
         <span className="ml-1">{saving?'保存中...':'保存'}</span>
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>

    <div className="flex-1 min-h-0 overflow-y-auto space-y-4">
     {activeSection==='auto-approval'&&<AutoApprovalSettings projectId={currentProject.id}/>}

     {activeSection==='output'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>出力設定</DiamondMarker>
       </CardHeader>
       <CardContent>
        <div>
         <label className={cn('block text-nier-caption mb-1',outputDirChanged?'text-nier-accent-red':'text-nier-text-light')}>
          出力ディレクトリ
         </label>
         <input
          type="text"
          className={cn(
           'w-full bg-nier-bg-panel border px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark',
           outputDirChanged?'border-nier-accent-red text-nier-accent-red':'border-nier-border-light'
)}
          value={outputDir}
          onChange={(e)=>setOutputDir(e.target.value)}
         />
        </div>
       </CardContent>
      </Card>
)}

     {activeSection==='ai-models'&&<AIModelSettings projectId={currentProject.id}/>}

     {activeSection==='principles'&&<PrincipleSettings projectId={currentProject.id}/>}

     {activeSection==='advanced'&&<AdvancedSettings projectId={currentProject.id}/>}
    </div>
   </div>
  </div>
)
}
