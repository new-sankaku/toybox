import{useState,useEffect,useCallback,useMemo}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{AssetFileUploader}from'@/components/project/AssetFileUploader'
import{useProjectStore}from'@/stores/projectStore'
import{useProjectOptionsStore}from'@/stores/projectOptionsStore'
import{useAIServiceStore}from'@/stores/aiServiceStore'
import{projectApi,fileUploadApi,extractApiError}from'@/services/apiService'
import type{Project,ProjectStatus}from'@/types/project'
import type{FileCategory}from'@/types/uploadedFile'
import{cn}from'@/lib/utils'
import{Play,Pause,Square,Trash2,Plus,FolderOpen,RotateCcw,AlertTriangle,Loader2,RefreshCw,Pencil,X,Check,Upload,FileText,Image,Music,File}from'lucide-react'
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
import{BrushupReferenceImages}from'@/components/brushup'

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

interface NewProjectForm{
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
):NewProjectForm=>({
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

const statusLabels:Record<ProjectStatus,string>={
 draft:'下書き',
 running:'実行中',
 paused:'一時停止',
 completed:'完了',
 failed:'エラー'
}

const statusColors:Record<ProjectStatus,string>={
 draft:'text-nier-text-light',
 running:'text-nier-accent-orange',
 paused:'text-nier-accent-yellow',
 completed:'text-nier-accent-green',
 failed:'text-nier-accent-red'
}

export default function ProjectView():JSX.Element{
 const{currentProject,setCurrentProject,projects,setProjects,incrementDataVersion}=useProjectStore()
 const{platforms,scopes,defaults,scaleOptions,assetServiceOptions,violenceRatingOptions,sexualRatingOptions,projectDefaults,fetchOptions}=useProjectOptionsStore()
 const{master,fetchMaster}=useAIServiceStore()
 const{getLabel:getAgentLabel,getFilteredUIPhases,fetchDefinitions,loaded:definitionsLoaded}=useAgentDefinitionStore()
 const brushupStore=useBrushupStore()
 const initialForm=getInitialForm(defaults,projectDefaults)
 const[showNewForm,setShowNewForm]=useState(false)
 const[form,setForm]=useState<NewProjectForm>(initialForm)
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
 const[editForm,setEditForm]=useState<NewProjectForm>(initialForm)
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
    description:form.userIdea.slice(0,50)+(form.userIdea.length>50?'...' : ''),
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
   assetGeneration:{...(projectDefaults?.assetGeneration||{}),...project.config?.assetGeneration},
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
   setProjects(projects.map(p=>p.id===currentProject.id?updated : p))
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
   setProjects(projects.map(p=>p.id===currentProject.id?updated : p))
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
   setProjects(projects.map(p=>p.id===currentProject.id?updated : p))
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
   setProjects(projects.map(p=>p.id===currentProject.id?updated : p))
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
   setProjects(projects.map(p=>p.id===currentProject.id?updated : p))
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

 const canInitialize=currentProject&&(currentProject.status!=='draft'||currentProject.currentPhase>1)
 const canBrushup=currentProject?.status==='completed'

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
    clearAssets:brushupClearAssets,
    customInstruction:brushupStore.customInstruction,
    referenceImageIds:Array.from(brushupStore.selectedSuggestedImageIds)
   }
   const updated=await projectApi.brushup(currentProject.id,options)
   incrementDataVersion()
   setProjects(projects.map(p=>p.id===currentProject.id?updated : p))
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
   assetGeneration:{...(projectDefaults?.assetGeneration||{}),...currentProject.config?.assetGeneration},
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
    description:editForm.userIdea.slice(0,50)+(editForm.userIdea.length>50?'...' : ''),
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
   setProjects(projects.map(p=>p.id===currentProject.id?updated : p))
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

 return(
  <div className="p-4 animate-nier-fade-in h-full flex flex-col overflow-hidden">
   {/*Error Message*/}
   {error&&(
    <div className="mb-4 p-3 bg-nier-bg-panel border border-nier-border-dark text-nier-text-main text-nier-small flex-shrink-0">
     {error}
     <button
      onClick={()=>setError(null)}
      className="ml-2 underline hover:no-underline"
     >
      閉じる
     </button>
    </div>
)}

   <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-3 overflow-hidden">
    {/*Left: Project List*/}
    <div className="lg:col-span-1 flex flex-col overflow-hidden">
     <Card className="flex flex-col overflow-hidden">
      <CardHeader>
       <div className="flex items-center justify-between w-full">
        <DiamondMarker>プロジェクト一覧</DiamondMarker>
        <div className="flex items-center gap-1">
         <button
          onClick={fetchProjects}
          className="p-1.5 hover:bg-nier-bg-selected transition-colors"
          title="更新"
          disabled={isLoading}
         >
          <RefreshCw size={16} className={isLoading?'animate-spin' : ''}/>
         </button>
         <button
          onClick={()=>setShowNewForm(true)}
          className="p-1.5 hover:bg-nier-bg-selected transition-colors"
          title="新規作成"
         >
          <Plus size={16}/>
         </button>
        </div>
       </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
       {isLoading&&projects.length===0?(
        <div className="text-center text-nier-text-light py-8">
         <Loader2 size={24} className="mx-auto mb-2 animate-spin"/>
         読み込み中...
        </div>
) : projects.length===0?(
        <div className="text-center text-nier-text-light py-8">
         プロジェクトがありません
        </div>
) : (
        <div className="space-y-2">
         {projects.map((project)=>(
          <div
           key={project.id}
           onClick={()=>handleSelectProject(project)}
           className={cn(
            'p-3 border cursor-pointer transition-colors',
            currentProject?.id===project.id
             ?'border-nier-border-light bg-nier-bg-selected'
             : 'border-nier-border-light hover:bg-nier-bg-hover'
)}
          >
           <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
             <div className="text-nier-small font-medium truncate">
              {project.name}
             </div>
             <div className="text-nier-caption text-nier-text-light truncate mt-0.5">
              {project.description}
             </div>
            </div>
            <div className="flex items-center gap-2 ml-2">
             <span className={cn('text-nier-caption',statusColors[project.status])}>
              {statusLabels[project.status]}
             </span>
             <button
              onClick={(e)=>{
               e.stopPropagation()
               handleEditProjectFromList(project)
              }}
              className="p-1 hover:bg-nier-bg-main transition-colors text-nier-text-light hover:text-nier-accent-gold"
              title="編集"
             >
              <Pencil size={12}/>
             </button>
             <button
              onClick={(e)=>{
               e.stopPropagation()
               setShowDeleteDialog(project.id)
              }}
              className="p-1 hover:bg-nier-bg-main transition-colors text-nier-text-light hover:text-nier-text-main"
              title="削除"
             >
              <Trash2 size={12}/>
             </button>
            </div>
           </div>
           <div className="text-nier-caption text-nier-text-light mt-1">
            Phase {project.currentPhase}
           </div>
          </div>
))}
        </div>
)}
      </CardContent>
     </Card>
    </div>

    {/*Right: New Project Form or Project Details*/}
    <div className="lg:col-span-2 overflow-y-auto">
     {showNewForm?(
      <Card>
       <CardHeader>
        <DiamondMarker>新規プロジェクト作成</DiamondMarker>
       </CardHeader>
       <CardContent>
        <div className="space-y-4">
         {/*Project Name*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-1">
           プロジェクト名<span className="text-nier-text-main">*</span>
          </label>
          <input
           type="text"
           value={form.name}
           onChange={(e)=>setForm({...form,name:e.target.value})}
           placeholder="例: NebulaForge"
           className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
          />
         </div>

         {/*User Idea*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-1">
           ゲームアイデア<span className="text-nier-text-main">*</span>
          </label>
          <textarea
           value={form.userIdea}
           onChange={(e)=>setForm({...form,userIdea:e.target.value})}
           placeholder="作りたいゲームのアイデアを自由に記述してください。ジャンル、世界観、ゲームプレイなど..."
           rows={5}
           className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none resize-none"
          />
         </div>

         {/*References*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-1">
           参考ゲーム（カンマ区切り）
          </label>
          <input
           type="text"
           value={form.references}
           onChange={(e)=>setForm({...form,references:e.target.value})}
           placeholder="例: Astroneer, FTL, Hollow Knight"
           className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
          />
         </div>

         {/*Platform Selection*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           プラットフォーム
          </label>
          <div className="grid grid-cols-3 gap-2">
           {platforms.map((opt)=>(
            <button
             key={opt.value}
             type="button"
             onClick={()=>setForm({...form,platform:opt.value})}
             className={cn(
              'p-2 border text-left transition-colors',
              form.platform===opt.value
               ?'border-nier-accent-gold bg-nier-bg-selected'
               : 'border-nier-border-light hover:bg-nier-bg-hover'
)}
            >
             <div className="text-nier-small font-medium">{opt.label}</div>
             <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
            </button>
))}
          </div>
         </div>

         {/*Scope Selection*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           スコープ
          </label>
          <div className="grid grid-cols-4 gap-2">
           {scopes.map((opt)=>(
            <button
             key={opt.value}
             type="button"
             onClick={()=>setForm({...form,scope:opt.value})}
             className={cn(
              'p-2 border text-left transition-colors',
              form.scope===opt.value
               ?'border-nier-accent-gold bg-nier-bg-selected'
               : 'border-nier-border-light hover:bg-nier-bg-hover'
)}
            >
             <div className="text-nier-small font-medium">{opt.label}</div>
             <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
            </button>
))}
          </div>
         </div>

         {/*Project Scale Selection*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           プロジェクト規模
          </label>
          <div className="grid grid-cols-3 gap-2">
           {scaleOptions.map((opt)=>(
            <button
             key={opt.value}
             type="button"
             onClick={()=>setForm({...form,scale:opt.value})}
             className={cn(
              'p-2 border text-left transition-colors',
              form.scale===opt.value
               ?'border-nier-accent-gold bg-nier-bg-selected'
               : 'border-nier-border-light hover:bg-nier-bg-hover'
)}
            >
             <div className="text-nier-small font-medium">{opt.label}</div>
             <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
             <div className="text-nier-caption text-nier-text-light">{opt.estimatedHours}</div>
            </button>
))}
          </div>
         </div>

         {/*Asset Generation Options*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           アセット自動生成
          </label>
          <div className="grid grid-cols-2 gap-2">
           {assetServiceOptions.map((opt)=>(
            <label
             key={opt.key}
             className="flex items-center gap-2 p-2 border border-nier-border-light hover:bg-nier-bg-hover cursor-pointer"
            >
             <input
              type="checkbox"
              checked={form.assetGeneration[opt.key]}
              onChange={(e)=>setForm({
               ...form,
               assetGeneration:{...form.assetGeneration,[opt.key]:e.target.checked}
              })}
              className="w-4 h-4"
             />
             <div className="flex-1">
              <span className="text-nier-small">{opt.label}</span>
              <span className="text-nier-caption text-nier-text-light ml-2">{opt.service}</span>
             </div>
            </label>
))}
          </div>
          <p className="text-nier-caption text-nier-text-light mt-1">
           使用するにはConfigタブでサービス設定が必要です
          </p>
         </div>

         {/*AI Service Settings*/}
         {master&&master.usageCategories&&(
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           AI サービス設定
          </label>
          <div className="space-y-2">
           {master.usageCategories.map((cat)=>{
            const providers=Object.entries(master.providers||{}).filter(
             ([,p])=>p.serviceTypes.includes(cat.service_type)
)
            const defaultValue=`${cat.default.provider}:${cat.default.model}`
            const isDisabled=
             (cat.service_type==='image'&&!form.assetGeneration.enableImageGeneration)||
             (cat.service_type==='music'&&!form.assetGeneration.enableBGMGeneration)||
             (cat.service_type==='audio'&&!form.assetGeneration.enableVoiceSynthesis)
            return(
            <div key={cat.id} className="flex items-center gap-3">
             <label className={cn('w-44 text-nier-small flex-shrink-0',isDisabled?'text-nier-text-light/50':'text-nier-text-light')}>
              {cat.label}
             </label>
             <select
              value={form.aiServiceSettings[cat.id]||defaultValue}
              onChange={(e)=>setForm({
               ...form,
               aiServiceSettings:{...form.aiServiceSettings,[cat.id]:e.target.value}
              })}
              disabled={isDisabled}
              className={cn('flex-1 px-2 py-1 bg-nier-bg-main border border-nier-border-light text-nier-small focus:border-nier-accent-gold focus:outline-none',isDisabled&&'opacity-50 cursor-not-allowed')}
             >
              {providers.flatMap(([providerId,provider])=>{
               if(providerId.startsWith('local-')){
                return[
                 <option key={providerId} value={`${providerId}:${provider.defaultModel}`}>
                  {provider.label}
                 </option>
]
               }
               return provider.models.map((model)=>(
                <option key={`${providerId}:${model.id}`} value={`${providerId}:${model.id}`}>
                 {model.label}
                </option>
))
              })}
             </select>
            </div>
)
           })}
          </div>
         </div>
)}

         {/*Content Permissions*/}
         {violenceRatingOptions.length>0&&sexualRatingOptions.length>0&&(
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           コンテンツレーティング
          </label>
          <div className="grid grid-cols-2 gap-3">
           <div className="p-2 border border-nier-border-light">
            <div className="flex items-center justify-between mb-1">
             <span className="text-nier-small text-nier-text-main">暴力表現</span>
             <span className="text-nier-small text-nier-text-main">{violenceRatingOptions[form.contentPermissions.violenceLevel]?.age??''}</span>
            </div>
            <input
             type="range"
             min={0}
             max={4}
             value={form.contentPermissions.violenceLevel}
             onChange={(e)=>setForm({
              ...form,
              contentPermissions:{...form.contentPermissions,violenceLevel:Number(e.target.value) as ContentRatingLevel}
             })}
             className="nier-slider"
            />
            <p className="text-nier-caption text-nier-text-light mt-1">{violenceRatingOptions[form.contentPermissions.violenceLevel]?.description??''}</p>
           </div>
           <div className="p-2 border border-nier-border-light">
            <div className="flex items-center justify-between mb-1">
             <span className="text-nier-small text-nier-text-main">性表現</span>
             <span className="text-nier-small text-nier-text-main">{sexualRatingOptions[form.contentPermissions.sexualLevel]?.age??''}</span>
            </div>
            <input
             type="range"
             min={0}
             max={4}
             value={form.contentPermissions.sexualLevel}
             onChange={(e)=>setForm({
              ...form,
              contentPermissions:{...form.contentPermissions,sexualLevel:Number(e.target.value) as ContentRatingLevel}
             })}
             className="nier-slider"
            />
            <p className="text-nier-caption text-nier-text-light mt-1">{sexualRatingOptions[form.contentPermissions.sexualLevel]?.description??''}</p>
           </div>
          </div>
         </div>
)}

         {/*Initial Files*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-1">
           <Upload size={14} className="inline mr-1"/>
           初期ファイル（オプション）
          </label>
          <p className="text-nier-caption text-nier-text-light mb-2">
           カテゴリごとにファイルをアップロードできます
          </p>
          <AssetFileUploader
           files={selectedFiles}
           onFilesChange={setSelectedFiles}
           disabled={isLoading}
          />
         </div>

         {/*Upload Progress*/}
         {uploadProgress&&(
          <div className="text-nier-small text-nier-accent-gold">
           {uploadProgress}
          </div>
)}

         {/*Buttons*/}
         <div className="flex gap-3 pt-2">
          <Button onClick={handleCreateProject} disabled={!form.name.trim()||!form.userIdea.trim()||isLoading}>
           {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>: null}
           作成
          </Button>
          <Button variant="secondary" onClick={()=>setShowNewForm(false)}>
           キャンセル
          </Button>
         </div>
        </div>
       </CardContent>
      </Card>
) : currentProject?(
      <div className="space-y-3">
       {/*Project Info*/}
       <Card>
        <CardHeader>
         <div className="flex items-center justify-between w-full">
          <DiamondMarker>プロジェクト詳細</DiamondMarker>
          {!isEditing&&currentProject.status!=='running'&&(
           <button
            onClick={handleStartEdit}
            className="p-1.5 hover:bg-nier-bg-selected transition-colors"
            title="編集"
           >
            <Pencil size={16}/>
           </button>
)}
         </div>
        </CardHeader>
        <CardContent>
         {isEditing?(
          <div className="space-y-4">
           {/*Project Name*/}
           <div>
            <label className="block text-nier-small text-nier-text-light mb-1">
             プロジェクト名<span className="text-nier-text-main">*</span>
            </label>
            <input
             type="text"
             value={editForm.name}
             onChange={(e)=>setEditForm({...editForm,name:e.target.value})}
             className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
            />
           </div>

           {/*User Idea*/}
           <div>
            <label className="block text-nier-small text-nier-text-light mb-1">
             ゲームアイデア
            </label>
            <textarea
             value={editForm.userIdea}
             onChange={(e)=>setEditForm({...editForm,userIdea:e.target.value})}
             rows={4}
             className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none resize-none"
            />
           </div>

           {/*Platform Selection*/}
           <div>
            <label className="block text-nier-small text-nier-text-light mb-2">
             プラットフォーム
            </label>
            <div className="grid grid-cols-3 gap-2">
             {platforms.map((opt)=>(
              <button
               key={opt.value}
               type="button"
               onClick={()=>setEditForm({...editForm,platform:opt.value})}
               className={cn(
                'p-2 border text-left transition-colors',
                editForm.platform===opt.value
                 ?'border-nier-accent-gold bg-nier-bg-selected'
                 : 'border-nier-border-light hover:bg-nier-bg-hover'
)}
              >
               <div className="text-nier-small font-medium">{opt.label}</div>
               <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
              </button>
))}
            </div>
           </div>

           {/*Scope Selection*/}
           <div>
            <label className="block text-nier-small text-nier-text-light mb-2">
             スコープ
            </label>
            <div className="grid grid-cols-4 gap-2">
             {scopes.map((opt)=>(
              <button
               key={opt.value}
               type="button"
               onClick={()=>setEditForm({...editForm,scope:opt.value})}
               className={cn(
                'p-2 border text-left transition-colors',
                editForm.scope===opt.value
                 ?'border-nier-accent-gold bg-nier-bg-selected'
                 : 'border-nier-border-light hover:bg-nier-bg-hover'
)}
              >
               <div className="text-nier-small font-medium">{opt.label}</div>
               <div className="text-nier-caption text-nier-text-light">{opt.description}</div>
              </button>
))}
            </div>
           </div>

           {/*Asset Generation Options*/}
           <div>
            <label className="block text-nier-small text-nier-text-light mb-2">
             アセット自動生成
            </label>
            <div className="grid grid-cols-2 gap-2">
             {assetServiceOptions.map((opt)=>(
              <label
               key={opt.key}
               className="flex items-center gap-2 p-2 border border-nier-border-light hover:bg-nier-bg-hover cursor-pointer"
              >
               <input
                type="checkbox"
                checked={editForm.assetGeneration[opt.key]}
                onChange={(e)=>setEditForm({
                 ...editForm,
                 assetGeneration:{...editForm.assetGeneration,[opt.key]:e.target.checked}
                })}
                className="w-4 h-4"
               />
               <div className="flex-1">
                <span className="text-nier-small">{opt.label}</span>
                <span className="text-nier-caption text-nier-text-light ml-2">{opt.service}</span>
               </div>
              </label>
))}
            </div>
           </div>

           {/*AI Service Settings*/}
           {master&&master.usageCategories&&(
           <div>
            <label className="block text-nier-small text-nier-text-light mb-2">
             AI サービス設定
            </label>
            <div className="space-y-2">
             {master.usageCategories.map((cat)=>{
              const providers=Object.entries(master.providers||{}).filter(
               ([,p])=>p.serviceTypes.includes(cat.service_type)
)
              const defaultValue=`${cat.default.provider}:${cat.default.model}`
              const isDisabled=
               (cat.service_type==='image'&&!editForm.assetGeneration.enableImageGeneration)||
               (cat.service_type==='music'&&!editForm.assetGeneration.enableBGMGeneration)||
               (cat.service_type==='audio'&&!editForm.assetGeneration.enableVoiceSynthesis)
              return(
              <div key={cat.id} className="flex items-center gap-3">
               <label className={cn('w-44 text-nier-small flex-shrink-0',isDisabled?'text-nier-text-light/50':'text-nier-text-light')}>
                {cat.label}
               </label>
               <select
                value={editForm.aiServiceSettings[cat.id]||defaultValue}
                onChange={(e)=>setEditForm({
                 ...editForm,
                 aiServiceSettings:{...editForm.aiServiceSettings,[cat.id]:e.target.value}
                })}
                disabled={isDisabled}
                className={cn('flex-1 px-2 py-1 bg-nier-bg-main border border-nier-border-light text-nier-small focus:border-nier-accent-gold focus:outline-none',isDisabled&&'opacity-50 cursor-not-allowed')}
               >
                {providers.flatMap(([providerId,provider])=>{
                 if(providerId.startsWith('local-')){
                  return[
                   <option key={providerId} value={`${providerId}:${provider.defaultModel}`}>
                    {provider.label}
                   </option>
]
                 }
                 return provider.models.map((model)=>(
                  <option key={`${providerId}:${model.id}`} value={`${providerId}:${model.id}`}>
                   {model.label}
                  </option>
))
                })}
               </select>
              </div>
)
             })}
            </div>
           </div>
)}

           {/*Content Permissions*/}
           {violenceRatingOptions.length>0&&sexualRatingOptions.length>0&&(
           <div>
            <label className="block text-nier-small text-nier-text-light mb-2">
             コンテンツレーティング
            </label>
            <div className="grid grid-cols-2 gap-3">
             <div className="p-2 border border-nier-border-light">
              <div className="flex items-center justify-between mb-1">
               <span className="text-nier-small text-nier-text-main">暴力表現</span>
               <span className="text-nier-small text-nier-text-main">{violenceRatingOptions[editForm.contentPermissions.violenceLevel]?.age??''}</span>
              </div>
              <input
               type="range"
               min={0}
               max={4}
               value={editForm.contentPermissions.violenceLevel}
               onChange={(e)=>setEditForm({
                ...editForm,
                contentPermissions:{...editForm.contentPermissions,violenceLevel:Number(e.target.value) as ContentRatingLevel}
               })}
               className="nier-slider"
              />
              <p className="text-nier-caption text-nier-text-light mt-1">{violenceRatingOptions[editForm.contentPermissions.violenceLevel]?.description??''}</p>
             </div>
             <div className="p-2 border border-nier-border-light">
              <div className="flex items-center justify-between mb-1">
               <span className="text-nier-small text-nier-text-main">性表現</span>
               <span className="text-nier-small text-nier-text-main">{sexualRatingOptions[editForm.contentPermissions.sexualLevel]?.age??''}</span>
              </div>
              <input
               type="range"
               min={0}
               max={4}
               value={editForm.contentPermissions.sexualLevel}
               onChange={(e)=>setEditForm({
                ...editForm,
                contentPermissions:{...editForm.contentPermissions,sexualLevel:Number(e.target.value) as ContentRatingLevel}
               })}
               className="nier-slider"
              />
              <p className="text-nier-caption text-nier-text-light mt-1">{sexualRatingOptions[editForm.contentPermissions.sexualLevel]?.description??''}</p>
             </div>
            </div>
           </div>
)}

           {/*Buttons*/}
           <div className="flex gap-3 pt-2">
            <Button onClick={handleSaveEdit} disabled={!editForm.name.trim()||isLoading}>
             {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:<Check size={14} className="mr-1.5"/>}
             保存
            </Button>
            <Button variant="secondary" onClick={handleCancelEdit}>
             <X size={14} className="mr-1.5"/>
             キャンセル
            </Button>
           </div>
          </div>
) : (
          <div className="space-y-4">
           <div>
            <span className="text-nier-caption text-nier-text-light block">名前</span>
            <span className="text-nier-h2 font-medium">{currentProject.name}</span>
           </div>
           <div>
            <span className="text-nier-caption text-nier-text-light block">ステータス</span>
            <span className={cn('text-nier-body',statusColors[currentProject.status])}>
             {statusLabels[currentProject.status]}
            </span>
           </div>
           <div>
            <span className="text-nier-caption text-nier-text-light block">現在のフェーズ</span>
            <span className="text-nier-body">Phase {currentProject.currentPhase}</span>
           </div>
           {currentProject.concept&&(
            <>
             <div>
              <span className="text-nier-caption text-nier-text-light block">ゲームアイデア</span>
              <span className="text-nier-body">{currentProject.concept.description}</span>
             </div>
             <div className="grid grid-cols-3 gap-4">
              <div>
               <span className="text-nier-caption text-nier-text-light block">プラットフォーム</span>
               <span className="text-nier-body">{currentProject.concept.platform}</span>
              </div>
              <div>
               <span className="text-nier-caption text-nier-text-light block">スコープ</span>
               <span className="text-nier-body">{currentProject.concept.scope}</span>
              </div>
              {currentProject.concept.genre&&(
               <div>
                <span className="text-nier-caption text-nier-text-light block">ジャンル</span>
                <span className="text-nier-body">{currentProject.concept.genre}</span>
               </div>
)}
             </div>
            </>
)}
           <div>
            <span className="text-nier-caption text-nier-text-light block">作成日時</span>
            <span className="text-nier-body">
             {new Date(currentProject.createdAt).toLocaleString('ja-JP')}
            </span>
           </div>
          </div>
)}
        </CardContent>
       </Card>

       {/*Controls*/}
       <Card>
        <CardHeader>
         <DiamondMarker>実行コントロール</DiamondMarker>
        </CardHeader>
        <CardContent>
         <div className="flex gap-3">
          {/*開始: draft の時のみ*/}
          {currentProject.status==='draft'&&(
           <Button onClick={handleStartProject} disabled={isLoading}>
            {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:<Play size={14} className="mr-1.5"/>}
            開始
           </Button>
)}
          {/*再開: paused の時のみ（サーバー側エージェントを再開）*/}
          {currentProject.status==='paused'&&(
           <Button onClick={handleResumeProject} disabled={isLoading}>
            {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:<Play size={14} className="mr-1.5"/>}
            再開
           </Button>
)}
          {/*一時停止: running の時のみ*/}
          {currentProject.status==='running'&&(
           <Button onClick={handlePauseProject} disabled={isLoading}>
            {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:<Pause size={14} className="mr-1.5"/>}
            一時停止
           </Button>
)}
          {/*停止: running または paused の時のみ*/}
          {(currentProject.status==='running'||currentProject.status==='paused')&&(
           <Button variant="secondary" onClick={handleStopProject} disabled={isLoading}>
            <Square size={14} className="mr-1.5"/>
            停止
           </Button>
)}
          {/*ブラッシュアップ: completed の時のみ*/}
          {canBrushup&&(
           <Button onClick={()=>setShowBrushupDialog(true)}>
            <RefreshCw size={14} className="mr-1.5"/>
            ブラッシュアップ
           </Button>
)}
          {/*初期化: draft以外の時（進捗がある時）*/}
          {canInitialize&&(
           <Button
            variant="danger"
            onClick={()=>setShowInitializeDialog(true)}
           >
            <RotateCcw size={14} className="mr-1.5"/>
            初期化
           </Button>
)}
         </div>
        </CardContent>
       </Card>

       {/*Uploaded Files*/}
       <Card>
        <CardHeader>
         <div className="flex items-center justify-between w-full">
          <DiamondMarker>アップロードファイル</DiamondMarker>
          <span className="text-nier-caption text-nier-text-light">{uploadedFiles.length}件</span>
         </div>
        </CardHeader>
        <CardContent>
         {filesLoading?(
          <div className="text-center py-4 text-nier-text-light">
           <Loader2 size={20} className="mx-auto mb-2 animate-spin"/>
           読み込み中...
          </div>
) : filesError?(
          <div className="text-center py-4 text-nier-text-light">
           {filesError}
          </div>
) : uploadedFiles.length===0?(
          <div className="text-center py-4 text-nier-text-light">
           アップロードファイルはありません
          </div>
) : (
          <div className="grid grid-cols-2 gap-2 max-h-[200px] overflow-y-auto">
           {uploadedFiles.map((file)=>{
            const isImage=file.mimeType.startsWith('image/')
            const isAudio=file.mimeType.startsWith('audio/')
            const isPdf=file.mimeType==='application/pdf'
            const FileIcon=isImage?Image : isAudio?Music : isPdf?FileText : File
            const sizeKB=Math.round(file.sizeBytes/1024)

            return(
             <div
              key={file.id}
              className="flex items-center gap-2 p-2 border border-nier-border-light hover:bg-nier-bg-hover"
             >
              {isImage&&file.url?(
               <img
                src={file.url}
                alt={file.originalFilename}
                className="w-10 h-10 object-cover rounded"
               />
) : (
               <div className="w-10 h-10 flex items-center justify-center bg-nier-bg-selected rounded">
                <FileIcon size={20} className="text-nier-text-light"/>
               </div>
)}
              <div className="flex-1 min-w-0">
               <div className="text-nier-small truncate">{file.originalFilename}</div>
               <div className="text-nier-caption text-nier-text-light">
                {file.category}/{sizeKB}KB
               </div>
              </div>
             </div>
)
           })}
          </div>
)}
        </CardContent>
       </Card>
      </div>
) : (
      <Card>
       <CardContent>
        <div className="text-center py-12 text-nier-text-light">
         <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
         <p className="text-nier-body mb-4">プロジェクトを選択するか、新規作成してください</p>
         <Button onClick={()=>setShowNewForm(true)}>
          <Plus size={14} className="mr-1.5"/>
          新規プロジェクト作成
         </Button>
        </div>
       </CardContent>
      </Card>
)}
    </div>
   </div>

   {/*Initialize Confirmation Dialog*/}
   {showInitializeDialog&&currentProject&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-[90vw] md:max-w-sm lg:max-w-md">
      <CardHeader>
       <div className="flex items-center gap-2 text-nier-text-main">
        <AlertTriangle size={18}/>
        <span>初期化の確認</span>
       </div>
      </CardHeader>
      <CardContent>
       <p className="text-nier-body mb-4">
        プロジェクト「{currentProject.name}」を初期化しますか？
       </p>
       <p className="text-nier-small text-nier-text-main mb-6">
        すべての進捗状況とエージェント出力がリセットされます。この操作は取り消せません。
       </p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setShowInitializeDialog(false)}>
         キャンセル
        </Button>
        <Button
         variant="danger"
         onClick={handleInitializeProject}
         disabled={isLoading}
        >
         {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>: null}
         初期化する
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>
)}

   {/*Delete Confirmation Dialog*/}
   {showDeleteDialog&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-full max-w-[90vw] md:max-w-sm lg:max-w-md">
      <CardHeader>
       <div className="flex items-center gap-2 text-nier-text-main">
        <AlertTriangle size={18}/>
        <span>削除の確認</span>
       </div>
      </CardHeader>
      <CardContent>
       <p className="text-nier-body mb-4">
        プロジェクト「{projects.find(p=>p.id===showDeleteDialog)?.name}」を削除しますか？
       </p>
       <p className="text-nier-small text-nier-text-main mb-6">
        この操作は取り消せません。
       </p>
       <div className="flex gap-3 justify-end">
        <Button variant="secondary" onClick={()=>setShowDeleteDialog(null)}>
         キャンセル
        </Button>
        <Button
         variant="danger"
         onClick={()=>{
          handleDeleteProject(showDeleteDialog)
          setShowDeleteDialog(null)
         }}
         disabled={isLoading}
        >
         {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>: null}
         削除する
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>
)}

   {/*Brushup Dialog*/}
   {showBrushupDialog&&currentProject&&(
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
     <Card className="w-[70vw] max-h-[90vh] flex flex-col">
      <CardHeader>
       <div className="flex items-center justify-between w-full">
        <div className="flex items-center gap-2">
         <RefreshCw size={18}/>
         <span>ブラッシュアップ設定</span>
        </div>
        <button
         type="button"
         onClick={()=>{
          setShowBrushupDialog(false)
          setBrushupSelectedAgents(new Set())
          setBrushupClearAssets(false)
          brushupStore.reset()
         }}
         className="p-1 hover:bg-black/20 transition-colors"
        >
         <X size={16}/>
        </button>
       </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-y-auto">
       <div className="space-y-6">
        {/*Section 1: Agent Selection with Options*/}
        <div>
         <h3 className="text-nier-body font-medium mb-3">ブラッシュアップ対象エージェント</h3>
         <p className="text-nier-small text-nier-text-light mb-3">
          エージェントを選択し、改善項目を指定してください。
         </p>
         <div className="space-y-3">
          {brushupPhases.map(phase=>{
           const phaseSelected=phase.agents.filter(a=>brushupSelectedAgents.has(a)).length
           const allSelected=phaseSelected===phase.agents.length
           return(
            <div key={phase.id} className="border border-nier-border-light p-3">
             <button
              type="button"
              onClick={()=>toggleBrushupPhase(phase.agents)}
              className="flex items-center gap-2 w-full text-left mb-2"
             >
              <span className={cn('w-4 h-4 border flex items-center justify-center',
               allSelected?'bg-nier-bg-selected border-nier-border-dark':'border-nier-border-light'
)}>
               {allSelected&&<Check size={12}/>}
               {phaseSelected>0&&!allSelected&&<span className="w-2 h-2 bg-nier-text-light"/>}
              </span>
              <span className="text-nier-body font-medium">{phase.label}</span>
              <span className="text-nier-caption text-nier-text-light ml-auto">
               {phaseSelected}/{phase.agents.length}
              </span>
             </button>
             <div className="space-y-2 pl-6">
              {phase.agents.map(agentType=>{
               const agentOpts=brushupStore.optionsConfig?.agents[agentType]?.options||[]
               const selectedOpts=brushupStore.agentOptions[agentType]||[]
               const isSelected=brushupSelectedAgents.has(agentType)
               return(
                <div key={agentType} className="flex items-start gap-2">
                 <button
                  type="button"
                  onClick={()=>toggleBrushupAgent(agentType)}
                  className="flex items-center gap-2 py-1 min-w-[140px]"
                 >
                  <span className={cn('w-3 h-3 border flex items-center justify-center flex-shrink-0',
                   isSelected?'bg-nier-bg-selected border-nier-border-dark':'border-nier-border-light'
)}>
                   {isSelected&&<Check size={10}/>}
                  </span>
                  <span className="text-nier-small">{getAgentLabel(agentType)}</span>
                 </button>
                 {isSelected&&agentOpts.length>0&&(
                  <div className="flex-1 relative">
                   <select
                    multiple
                    value={selectedOpts}
                    onChange={(e)=>{
                     const values=Array.from(e.target.selectedOptions,o=>o.value)
                     brushupStore.setAgentOptions(agentType,values)
                    }}
                    className="w-full px-2 py-1 bg-nier-bg-main border border-nier-border-light text-nier-small focus:border-nier-accent-gold focus:outline-none min-h-[60px]"
                   >
                    {agentOpts.map(opt=>(
                     <option key={opt.id} value={opt.id}>{opt.label}</option>
))}
                   </select>
                   <span className="text-nier-caption text-nier-text-light mt-1 block">
                    {selectedOpts.length>0?`${selectedOpts.length}件選択中`:'Ctrl+クリックで複数選択'}
                   </span>
                  </div>
)}
                </div>
)
              })}
             </div>
            </div>
)
          })}
         </div>
         <div className="mt-3">
          <button
           type="button"
           onClick={()=>setBrushupClearAssets(!brushupClearAssets)}
           className="flex items-center gap-2"
          >
           <span className={cn('w-4 h-4 border flex items-center justify-center',
            brushupClearAssets?'bg-nier-bg-selected border-nier-border-dark':'border-nier-border-light'
)}>
            {brushupClearAssets&&<Check size={12}/>}
           </span>
           <span className="text-nier-small">選択したエージェントが生成したアセットも削除する</span>
          </button>
         </div>
        </div>

        {/*Section 2: Reference Images*/}
        <div className="border-t border-nier-border-light pt-4">
         <h3 className="text-nier-body font-medium mb-3">参考画像</h3>
         <BrushupReferenceImages/>
        </div>

        {/*Section 3: Custom Instruction*/}
        <div className="border-t border-nier-border-light pt-4">
         <h3 className="text-nier-body font-medium mb-3">全体への追加指示（任意）</h3>
         <textarea
          value={brushupStore.customInstruction}
          onChange={(e)=>brushupStore.setCustomInstruction(e.target.value)}
          placeholder="全エージェントに共通する追加指示があれば記述してください..."
          rows={3}
          className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none resize-y min-h-[84px] max-h-[196px]"
         />
        </div>
       </div>

       {/*Buttons*/}
       <div className="flex gap-3 justify-end mt-6 pt-4 border-t border-nier-border-light">
        <Button
         variant="secondary"
         onClick={()=>{
          setShowBrushupDialog(false)
          setBrushupSelectedAgents(new Set())
          setBrushupClearAssets(false)
          brushupStore.reset()
         }}
        >
         キャンセル
        </Button>
        <Button
         onClick={handleBrushupProject}
         disabled={isLoading||brushupSelectedAgents.size===0}
        >
         {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:null}
         ブラッシュアップ開始
        </Button>
       </div>
      </CardContent>
     </Card>
    </div>
)}
  </div>
)
}
