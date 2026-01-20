import{useState,useEffect}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{DollarSign,ToggleLeft,ToggleRight,RefreshCw,CheckCircle2,XCircle}from'lucide-react'
import{qualitySettingsApi,type QualityCheckConfig,type QualitySettingsResponse}from'@/services/apiService'

interface QualityCheckSettingsPanelProps{
 projectId:string
}

interface PhaseGroup{
 id:string
 label:string
 agents:string[]
}

const phaseGroups:PhaseGroup[] = [
 {
  id:'phase1_leaders',
  label:'Phase1: リーダー',
  agents:[
   'concept_leader',
   'design_leader',
   'scenario_leader',
   'character_leader',
   'world_leader',
   'task_split_leader',
  ]
 },
 {
  id:'phase1_workers',
  label:'Phase1: ワーカー',
  agents:[
   'research_worker','ideation_worker','concept_validation_worker',
   'architecture_worker','component_worker','dataflow_worker',
   'story_worker','dialog_worker','event_worker',
   'main_character_worker','npc_worker','relationship_worker',
   'geography_worker','lore_worker','system_worker',
   'analysis_worker','decomposition_worker','schedule_worker',
  ]
 },
 {
  id:'phase2',
  label:'Phase2: 開発',
  agents:[
   'code_leader','asset_leader',
   'code_worker','asset_worker',
  ]
 },
 {
  id:'phase3',
  label:'Phase3: 品質管理',
  agents:[
   'integrator_leader','tester_leader','reviewer_leader',
   'dependency_worker','build_worker','integration_validation_worker',
   'unit_test_worker','integration_test_worker','e2e_test_worker','performance_test_worker',
   'code_review_worker','asset_review_worker','gameplay_review_worker','compliance_worker',
  ]
 },
]

export function QualityCheckSettingsPanel({projectId}:QualityCheckSettingsPanelProps):JSX.Element{
 const[settings,setSettings] = useState<Record<string,QualityCheckConfig>>({})
 const[displayNames,setDisplayNames] = useState<Record<string,string>>({})
 const[loading,setLoading] = useState(true)
 const[saving,setSaving] = useState(false)
 const[error,setError] = useState<string | null>(null)

 useEffect(() => {
  loadSettings()
 },[projectId])

 const loadSettings = async() => {
  try{
   setLoading(true)
   setError(null)
   const response = await qualitySettingsApi.getByProject(projectId)
   setSettings(response.settings)
   setDisplayNames(response.displayNames)
  }catch(err){
   console.error('Failed to load quality settings:',err)
   setError('設定の読み込みに失敗しました')
  }finally{
   setLoading(false)
  }
 }

 const toggleSetting = async(agentType:string) => {
  const currentConfig = settings[agentType]
  if(!currentConfig)return

  try{
   setSaving(true)
   await qualitySettingsApi.updateSingle(projectId,agentType,{
    enabled:!currentConfig.enabled
   })
   setSettings(prev => ({
    ...prev,
    [agentType]:{
     ...prev[agentType],
     enabled:!currentConfig.enabled
    }
   }))
  }catch(err){
   console.error('Failed to update setting:',err)
   setError('設定の更新に失敗しました')
  }finally{
   setSaving(false)
  }
 }

 const setAllEnabled = async(enabled:boolean) => {
  try{
   setSaving(true)
   const updates:Record<string,{enabled:boolean}> = {}
   Object.keys(settings).forEach(agentType => {
    updates[agentType] = {enabled}
   })
   await qualitySettingsApi.bulkUpdate(projectId,updates)
   setSettings(prev => {
    const newSettings = {...prev}
    Object.keys(newSettings).forEach(key => {
     newSettings[key] = {...newSettings[key],enabled}
    })
    return newSettings
   })
  }catch(err){
   console.error('Failed to bulk update settings:',err)
   setError('一括更新に失敗しました')
  }finally{
   setSaving(false)
  }
 }

 const resetToDefaults = async() => {
  try{
   setSaving(true)
   const response = await qualitySettingsApi.resetToDefaults(projectId)
   setSettings(response.settings)
  }catch(err){
   console.error('Failed to reset settings:',err)
   setError('リセットに失敗しました')
  }finally{
   setSaving(false)
  }
 }

 const getEnabledCount = () => {
  return Object.values(settings).filter(s => s.enabled).length
 }

 const getTotalCount = () => {
  return Object.keys(settings).length
 }

 if(loading){
  return(
   <Card>
    <CardContent className="p-4">
     <p className="text-nier-text-light">読み込み中...</p>
    </CardContent>
   </Card>
  )
 }

 return(
  <div className="space-y-4">
   {/* Summary and Actions */}
   <Card>
    <CardHeader>
     <DiamondMarker>品質チェック設定</DiamondMarker>
    </CardHeader>
    <CardContent className="space-y-4">
     {error && (
      <div className="p-2 bg-nier-accent-red/20 text-nier-accent-red text-nier-small">
       {error}
      </div>
     )}

     <div className="flex items-center justify-between">
      <div className="text-nier-small">
       <span className="text-nier-accent-green">{getEnabledCount()}</span>
       <span className="text-nier-text-light"> / {getTotalCount()} エージェントで品質チェックON</span>
      </div>
      <div className="flex gap-2">
       <Button
        variant="ghost"
        size="sm"
        onClick={() => setAllEnabled(true)}
        disabled={saving}
       >
        <CheckCircle2 size={14} />
        <span className="ml-1">全てON</span>
       </Button>
       <Button
        variant="ghost"
        size="sm"
        onClick={() => setAllEnabled(false)}
        disabled={saving}
       >
        <XCircle size={14} />
        <span className="ml-1">全てOFF</span>
       </Button>
       <Button
        variant="ghost"
        size="sm"
        onClick={resetToDefaults}
        disabled={saving}
       >
        <RefreshCw size={14} />
        <span className="ml-1">デフォルトに戻す</span>
       </Button>
      </div>
     </div>

     <div className="p-3 bg-nier-bg-panel border border-nier-border-light text-nier-caption">
      <div className="flex items-center gap-2 text-nier-accent-yellow">
       <DollarSign size={14} />
       <span>高コストエージェント（アセット系）はデフォルトで品質チェックOFFです</span>
      </div>
     </div>
    </CardContent>
   </Card>

   {/* Phase Groups */}
   {phaseGroups.map(phase => (
    <Card key={phase.id}>
     <CardHeader>
      <DiamondMarker variant="secondary">{phase.label}</DiamondMarker>
     </CardHeader>
     <CardContent className="p-0">
      <div className="divide-y divide-nier-border-light">
       {phase.agents
        .filter(agentType => settings[agentType])
        .map(agentType => {
         const config = settings[agentType]
         const name = displayNames[agentType] || agentType

         return(
          <div
           key={agentType}
           className={cn(
            'flex items-center justify-between px-4 py-2 transition-colors',
            'hover:bg-nier-bg-panel'
           )}
          >
           <div className="flex items-center gap-3">
            {config.isHighCost && (
             <DollarSign
              size={14}
              className="text-nier-accent-yellow"
              title="高コストエージェント"
             />
            )}
            <div>
             <span className="text-nier-small text-nier-text-main">{name}</span>
             <span className="ml-2 text-nier-caption text-nier-text-light">
              ({agentType})
             </span>
            </div>
           </div>
           <button
            onClick={() => toggleSetting(agentType)}
            disabled={saving}
            className={cn(
             'p-1 rounded transition-colors',
             'focus:outline-none focus:ring-2 focus:ring-nier-accent-blue',
             saving && 'opacity-50 cursor-not-allowed'
            )}
            title={config.enabled ? '品質チェックON' : '品質チェックOFF'}
           >
            {config.enabled ? (
             <div className="flex items-center gap-1 text-nier-accent-green">
              <ToggleRight size={20} />
              <span className="text-nier-caption">ON</span>
             </div>
            ) : (
             <div className="flex items-center gap-1 text-nier-text-light">
              <ToggleLeft size={20} />
              <span className="text-nier-caption">OFF</span>
             </div>
            )}
           </button>
          </div>
         )
        })}
      </div>
     </CardContent>
    </Card>
   ))}
  </div>
 )
}
