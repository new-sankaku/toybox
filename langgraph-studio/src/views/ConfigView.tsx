import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Save,RefreshCw,AlertTriangle,FolderOpen}from'lucide-react'
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
 const[originalOutputDir,setOriginalOutputDir]=useState('./output')
 const[saving,setSaving]=useState(false)
 const[showResetDialog,setShowResetDialog]=useState(false)
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
   await saveProviderConfigs(currentProject.id)
   await saveAutoApproval()
   await saveCostSettings(currentProject.id)
   await projectSettingsApi.updateOutputSettings(currentProject.id,{default_dir:outputDir})
   setOriginalOutputDir(outputDir)
  }catch(error){
   console.error('Failed to save settings:',error)
  }finally{
   setSaving(false)
  }
 },[currentProject,saveProviderConfigs,saveAutoApproval,saveCostSettings,outputDir])

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
         <Button variant="ghost" size="sm" className="w-full" onClick={()=>setShowResetDialog(true)}>
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
    </div>
   </div>

   {/*Reset Confirmation Dialog*/}
   {showResetDialog&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-[90vw] md:max-w-sm lg:max-w-md">
      <CardHeader>
       <div className="flex items-center gap-2 text-nier-text-main">
        <AlertTriangle size={18}/>
        <span>リセットの確認</span>
       </div>
      </CardHeader>
      <CardContent>
       <p className="text-nier-body mb-4">
        {activeSection==='ai-services'?'AIサービス設定':'コスト設定'}をデフォルト値にリセットしますか？
       </p>
       <p className="text-nier-small text-nier-text-main mb-6">
        現在の設定は失われます。
       </p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setShowResetDialog(false)}>
         キャンセル
        </Button>
        <Button
         variant="danger"
         onClick={()=>{
          handleReset()
          setShowResetDialog(false)
         }}
        >
         リセットする
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>
   )}
  </div>
)
}
