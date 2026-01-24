import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Save,FolderOpen,RefreshCw}from'lucide-react'
import{AutoApprovalSettings}from'@/components/settings/AutoApprovalSettings'
import{AIProviderSettings}from'@/components/settings/AIProviderSettings'
import{CostSettings}from'@/components/settings/CostSettings'
import{useProjectStore}from'@/stores/projectStore'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{useAutoApprovalStore}from'@/stores/autoApprovalStore'
import{useCostSettingsStore}from'@/stores/costSettingsStore'
import{projectSettingsApi}from'@/services/apiService'

interface ConfigSection{
 id:string
 label:string
}

const configSections:ConfigSection[]=[
 {id:'ai-services',label:'AIサービス設定'},
 {id:'auto-approval',label:'自動承認設定'},
 {id:'cost',label:'コスト設定'},
 {id:'output',label:'出力設定'}
]

export default function ConfigView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{saveProviderConfigs,resetProviderConfigs}=useAIServiceStore()
 const{saveToServer:saveAutoApproval}=useAutoApprovalStore()
 const{saveToServer:saveCostSettings,resetToDefaults:resetCostSettings}=useCostSettingsStore()
 const[activeSection,setActiveSection]=useState('ai-services')
 const[outputDir,setOutputDir]=useState('./output')
 const[saving,setSaving]=useState(false)

 const loadOutputSettings=useCallback(async()=>{
  if(!currentProject)return
  try{
   const settings=await projectSettingsApi.getOutputSettings(currentProject.id)
   setOutputDir(settings.default_dir||'./output')
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
   switch(activeSection){
    case'ai-services':
     await saveProviderConfigs(currentProject.id)
     break
    case'auto-approval':
     await saveAutoApproval()
     break
    case'cost':
     await saveCostSettings(currentProject.id)
     break
    case'output':
     await projectSettingsApi.updateOutputSettings(currentProject.id,{default_dir:outputDir})
     break
   }
  }catch(error){
   console.error('Failed to save settings:',error)
  }finally{
   setSaving(false)
  }
 },[currentProject,activeSection,saveProviderConfigs,saveAutoApproval,saveCostSettings,outputDir])

 const handleReset=useCallback(()=>{
  switch(activeSection){
   case'ai-services':
    resetProviderConfigs()
    break
   case'cost':
    resetCostSettings()
    break
  }
 },[activeSection,resetProviderConfigs,resetCostSettings])

 const hasReset=activeSection==='ai-services'||activeSection==='cost'

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
            :'text-nier-text-light hover:bg-nier-bg-panel'
)}
          onClick={()=>setActiveSection(section.id)}
         >
          {section.label}
         </button>
))}
       </div>
       <div className="p-3 border-t border-nier-border-light space-y-2">
        {hasReset&&(
         <Button variant="ghost" size="sm" className="w-full" onClick={handleReset}>
          <RefreshCw size={14}/>
          <span className="ml-1">リセット</span>
         </Button>
)}
        <Button variant="primary" size="sm" className="w-full" onClick={handleSave} disabled={saving}>
         <Save size={14}/>
         <span className="ml-1">{saving?'保存中...':'保存'}</span>
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>

    <div className="flex-1 min-h-0 overflow-y-auto space-y-4">
     {activeSection==='ai-services'&&<AIProviderSettings projectId={currentProject.id}/>}

     {activeSection==='auto-approval'&&<AutoApprovalSettings projectId={currentProject.id}/>}

     {activeSection==='cost'&&<CostSettings projectId={currentProject.id}/>}

     {activeSection==='output'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>出力設定</DiamondMarker>
       </CardHeader>
       <CardContent>
        <div>
         <label className="block text-nier-caption text-nier-text-light mb-1">
          出力ディレクトリ
         </label>
         <div className="flex gap-2">
          <input
           type="text"
           className="flex-1 bg-nier-bg-panel border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
           value={outputDir}
           onChange={(e)=>setOutputDir(e.target.value)}
          />
          <button className="p-2 bg-nier-bg-panel border border-nier-border-light hover:bg-nier-bg-selected transition-colors">
           <FolderOpen size={16}/>
          </button>
         </div>
        </div>
       </CardContent>
      </Card>
)}
    </div>
   </div>
  </div>
)
}
