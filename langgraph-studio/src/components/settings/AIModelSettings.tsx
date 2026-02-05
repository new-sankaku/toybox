import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{RotateCcw,Save}from'lucide-react'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{
 projectSettingsApi,projectApi,
 type UsageCategorySetting
}from'@/services/apiService'

interface AIModelSettingsProps{
 projectId:string
}

export function AIModelSettings({projectId}:AIModelSettingsProps):JSX.Element{
 const{master,fetchMaster,masterLoaded,getProviderLabel}=useAIServiceStore()
 const[categories,setCategories]=useState<UsageCategorySetting[]>([])
 const[originalCategories,setOriginalCategories]=useState<UsageCategorySetting[]>([])
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState<Record<string,boolean>>({})
 const[savingAll,setSavingAll]=useState(false)

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

 const getChangedCategories=()=>categories.filter(cat=>{
  const original=originalCategories.find(c=>c.id===cat.id)
  return original&&(cat.provider!==original.provider||cat.model!==original.model)
 })

 const handleSaveToProject=async()=>{
  const changed=getChangedCategories()
  if(changed.length===0)return
  setSavingAll(true)
  try{
   for(const cat of changed){
    await projectSettingsApi.updateUsageCategory(projectId,cat.id,{provider:cat.provider,model:cat.model})
   }
   setOriginalCategories(JSON.parse(JSON.stringify(categories)))
  }catch(e){
   console.error('Failed to save:',e)
  }finally{
   setSavingAll(false)
  }
 }

 const handleSaveToAllProjects=async()=>{
  const changed=getChangedCategories()
  if(changed.length===0)return
  setSavingAll(true)
  try{
   const projects=await projectApi.list()
   for(const project of projects){
    for(const cat of changed){
     await projectSettingsApi.updateUsageCategory(project.id,cat.id,{provider:cat.provider,model:cat.model})
    }
   }
   setOriginalCategories(JSON.parse(JSON.stringify(categories)))
  }catch(e){
   console.error('Failed to save to all projects:',e)
  }finally{
   setSavingAll(false)
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
  return<div className="nier-surface-panel text-center py-8">読み込み中...</div>
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
        <div key={cat.id} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 items-center">
         <div>
          <label className="block text-nier-caption text-nier-text-light mb-1">{cat.label}</label>
         </div>
         <div>
          <select
           className={cn(
            'nier-input w-full',
            changed&&'border-nier-accent-orange'
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
            'nier-input w-full',
            changed&&'border-nier-accent-orange'
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
        </div>
       )
      })}
     </CardContent>
    </Card>
   ))}
   {getChangedCategories().length>0&&(
    <div className="flex gap-2 justify-end">
     <Button variant="secondary" size="sm" onClick={handleSaveToProject} disabled={savingAll}>
      <Save size={12}/>
      <span className="ml-1">{savingAll?'保存中...':'このプロジェクトに保存'}</span>
     </Button>
     <Button variant="primary" size="sm" onClick={handleSaveToAllProjects} disabled={savingAll}>
      <Save size={12}/>
      <span className="ml-1">{savingAll?'保存中...':'全てのプロジェクトに保存'}</span>
     </Button>
    </div>
   )}
  </div>
 )
}
