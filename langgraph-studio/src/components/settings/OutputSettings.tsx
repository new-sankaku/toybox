import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Save}from'lucide-react'
import{projectSettingsApi,projectApi}from'@/services/apiService'

interface OutputSettingsProps{
 projectId:string
}

export function OutputSettings({projectId}:OutputSettingsProps):JSX.Element{
 const[outputDir,setOutputDir]=useState('./output')
 const[originalOutputDir,setOriginalOutputDir]=useState('./output')
 const[saving,setSaving]=useState(false)
 const outputDirChanged=outputDir!==originalOutputDir

 const loadOutputSettings=useCallback(async()=>{
  try{
   const settings=await projectSettingsApi.getOutputSettings(projectId)
   const dir=settings.default_dir||'./output'
   setOutputDir(dir)
   setOriginalOutputDir(dir)
  }catch(error){
   console.error('Failed to load output settings:',error)
  }
 },[projectId])

 useEffect(()=>{
  loadOutputSettings()
 },[loadOutputSettings])

 const handleSaveToProject=async()=>{
  setSaving(true)
  try{
   await projectSettingsApi.updateOutputSettings(projectId,{default_dir:outputDir})
   setOriginalOutputDir(outputDir)
  }catch(error){
   console.error('Failed to save output settings:',error)
  }finally{
   setSaving(false)
  }
 }

 const handleSaveToAllProjects=async()=>{
  setSaving(true)
  try{
   const projects=await projectApi.list()
   for(const project of projects){
    await projectSettingsApi.updateOutputSettings(project.id,{default_dir:outputDir})
   }
   setOriginalOutputDir(outputDir)
  }catch(error){
   console.error('Failed to save to all projects:',error)
  }finally{
   setSaving(false)
  }
 }

 return(
  <Card>
   <CardHeader>
    <DiamondMarker>生成結果保存先</DiamondMarker>
   </CardHeader>
   <CardContent>
    <div>
     <label className={cn('block text-nier-caption mb-1',outputDirChanged?'text-nier-accent-red':'text-nier-text-light')}>
      出力ディレクトリ
     </label>
     <input
      type="text"
      className={cn(
       'nier-input w-full',
       outputDirChanged&&'border-nier-accent-red text-nier-accent-red'
)}
      value={outputDir}
      onChange={(e)=>setOutputDir(e.target.value)}
     />
    </div>
    {outputDirChanged&&(
     <div className="flex gap-2 justify-end mt-4">
      <Button variant="secondary" size="sm" onClick={handleSaveToProject} disabled={saving}>
       <Save size={12}/>
       <span className="ml-1">{saving?'保存中...':'このプロジェクトに保存'}</span>
      </Button>
      <Button variant="primary" size="sm" onClick={handleSaveToAllProjects} disabled={saving}>
       <Save size={12}/>
       <span className="ml-1">{saving?'保存中...':'全てのプロジェクトに保存'}</span>
      </Button>
     </div>
)}
   </CardContent>
  </Card>
)
}
