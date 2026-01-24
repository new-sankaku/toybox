import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Save,FolderOpen}from'lucide-react'
import{AutoApprovalSettings}from'@/components/settings/AutoApprovalSettings'
import{AIProviderSettings}from'@/components/settings/AIProviderSettings'
import{CostSettings}from'@/components/settings/CostSettings'
import{useProjectStore}from'@/stores/projectStore'
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

 const handleSaveOutput=async()=>{
  if(!currentProject)return
  setSaving(true)
  try{
   await projectSettingsApi.updateOutputSettings(currentProject.id,{default_dir:outputDir})
  }catch(error){
   console.error('Failed to save output settings:',error)
  }finally{
   setSaving(false)
  }
 }

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
  <div className="p-4 animate-nier-fade-in">
   <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-start">
    <div>
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
            :'text-nier-text-light hover:bg-nier-bg-panel'
)}
          onClick={()=>setActiveSection(section.id)}
         >
          {section.label}
         </button>
))}
       </div>
      </CardContent>
     </Card>
    </div>

    <div className="md:col-span-3 space-y-4">
     {activeSection==='ai-services'&&<AIProviderSettings projectId={currentProject.id}/>}

     {activeSection==='auto-approval'&&<AutoApprovalSettings projectId={currentProject.id}/>}

     {activeSection==='cost'&&<CostSettings projectId={currentProject.id}/>}

     {activeSection==='output'&&(
      <Card>
       <CardHeader>
        <DiamondMarker>出力設定</DiamondMarker>
       </CardHeader>
       <CardContent>
        <div className="space-y-4">
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
         <div className="flex justify-end">
          <Button variant="primary" size="sm" onClick={handleSaveOutput} disabled={saving}>
           <Save size={14}/>
           <span className="ml-1.5">{saving?'保存中...':'保存'}</span>
          </Button>
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
