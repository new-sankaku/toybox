import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Save,FolderOpen}from'lucide-react'
import{AutoApprovalSettings}from'@/components/settings/AutoApprovalSettings'
import{useProjectStore}from'@/stores/projectStore'
import{useAutoApprovalStore}from'@/stores/autoApprovalStore'
import{projectSettingsApi}from'@/services/apiService'

interface ConfigSection{
 id:string
 label:string
}

const configSections:ConfigSection[]=[
 {id:'auto-approval',label:'自動承認設定'},
 {id:'output',label:'出力設定'}
]

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
    </div>
   </div>
  </div>
 )
}
