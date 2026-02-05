import{useState,useEffect,useCallback,Fragment}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Badge}from'@/components/ui/Badge'
import{RotateCcw,Save,ChevronDown,ChevronRight}from'lucide-react'
import{
 projectSettingsApi,projectApi,
 type PrincipleInfo,type AgentPrincipleMeta,type UiPhaseInfo
}from'@/services/apiService'

interface PrincipleSettingsProps{
 projectId:string
}

export function PrincipleSettings({projectId}:PrincipleSettingsProps):JSX.Element{
 const[principles,setPrinciples]=useState<PrincipleInfo[]>([])
 const[enabled,setEnabled]=useState<string[]>([])
 const[originalEnabled,setOriginalEnabled]=useState<string[]>([])
 const[overrides,setOverrides]=useState<Record<string,string[]>>({})
 const[originalOverrides,setOriginalOverrides]=useState<Record<string,string[]>>({})
 const[defaults,setDefaults]=useState<Record<string,string[]>>({})
 const[agentsMeta,setAgentsMeta]=useState<Record<string,AgentPrincipleMeta>>({})
 const[uiPhases,setUiPhases]=useState<UiPhaseInfo[]>([])
 const[expandedPhases,setExpandedPhases]=useState<Record<string,boolean>>({})
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
   setDefaults(listData.defaults)
   setAgentsMeta(listData.agents??{})
   setUiPhases(listData.uiPhases??[])
   const allIds=listData.principles.map(p=>p.id)
   const current=projectData.enabledPrinciples??allIds
   setEnabled(current)
   setOriginalEnabled(current)
   const ov=projectData.overrides??{}
   setOverrides(ov)
   setOriginalOverrides(ov)
  }catch(e){
   console.error('Failed to load principles:',e)
  }finally{
   setLoading(false)
  }
 },[projectId])

 useEffect(()=>{loadData()},[loadData])

 const hasEnabledChanges=JSON.stringify([...enabled].sort())!==JSON.stringify([...originalEnabled].sort())
 const hasOverrideChanges=JSON.stringify(overrides)!==JSON.stringify(originalOverrides)
 const hasChanges=hasEnabledChanges||hasOverrideChanges

 const handleToggle=(id:string)=>{
  setEnabled(prev=>prev.includes(id)?prev.filter(p=>p!==id):[...prev,id])
 }

 const getEffectivePrinciples=(agentType:string):string[]=>{
  return overrides[agentType]??defaults[agentType]??defaults['_default']??[]
 }

 const handleAgentPrincipleToggle=(agentType:string,principleId:string)=>{
  const effective=getEffectivePrinciples(agentType)
  const updated=effective.includes(principleId)
   ?effective.filter(p=>p!==principleId)
   :[...effective,principleId]
  setOverrides(prev=>({...prev,[agentType]:updated}))
 }

 const handleResetAgent=(agentType:string)=>{
  setOverrides(prev=>{
   const next={...prev}
   delete next[agentType]
   return next
  })
 }

 const handleSaveToProject=async()=>{
  setSaving(true)
  try{
   await projectSettingsApi.updateProjectPrinciples(projectId,{
    enabledPrinciples:enabled,
    overrides:Object.keys(overrides).length>0?overrides:undefined
   })
   setOriginalEnabled([...enabled])
   setOriginalOverrides({...overrides})
  }catch(e){
   console.error('Failed to save principles:',e)
  }finally{
   setSaving(false)
  }
 }

 const handleSaveToAllProjects=async()=>{
  setSaving(true)
  try{
   const projects=await projectApi.list()
   const settings={
    enabledPrinciples:enabled,
    overrides:Object.keys(overrides).length>0?overrides:undefined
   }
   for(const project of projects){
    await projectSettingsApi.updateProjectPrinciples(project.id,settings)
   }
   setOriginalEnabled([...enabled])
   setOriginalOverrides({...overrides})
  }catch(e){
   console.error('Failed to save to all projects:',e)
  }finally{
   setSaving(false)
  }
 }

 const handleResetAll=()=>{
  const allIds=principles.map(p=>p.id)
  setEnabled(allIds)
  setOverrides({})
 }

 const togglePhase=(phaseId:string)=>{
  setExpandedPhases(prev=>({...prev,[phaseId]:!prev[phaseId]}))
 }

 const isAgentCustomized=(agentType:string):boolean=>{
  return agentType in overrides
 }

 if(loading){
  return<div className="nier-surface-panel text-center py-8">読み込み中...</div>
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
        enabled.includes(p.id)?'border-nier-border-dark nier-surface-selected':'border-nier-border-light nier-surface-panel hover:bg-nier-bg-selected'
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
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <DiamondMarker>エージェント別 原則割り当て</DiamondMarker>
     <span className="text-nier-caption text-nier-text-light ml-2">各エージェントに適用する原則を個別設定</span>
    </CardHeader>
    <CardContent className="space-y-3">
     <p className="text-nier-small text-nier-text-light">
      エージェントごとに参照する原則を変更できます。上のグローバル設定で無効にした原則はここでも無効になります。
     </p>
     <div className="space-y-1">
      {uiPhases.map(phase=>(
       <div key={phase.id} className="border border-nier-border-light">
        <button
         className="w-full flex items-center gap-2 p-2 nier-surface-header text-left hover:opacity-80 transition-opacity"
         onClick={()=>togglePhase(phase.id)}
        >
         {expandedPhases[phase.id]
          ?<ChevronDown size={14}/>
          :<ChevronRight size={14}/>
         }
         <span className="text-nier-small font-medium">{phase.label}</span>
         <span className="text-nier-caption text-nier-text-light">({phase.agents.length})</span>
        </button>
        {expandedPhases[phase.id]&&(
         <div className="p-2 nier-surface-panel overflow-x-auto">
          <div className="grid gap-x-1 gap-y-1 items-center" style={{gridTemplateColumns:`minmax(0,1fr) repeat(${principles.length},2rem) auto`}}>
           <div className="text-nier-caption text-nier-text-light font-medium px-1"/>
           {principles.map(p=>(
            <div key={p.id} className="text-center" title={p.label}>
             <span className={cn('text-nier-caption',enabled.includes(p.id)?'text-nier-text-main':'text-nier-text-light opacity-40')}>
              {p.id.slice(0,2).toUpperCase()}
             </span>
            </div>
           ))}
           <div/>
           {phase.agents.map(agentType=>{
            const meta=agentsMeta[agentType]
            if(!meta)return null
            const effective=getEffectivePrinciples(agentType)
            const customized=isAgentCustomized(agentType)
            return(
             <Fragment key={agentType}>
              <div className="text-nier-caption text-nier-text-main truncate px-1" title={meta.label}>
               {meta.shortLabel||meta.label}
               {customized&&<Badge variant="orange" className="ml-1 text-[0.6rem] px-1 py-0">custom</Badge>}
              </div>
              {principles.map(p=>{
               const globalEnabled=enabled.includes(p.id)
               const checked=effective.includes(p.id)
               return(
                <div key={p.id} className="flex justify-center">
                 <input
                  type="checkbox"
                  className={cn('cursor-pointer',!globalEnabled&&'opacity-30')}
                  checked={checked&&globalEnabled}
                  disabled={!globalEnabled}
                  onChange={()=>handleAgentPrincipleToggle(agentType,p.id)}
                 />
                </div>
               )
              })}
              <div className="flex justify-center">
               {customized&&(
                <button
                 className="text-nier-text-light hover:text-nier-text-main transition-colors p-0.5"
                 onClick={()=>handleResetAgent(agentType)}
                 title="デフォルトに戻す"
                >
                 <RotateCcw size={10}/>
                </button>
               )}
              </div>
             </Fragment>
            )
           })}
          </div>
         </div>
        )}
       </div>
      ))}
     </div>
     <div className="flex gap-2 justify-end pt-2">
      <Button variant="ghost" size="sm" onClick={handleResetAll}>
       <RotateCcw size={12}/>
       <span className="ml-1">デフォルトに戻す</span>
      </Button>
      <Button variant="secondary" size="sm" onClick={handleSaveToProject} disabled={!hasChanges||saving}>
       <Save size={12}/>
       <span className="ml-1">{saving?'保存中...':'このプロジェクトに保存'}</span>
      </Button>
      <Button variant="primary" size="sm" onClick={handleSaveToAllProjects} disabled={!hasChanges||saving}>
       <Save size={12}/>
       <span className="ml-1">{saving?'保存中...':'全てのプロジェクトに保存'}</span>
      </Button>
     </div>
    </CardContent>
   </Card>
  </div>
 )
}
