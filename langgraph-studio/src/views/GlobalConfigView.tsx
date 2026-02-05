import{useState,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{FolderOpen,Save}from'lucide-react'
import{
 GlobalCostManagement,
 CostReportPanel,
 AutoApprovalSettings,
 AIModelSettings,
 PrincipleSettings,
 AdvancedSettings,
 ApiKeyManagement,
 DataManagement,
 ExecutionSettings,
 OutputSettings
}from'@/components/settings'
import{useProjectStore}from'@/stores/projectStore'
import{useAutoApprovalStore}from'@/stores/autoApprovalStore'

interface ConfigSection{
 id:string
 label:string
 projectOnly?:boolean
}

const configSections:ConfigSection[]=[
 {id:'auto-approval',label:'自動承認設定',projectOnly:true},
 {id:'execution-settings',label:'AI 同時実行数'},
 {id:'ai-models',label:'AI 使用モデル',projectOnly:true},
 {id:'cost-management',label:'AI コスト管理'},
 {id:'api-keys',label:'AI APIキー管理'},
 {id:'advanced',label:'AI 詳細設定',projectOnly:true},
 {id:'principles',label:'AI Agentプロンプト',projectOnly:true},
 {id:'output',label:'生成結果保存先',projectOnly:true},
 {id:'data-management',label:'データ管理'}
]

export default function GlobalConfigView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{saveToServer:saveAutoApproval,saveToAllProjects:saveAutoApprovalToAll,hasChanges:hasAutoApprovalChanges}=useAutoApprovalStore()
 const[activeSection,setActiveSection]=useState('auto-approval')
 const[saving,setSaving]=useState(false)

 const handleSaveAutoApprovalToProject=useCallback(async()=>{
  if(!currentProject)return
  setSaving(true)
  try{
   await saveAutoApproval()
  }catch(error){
   console.error('Failed to save settings:',error)
  }finally{
   setSaving(false)
  }
 },[currentProject,saveAutoApproval])

 const handleSaveAutoApprovalToAllProjects=useCallback(async()=>{
  setSaving(true)
  try{
   await saveAutoApprovalToAll()
  }catch(error){
   console.error('Failed to save settings:',error)
  }finally{
   setSaving(false)
  }
 },[saveAutoApprovalToAll])

 const renderNoProjectMessage=()=>(
  <Card>
   <CardContent>
    <div className="text-center py-12 text-nier-text-light">
     <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
     <p className="text-nier-body">プロジェクトを選択してください</p>
    </div>
   </CardContent>
  </Card>
 )

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   <div className="flex-1 flex gap-3 overflow-hidden">
    <div className="w-48 flex-shrink-0 flex flex-col overflow-hidden">
     <Card className="flex flex-col overflow-hidden">
      <CardHeader>
       <DiamondMarker>設定</DiamondMarker>
      </CardHeader>
      <CardContent className="p-0 flex-1 overflow-y-auto">
       <div className="divide-y divide-nier-border-light">
        {configSections.map(section=>(
         <button
          key={section.id}
          className={cn(
           'w-full px-4 py-3 text-left text-nier-small tracking-nier transition-colors',
           activeSection===section.id
            ?'nier-surface-selected'
            :'text-nier-text-light hover:bg-nier-bg-panel'
          )}
          onClick={()=>setActiveSection(section.id)}
         >
          {section.label}
         </button>
        ))}
       </div>
      </CardContent>
      {activeSection==='auto-approval'&&currentProject&&hasAutoApprovalChanges()&&(
       <div className="p-3 border-t border-nier-border-light space-y-2">
        <Button variant="secondary" size="sm" className="w-full" onClick={handleSaveAutoApprovalToProject} disabled={saving}>
         <Save size={14}/>
         <span className="ml-1">{saving?'保存中...':'このプロジェクトに保存'}</span>
        </Button>
        <Button variant="primary" size="sm" className="w-full" onClick={handleSaveAutoApprovalToAllProjects} disabled={saving}>
         <Save size={14}/>
         <span className="ml-1">{saving?'保存中...':'全てのプロジェクトに保存'}</span>
        </Button>
       </div>
      )}
     </Card>
    </div>

    <div className="flex-1 min-h-0 overflow-y-auto space-y-4">
     {activeSection==='auto-approval'&&(
      currentProject?<AutoApprovalSettings projectId={currentProject.id}/>:renderNoProjectMessage()
     )}
     {activeSection==='execution-settings'&&<ExecutionSettings/>}
     {activeSection==='ai-models'&&(
      currentProject?<AIModelSettings projectId={currentProject.id}/>:renderNoProjectMessage()
     )}
     {activeSection==='cost-management'&&(
      <div className="space-y-6">
       <GlobalCostManagement/>
       <CostReportPanel/>
      </div>
     )}
     {activeSection==='api-keys'&&<ApiKeyManagement/>}
     {activeSection==='advanced'&&(
      currentProject?<AdvancedSettings projectId={currentProject.id}/>:renderNoProjectMessage()
     )}
     {activeSection==='principles'&&(
      currentProject?<PrincipleSettings projectId={currentProject.id}/>:renderNoProjectMessage()
     )}
     {activeSection==='output'&&(
      currentProject?<OutputSettings projectId={currentProject.id}/>:renderNoProjectMessage()
     )}
     {activeSection==='data-management'&&<DataManagement/>}
    </div>
   </div>
  </div>
 )
}
