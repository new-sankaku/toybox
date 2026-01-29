import{useState,useEffect,useCallback,useMemo}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{AssetFileUploader}from'@/components/project/AssetFileUploader'
import{ProjectList}from'@/components/project/ProjectList'
import{ProjectDetail}from'@/components/project/ProjectDetail'
import{ProjectControls}from'@/components/project/ProjectControls'
import{ProjectFiles}from'@/components/project/ProjectFiles'
import{ConfirmDialog}from'@/components/project/dialogs/ConfirmDialog'
import{BrushupDialog}from'@/components/project/dialogs/BrushupDialog'
import{useProjectStore}from'@/stores/projectStore'
import{useProjectOptionsStore}from'@/stores/projectOptionsStore'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{projectApi,fileUploadApi,extractApiError}from'@/services/apiService'
import type{Project}from'@/types/project'
import type{FileCategory}from'@/types/uploadedFile'
import{cn}from'@/lib/utils'
import{Loader2,Pencil,FolderOpen,Plus,Upload}from'lucide-react'
import{
 type Platform,
 type Scope,
 type ProjectScale,
 type AssetGenerationOptions,
 type ContentPermissions,
 type ContentRatingLevel
}from'@/config/projectOptions'
import{useAgentDefinitionStore}from'@/stores/agentDefinitionStore'
import{useBrushupStore}from'@/stores/brushupStore'

interface SelectedFile{
 file:File
 category:FileCategory
 preview?:string
}

interface UploadedFile{
 id:string
 filename:string
 originalFilename:string
 mimeType:string
 category:string
 sizeBytes:number
 url:string
 uploadedAt:string
}

interface ProjectFormData{
 name:string
 userIdea:string
 references:string
 platform:Platform
 scope:Scope
 scale:ProjectScale
 aiServiceSettings:Record<string,string>
 assetGeneration:AssetGenerationOptions
 contentPermissions:ContentPermissions
}

const getInitialForm=(
 defaults:{platform:string;scope:string;projectTemplate:string}|null,
 projDefaults:{assetGeneration:AssetGenerationOptions;contentPermissions:ContentPermissions}|null
):ProjectFormData=>({
 name:'',
 userIdea:'',
 references:'',
 platform:(defaults?.platform||'') as Platform,
 scope:(defaults?.scope||'') as Scope,
 scale:'' as ProjectScale,
 aiServiceSettings:{},
 assetGeneration:projDefaults?{...projDefaults.assetGeneration}:{enableImageGeneration:false,enableBGMGeneration:false,enableVoiceSynthesis:false,enableVideoGeneration:false},
 contentPermissions:projDefaults?{...projDefaults.contentPermissions}:{violenceLevel:0 as ContentRatingLevel,sexualLevel:0 as ContentRatingLevel}
})

export default function ProjectView():JSX.Element{
 const{currentProject,setCurrentProject,projects,setProjects,incrementDataVersion}=useProjectStore()
 const{platforms,scopes,defaults,scaleOptions,assetServiceOptions,violenceRatingOptions,sexualRatingOptions,projectDefaults,fetchOptions}=useProjectOptionsStore()
 const{master,fetchMaster}=useAIServiceStore()
 const{getFilteredUIPhases,fetchDefinitions,loaded:definitionsLoaded}=useAgentDefinitionStore()
 const brushupStore=useBrushupStore()
 const initialForm=getInitialForm(defaults,projectDefaults)
 const[showNewForm,setShowNewForm]=useState(false)
 const[form,setForm]=useState<ProjectFormData>(initialForm)
 const[selectedFiles,setSelectedFiles]=useState<SelectedFile[]>([])
 const[showInitializeDialog,setShowInitializeDialog]=useState(false)
 const[showBrushupDialog,setShowBrushupDialog]=useState(false)
 const[showDeleteDialog,setShowDeleteDialog]=useState<string|null>(null)
 const[brushupSelectedAgents,setBrushupSelectedAgents]=useState<Set<string>>(new Set())
 const[brushupClearAssets,setBrushupClearAssets]=useState(false)
 const[isLoading,setIsLoading]=useState(false)
 const[uploadProgress,setUploadProgress]=useState<string|null>(null)
 const[error,setError]=useState<string|null>(null)
 const[isEditing,setIsEditing]=useState(false)
 const[editForm,setEditForm]=useState<ProjectFormData>(initialForm)
 const[uploadedFiles,setUploadedFiles]=useState<UploadedFile[]>([])
 const[filesLoading,setFilesLoading]=useState(false)
 const[filesError,setFilesError]=useState<string|null>(null)

 const assetGeneration=currentProject?.config?.assetGeneration as AssetGenerationOptions|undefined
 const brushupPhases=useMemo(()=>getFilteredUIPhases(assetGeneration),[assetGeneration,getFilteredUIPhases])

 const fetchProjects=async()=>{
  setIsLoading(true)
  setError(null)
  try{
   const data=await projectApi.list()
   setProjects(data)
  }catch(err){
   console.error('Failed to fetch projects:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの取得に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const fetchUploadedFiles=useCallback(async(projectId:string)=>{
  setFilesLoading(true)
  try{
   const files=await fileUploadApi.listByProject(projectId)
   setUploadedFiles(files)
  }catch(err){
   console.error('Failed to fetch uploaded files:',err)
   setFilesError(err instanceof Error?err.message:'ファイル一覧の取得に失敗しました')
  }finally{
   setFilesLoading(false)
  }
 },[])

 useEffect(()=>{
  fetchProjects()
  fetchOptions()
  fetchMaster()
  if(!definitionsLoaded)fetchDefinitions()
 },[definitionsLoaded])

 useEffect(()=>{
  if(currentProject){
   fetchUploadedFiles(currentProject.id)
  }else{
   setUploadedFiles([])
  }
 },[currentProject,fetchUploadedFiles])

 useEffect(()=>{
  if(showBrushupDialog){
   brushupStore.fetchOptions()
  }
 },[showBrushupDialog])

 const handleCreateProject=async()=>{
  if(!form.name.trim()||!form.userIdea.trim())return
  setIsLoading(true)
  try{
   const newProject=await projectApi.create({
    name:form.name,
    description:form.userIdea.slice(0,50)+(form.userIdea.length>50?'...':''),
    concept:{
     description:form.userIdea,
     platform:form.platform,
     scope:form.scope,
     references:form.references||undefined
    },
    config:{
     aiServiceSettings:form.aiServiceSettings,
     scale:form.scale,
     assetGeneration:form.assetGeneration,
     contentPermissions:form.contentPermissions
    }
   })
   if(selectedFiles.length>0){
    setUploadProgress(`ファイルをアップロード中... (0/${selectedFiles.length})`)
    const files=selectedFiles.map(sf=>sf.file)
    try{
     const result=await fileUploadApi.uploadBatch(newProject.id,files)
     setUploadProgress(`${result.totalUploaded}ファイルをアップロードしました`)
     if(result.totalErrors>0){
      console.warn('Some files failed to upload:',result.errors)
     }
    }catch(uploadErr){
     console.error('Failed to upload files:',uploadErr)
    }
   }
   setProjects([newProject,...projects])
   setCurrentProject(newProject)
   setForm(initialForm)
   setSelectedFiles([])
   setUploadProgress(null)
   setShowNewForm(false)
  }catch(err){
   console.error('Failed to create project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの作成に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const handleSelectProject=(project:Project)=>{
  if(currentProject?.id!==project.id){
   incrementDataVersion()
  }
  setCurrentProject(project)
 }

 const buildAIServiceDefaults=():Record<string,string>=>{
  if(!master?.usageCategories)return{}
  const result:Record<string,string>={}
  master.usageCategories.forEach(cat=>{
   result[cat.id]=`${cat.default.provider}:${cat.default.model}`
  })
  return result
 }

 const handleEditProjectFromList=(project:Project)=>{
  if(currentProject?.id!==project.id){
   incrementDataVersion()
  }
  setCurrentProject(project)
  setEditForm({
   name:project.name,
   userIdea:project.concept?.description||'',
   references:project.concept?.references||'',
   platform:(project.concept?.platform as Platform)||defaults?.platform||'',
   scope:(project.concept?.scope as Scope)||defaults?.scope||'',
   scale:(project.config?.scale as ProjectScale)||'medium',
   aiServiceSettings:{...buildAIServiceDefaults(),...(project.config?.aiServiceSettings as Record<string,string>||{})},
   assetGeneration:{...(projectDefaults?.assetGeneration||{}),...project.config?.assetGeneration} as AssetGenerationOptions,
   contentPermissions:{
    violenceLevel:(project.config?.contentPermissions?.violenceLevel as ContentRatingLevel)??(projectDefaults?.contentPermissions.violenceLevel??0 as ContentRatingLevel),
    sexualLevel:(project.config?.contentPermissions?.sexualLevel as ContentRatingLevel)??(projectDefaults?.contentPermissions.sexualLevel??0 as ContentRatingLevel)
   }
  })
  setIsEditing(true)
 }

 const handleDeleteProject=async(id:string)=>{
  try{
   await projectApi.delete(id)
   setProjects(projects.filter(p=>p.id!==id))
   if(currentProject?.id===id){
    setCurrentProject(null)
   }
  }catch(err){
   console.error('Failed to delete project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの削除に失敗: ${apiError.message}`)
  }
 }

 const handleStartProject=async()=>{
  if(!currentProject)return
  setIsLoading(true)
  try{
   const updated=await projectApi.start(currentProject.id)
   setProjects(projects.map(p=>p.id===currentProject.id?updated:p))
   setCurrentProject(updated)
  }catch(err){
   console.error('Failed to start project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの開始に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const handleResumeProject=async()=>{
  if(!currentProject)return
  setIsLoading(true)
  try{
   const updated=await projectApi.resume(currentProject.id)
   setProjects(projects.map(p=>p.id===currentProject.id?updated:p))
   setCurrentProject(updated)
  }catch(err){
   console.error('Failed to resume project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの再開に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const handlePauseProject=async()=>{
  if(!currentProject)return
  setIsLoading(true)
  try{
   const updated=await projectApi.pause(currentProject.id)
   setProjects(projects.map(p=>p.id===currentProject.id?updated:p))
   setCurrentProject(updated)
  }catch(err){
   console.error('Failed to pause project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの一時停止に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const handleStopProject=async()=>{
  if(!currentProject)return
  setIsLoading(true)
  try{
   const updated=await projectApi.update(currentProject.id,{status:'draft'})
   setProjects(projects.map(p=>p.id===currentProject.id?updated:p))
   setCurrentProject(updated)
  }catch(err){
   console.error('Failed to stop project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの停止に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const handleInitializeProject=async()=>{
  if(!currentProject)return
  setIsLoading(true)
  try{
   const updated=await projectApi.initialize(currentProject.id)
   incrementDataVersion()
   setProjects(projects.map(p=>p.id===currentProject.id?updated:p))
   setCurrentProject(updated)
   setShowInitializeDialog(false)
  }catch(err){
   console.error('Failed to initialize project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの初期化に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const handleBrushupProject=async()=>{
  if(!currentProject)return
  if(brushupSelectedAgents.size===0){
   setError('少なくとも1つのエージェントを選択してください')
   return
  }
  setIsLoading(true)
  try{
   const options={
    selectedAgents:Array.from(brushupSelectedAgents),
    agentOptions:brushupStore.agentOptions,
    agentInstructions:brushupStore.agentInstructions,
    clearAssets:brushupClearAssets,
    customInstruction:brushupStore.customInstruction,
    referenceImageIds:Array.from(brushupStore.selectedSuggestedImageIds)
   }
   const updated=await projectApi.brushup(currentProject.id,options)
   incrementDataVersion()
   setProjects(projects.map(p=>p.id===currentProject.id?updated:p))
   setCurrentProject(updated)
   setShowBrushupDialog(false)
   setBrushupSelectedAgents(new Set())
   setBrushupClearAssets(false)
   brushupStore.reset()
  }catch(err){
   console.error('Failed to brushup project:',err)
   const apiError=extractApiError(err)
   setError(`ブラッシュアップに失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const toggleBrushupAgent=(agentType:string)=>{
  setBrushupSelectedAgents(prev=>{
   const next=new Set(prev)
   if(next.has(agentType)){
    next.delete(agentType)
   }else{
    next.add(agentType)
   }
   return next
  })
 }

 const toggleBrushupPhase=(agents:string[])=>{
  setBrushupSelectedAgents(prev=>{
   const next=new Set(prev)
   const allSelected=agents.every(a=>prev.has(a))
   if(allSelected){
    agents.forEach(a=>next.delete(a))
   }else{
    agents.forEach(a=>next.add(a))
   }
   return next
  })
 }

 const handleStartEdit=()=>{
  if(!currentProject)return
  setEditForm({
   name:currentProject.name,
   userIdea:currentProject.concept?.description||'',
   references:currentProject.concept?.references||'',
   platform:(currentProject.concept?.platform as Platform)||defaults?.platform||'',
   scope:(currentProject.concept?.scope as Scope)||defaults?.scope||'',
   scale:(currentProject.config?.scale as ProjectScale)||'medium',
   aiServiceSettings:{...buildAIServiceDefaults(),...(currentProject.config?.aiServiceSettings as Record<string,string>||{})},
   assetGeneration:{...(projectDefaults?.assetGeneration||{}),...currentProject.config?.assetGeneration} as AssetGenerationOptions,
   contentPermissions:{
    violenceLevel:(currentProject.config?.contentPermissions?.violenceLevel as ContentRatingLevel)??(projectDefaults?.contentPermissions.violenceLevel??0 as ContentRatingLevel),
    sexualLevel:(currentProject.config?.contentPermissions?.sexualLevel as ContentRatingLevel)??(projectDefaults?.contentPermissions.sexualLevel??0 as ContentRatingLevel)
   }
  })
  setIsEditing(true)
 }

 const handleCancelEdit=()=>{
  setIsEditing(false)
  setEditForm(initialForm)
 }

 const handleSaveEdit=async()=>{
  if(!currentProject||!editForm.name.trim())return
  setIsLoading(true)
  try{
   const updated=await projectApi.update(currentProject.id,{
    name:editForm.name,
    description:editForm.userIdea.slice(0,50)+(editForm.userIdea.length>50?'...':''),
    concept:{
     ...currentProject.concept,
     description:editForm.userIdea,
     platform:editForm.platform,
     scope:editForm.scope,
     references:editForm.references||undefined
    },
    config:{
     ...currentProject.config,
     aiServiceSettings:editForm.aiServiceSettings,
     scale:editForm.scale,
     assetGeneration:editForm.assetGeneration,
     contentPermissions:editForm.contentPermissions
    }
   })
   setProjects(projects.map(p=>p.id===currentProject.id?updated:p))
   setCurrentProject(updated)
   setIsEditing(false)
  }catch(err){
   console.error('Failed to update project:',err)
   const apiError=extractApiError(err)
   setError(`プロジェクトの更新に失敗: ${apiError.message}`)
  }finally{
   setIsLoading(false)
  }
 }

 const handleCloseBrushupDialog=()=>{
  setShowBrushupDialog(false)
  setBrushupSelectedAgents(new Set())
  setBrushupClearAssets(false)
  brushupStore.reset()
 }

 const renderFormFields=(formData:ProjectFormData,setFormData:(data:ProjectFormData)=>void,mode:'create'|'edit')=>(
  <div className="space-y-4">
   <div>
    <label className="block text-nier-small text-nier-text-light mb-1">
     プロジェクト名<span className="text-nier-text-main">*</span>
    </label>
    <input
     type="text"
     value={formData.name}
     onChange={(e)=>setFormData({...formData,name:e.target.value})}
     placeholder="例: NebulaForge"
     className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
    />
   </div>
   <div>
    <label className="block text-nier-small text-nier-text-light mb-1">
     ゲームアイデア{mode==='create'&&<span className="text-nier-text-main">*</span>}
    </label>
    <textarea
     value={formData.userIdea}
     onChange={(e)=>setFormData({...formData,userIdea:e.target.value})}
     placeholder="作りたいゲームのアイデアを自由に記述してください。ジャンル、世界観、ゲームプレイなど..."
     rows={mode==='create'?5:4}
     className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none resize-none"
    />
   </div>
   {mode==='create'&&(
    <div>
     <label className="block text-nier-small text-nier-text-light mb-1">参考ゲーム（カンマ区切り）</label>
     <input
      type="text"
      value={formData.references}
      onChange={(e)=>setFormData({...formData,references:e.target.value})}
      placeholder="例: Astroneer, FTL, Hollow Knight"
      className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
     />
    </div>
)}
   <div>
    <label className="block text-nier-small text-nier-text-light mb-2">プラットフォーム</label>
    <div className="grid grid-cols-3 gap-2">
     {platforms.map((opt)=>(
      <button
       key={opt.value}
       type="button"
       onClick={()=>setFormData({...formData,platform:opt.value})}
       className={cn('p-2 border text-left transition-colors',formData.platform===opt.value?'border-nier-accent-gold bg-nier-bg-selected':'border-nier-border-light hover:bg-nier-bg-hover')}
      >
       <div className="text-nier-small font-medium">{opt.label}</div>
       <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
      </button>
))}
    </div>
   </div>
   <div>
    <label className="block text-nier-small text-nier-text-light mb-2">スコープ</label>
    <div className="grid grid-cols-4 gap-2">
     {scopes.map((opt)=>(
      <button
       key={opt.value}
       type="button"
       onClick={()=>setFormData({...formData,scope:opt.value})}
       className={cn('p-2 border text-left transition-colors',formData.scope===opt.value?'border-nier-accent-gold bg-nier-bg-selected':'border-nier-border-light hover:bg-nier-bg-hover')}
      >
       <div className="text-nier-small font-medium">{opt.label}</div>
       <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
      </button>
))}
    </div>
   </div>
   {mode==='create'&&(
    <div>
     <label className="block text-nier-small text-nier-text-light mb-2">プロジェクト規模</label>
     <div className="grid grid-cols-3 gap-2">
      {scaleOptions.map((opt)=>(
       <button
        key={opt.value}
        type="button"
        onClick={()=>setFormData({...formData,scale:opt.value})}
        className={cn('p-2 border text-left transition-colors',formData.scale===opt.value?'border-nier-accent-gold bg-nier-bg-selected':'border-nier-border-light hover:bg-nier-bg-hover')}
       >
        <div className="text-nier-small font-medium">{opt.label}</div>
        <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
        <div className="text-nier-caption text-nier-text-light">{opt.estimatedHours}</div>
       </button>
))}
     </div>
    </div>
)}
   <div>
    <label className="block text-nier-small text-nier-text-light mb-2">アセット自動生成</label>
    <div className="grid grid-cols-2 gap-2">
     {assetServiceOptions.map((opt)=>(
      <label key={opt.key} className="flex items-center gap-2 p-2 border border-nier-border-light hover:bg-nier-bg-hover cursor-pointer">
       <input
        type="checkbox"
        checked={formData.assetGeneration[opt.key]}
        onChange={(e)=>setFormData({...formData,assetGeneration:{...formData.assetGeneration,[opt.key]:e.target.checked}})}
        className="w-4 h-4"
       />
       <div className="flex-1">
        <span className="text-nier-small">{opt.label}</span>
        <span className="text-nier-caption text-nier-text-light ml-2">{opt.service}</span>
       </div>
      </label>
))}
    </div>
    {mode==='create'&&<p className="text-nier-caption text-nier-text-light mt-1">使用するにはConfigタブでサービス設定が必要です</p>}
   </div>
   {master&&master.usageCategories&&(
    <div>
     <label className="block text-nier-small text-nier-text-light mb-2">AI サービス設定</label>
     <div className="space-y-2">
      {master.usageCategories.map((cat)=>{
       const providers=Object.entries(master.providers||{}).filter(([,p])=>p.serviceTypes.includes(cat.service_type))
       const defaultValue=`${cat.default.provider}:${cat.default.model}`
       const isDisabled=(cat.service_type==='image'&&!formData.assetGeneration.enableImageGeneration)||(cat.service_type==='music'&&!formData.assetGeneration.enableBGMGeneration)||(cat.service_type==='audio'&&!formData.assetGeneration.enableVoiceSynthesis)
       return(
        <div key={cat.id} className="flex items-center gap-3">
         <label className={cn('w-44 text-nier-small flex-shrink-0',isDisabled?'text-nier-text-light/50':'text-nier-text-light')}>{cat.label}</label>
         <select
          value={formData.aiServiceSettings[cat.id]||defaultValue}
          onChange={(e)=>setFormData({...formData,aiServiceSettings:{...formData.aiServiceSettings,[cat.id]:e.target.value}})}
          disabled={isDisabled}
          className={cn('flex-1 px-2 py-1 bg-nier-bg-main border border-nier-border-light text-nier-small focus:border-nier-accent-gold focus:outline-none',isDisabled&&'opacity-50 cursor-not-allowed')}
         >
          {providers.flatMap(([providerId,provider])=>{
           if(providerId.startsWith('local-')){
            return[<option key={providerId} value={`${providerId}:${provider.defaultModel}`}>{provider.label}</option>]
           }
           return provider.models.map((model)=>(<option key={`${providerId}:${model.id}`} value={`${providerId}:${model.id}`}>{model.label}</option>))
          })}
         </select>
        </div>
)
      })}
     </div>
    </div>
)}
   {violenceRatingOptions.length>0&&sexualRatingOptions.length>0&&(
    <div>
     <label className="block text-nier-small text-nier-text-light mb-2">コンテンツレーティング</label>
     <div className="grid grid-cols-2 gap-3">
      <div className="p-2 border border-nier-border-light">
       <div className="flex items-center justify-between mb-1">
        <span className="text-nier-small text-nier-text-main">暴力表現</span>
        <span className="text-nier-small text-nier-text-main">{violenceRatingOptions[formData.contentPermissions.violenceLevel]?.age??''}</span>
       </div>
       <input type="range" min={0} max={4} value={formData.contentPermissions.violenceLevel} onChange={(e)=>setFormData({...formData,contentPermissions:{...formData.contentPermissions,violenceLevel:Number(e.target.value) as ContentRatingLevel}})} className="nier-slider"/>
       <p className="text-nier-caption text-nier-text-light mt-1">{violenceRatingOptions[formData.contentPermissions.violenceLevel]?.description??''}</p>
      </div>
      <div className="p-2 border border-nier-border-light">
       <div className="flex items-center justify-between mb-1">
        <span className="text-nier-small text-nier-text-main">性表現</span>
        <span className="text-nier-small text-nier-text-main">{sexualRatingOptions[formData.contentPermissions.sexualLevel]?.age??''}</span>
       </div>
       <input type="range" min={0} max={4} value={formData.contentPermissions.sexualLevel} onChange={(e)=>setFormData({...formData,contentPermissions:{...formData.contentPermissions,sexualLevel:Number(e.target.value) as ContentRatingLevel}})} className="nier-slider"/>
       <p className="text-nier-caption text-nier-text-light mt-1">{sexualRatingOptions[formData.contentPermissions.sexualLevel]?.description??''}</p>
      </div>
     </div>
    </div>
)}
  </div>
)

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   {error&&(
    <div className="mb-4 p-3 nier-surface-panel border border-nier-border-dark text-nier-small flex-shrink-0">
     {error}
     <button onClick={()=>setError(null)} className="ml-2 underline hover:no-underline">閉じる</button>
    </div>
)}

   <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-3 overflow-hidden">
    <div className="lg:col-span-1 flex flex-col overflow-hidden">
     <ProjectList
      projects={projects}
      currentProject={currentProject}
      isLoading={isLoading}
      onSelectProject={handleSelectProject}
      onEditProject={handleEditProjectFromList}
      onDeleteProject={(id)=>setShowDeleteDialog(id)}
      onRefresh={fetchProjects}
      onNewProject={()=>setShowNewForm(true)}
     />
    </div>

    <div className="lg:col-span-2 overflow-y-auto">
     {showNewForm?(
      <Card>
       <CardHeader><DiamondMarker>新規プロジェクト作成</DiamondMarker></CardHeader>
       <CardContent>
        {renderFormFields(form,setForm,'create')}
        <div className="mt-4">
         <label className="block text-nier-small text-nier-text-light mb-1">
          <Upload size={14} className="inline mr-1"/>初期ファイル（オプション）
         </label>
         <p className="text-nier-caption text-nier-text-light mb-2">カテゴリごとにファイルをアップロードできます</p>
         <AssetFileUploader files={selectedFiles} onFilesChange={setSelectedFiles} disabled={isLoading}/>
        </div>
        {uploadProgress&&<div className="text-nier-small text-nier-accent-gold mt-4">{uploadProgress}</div>}
        <div className="flex gap-3 pt-4">
         <Button onClick={handleCreateProject} disabled={!form.name.trim()||!form.userIdea.trim()||isLoading}>
          {isLoading&&<Loader2 size={14} className="mr-1.5 animate-spin"/>}作成
         </Button>
         <Button variant="secondary" onClick={()=>setShowNewForm(false)}>キャンセル</Button>
        </div>
       </CardContent>
      </Card>
):currentProject?(
      <div className="space-y-3">
       <Card>
        <CardHeader>
         <div className="flex items-center justify-between w-full">
          <DiamondMarker>プロジェクト詳細</DiamondMarker>
          {!isEditing&&currentProject.status!=='running'&&(
           <button onClick={handleStartEdit} className="p-1.5 hover:bg-nier-bg-selected transition-colors" title="編集"><Pencil size={16}/></button>
)}
         </div>
        </CardHeader>
        <CardContent>
         {isEditing?(
          <>
           {renderFormFields(editForm,setEditForm,'edit')}
           <div className="flex gap-3 pt-4">
            <Button onClick={handleSaveEdit} disabled={!editForm.name.trim()||isLoading}>
             {isLoading&&<Loader2 size={14} className="mr-1.5 animate-spin"/>}保存
            </Button>
            <Button variant="secondary" onClick={handleCancelEdit}>キャンセル</Button>
           </div>
          </>
):(
          <ProjectDetail project={currentProject}/>
)}
        </CardContent>
       </Card>
       <ProjectControls
        project={currentProject}
        isLoading={isLoading}
        onStart={handleStartProject}
        onResume={handleResumeProject}
        onPause={handlePauseProject}
        onStop={handleStopProject}
        onBrushup={()=>setShowBrushupDialog(true)}
        onInitialize={()=>setShowInitializeDialog(true)}
       />
       <ProjectFiles files={uploadedFiles} isLoading={filesLoading} error={filesError}/>
      </div>
):(
      <Card>
       <CardContent>
        <div className="text-center py-12 text-nier-text-light">
         <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
         <p className="text-nier-body mb-4">プロジェクトを選択するか、新規作成してください</p>
         <Button onClick={()=>setShowNewForm(true)}><Plus size={14} className="mr-1.5"/>新規プロジェクト作成</Button>
        </div>
       </CardContent>
      </Card>
)}
    </div>
   </div>

   {showInitializeDialog&&currentProject&&(
    <ConfirmDialog
     title="初期化の確認"
     message={`プロジェクト「${currentProject.name}」を初期化しますか？`}
     subMessage="すべての進捗状況とエージェント出力がリセットされます。この操作は取り消せません。"
     confirmLabel="初期化する"
     onConfirm={handleInitializeProject}
     onCancel={()=>setShowInitializeDialog(false)}
     isLoading={isLoading}
     variant="danger"
    />
)}

   {showDeleteDialog&&(
    <ConfirmDialog
     title="削除の確認"
     message={`プロジェクト「${projects.find(p=>p.id===showDeleteDialog)?.name}」を削除しますか？`}
     subMessage="この操作は取り消せません。"
     confirmLabel="削除する"
     onConfirm={()=>{
      handleDeleteProject(showDeleteDialog)
      setShowDeleteDialog(null)
     }}
     onCancel={()=>setShowDeleteDialog(null)}
     isLoading={isLoading}
     variant="danger"
    />
)}

   {showBrushupDialog&&currentProject&&(
    <BrushupDialog
     phases={brushupPhases}
     selectedAgents={brushupSelectedAgents}
     clearAssets={brushupClearAssets}
     isLoading={isLoading}
     onToggleAgent={toggleBrushupAgent}
     onTogglePhase={toggleBrushupPhase}
     onToggleClearAssets={()=>setBrushupClearAssets(!brushupClearAssets)}
     onSubmit={handleBrushupProject}
     onClose={handleCloseBrushupDialog}
    />
)}
  </div>
)
}
