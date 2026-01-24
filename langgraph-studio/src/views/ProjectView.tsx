import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{FileUploader}from'@/components/project/FileUploader'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{useProjectOptionsStore}from'@/stores/projectOptionsStore'
import{projectApi,fileUploadApi,extractApiError}from'@/services/apiService'
import type{Project,ProjectStatus}from'@/types/project'
import type{FileCategory}from'@/types/uploadedFile'
import{cn}from'@/lib/utils'
import{Play,Pause,Square,Trash2,Plus,FolderOpen,RotateCcw,AlertTriangle,Loader2,RefreshCw,Pencil,X,Check,Upload,FileText,Image,Music,File}from'lucide-react'
import{
 PROJECT_DEFAULTS,
 ASSET_SERVICE_OPTIONS,
 CONTENT_PERMISSION_OPTIONS,
 type Platform,
 type Scope,
 type LLMProvider,
 type AssetGenerationOptions,
 type ContentPermissions
}from'@/config/projectOptions'

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
 llmProvider:LLMProvider
 assetGeneration:AssetGenerationOptions
 contentPermissions:ContentPermissions
}

const getInitialForm=(defaults:{platform:string;scope:string;llmProvider:string}):NewProjectForm=>({
 name:'',
 userIdea:'',
 references:'',
 platform:defaults.platform as Platform,
 scope:defaults.scope as Scope,
 llmProvider:defaults.llmProvider as LLMProvider,
 assetGeneration:{...PROJECT_DEFAULTS.assetGeneration},
 contentPermissions:{...PROJECT_DEFAULTS.contentPermissions}
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
 running:'text-nier-text-light',
 paused:'text-nier-text-light',
 completed:'text-nier-text-light',
 failed:'text-nier-text-light'
}

export default function ProjectView():JSX.Element{
 const{currentProject,setCurrentProject,projects,setProjects,incrementDataVersion}=useProjectStore()
 const{setActiveTab}=useNavigationStore()
 const{platforms,scopes,llmProviders,defaults,fetchOptions}=useProjectOptionsStore()
 const initialForm=getInitialForm(defaults)
 const[showNewForm,setShowNewForm]=useState(false)
 const[form,setForm]=useState<NewProjectForm>(initialForm)
 const[selectedFiles,setSelectedFiles]=useState<SelectedFile[]>([])
 const[showInitializeDialog,setShowInitializeDialog]=useState(false)
 const[isLoading,setIsLoading]=useState(false)
 const[uploadProgress,setUploadProgress]=useState<string|null>(null)
 const[error,setError]=useState<string|null>(null)
 const[isEditing,setIsEditing]=useState(false)
 const[editForm,setEditForm]=useState<NewProjectForm>(initialForm)
 const[uploadedFiles,setUploadedFiles]=useState<UploadedFile[]>([])
 const[filesLoading,setFilesLoading]=useState(false)

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
   setUploadedFiles([])
  }finally{
   setFilesLoading(false)
  }
 },[])

 useEffect(()=>{
  fetchProjects()
  fetchOptions()
 },[])

 useEffect(()=>{
  if(currentProject){
   fetchUploadedFiles(currentProject.id)
  }else{
   setUploadedFiles([])
  }
 },[currentProject,fetchUploadedFiles])

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
     scope:form.scope
    },
    config:{
     llmProvider:form.llmProvider,
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

 const handleEditProjectFromList=(project:Project)=>{
  if(currentProject?.id!==project.id){
   incrementDataVersion()
  }
  setCurrentProject(project)
  setEditForm({
   name:project.name,
   userIdea:project.concept?.description||'',
   references:'',
   platform:(project.concept?.platform as Platform)||defaults.platform,
   scope:(project.concept?.scope as Scope)||defaults.scope,
   llmProvider:(project.config?.llmProvider as LLMProvider)||defaults.llmProvider,
   assetGeneration:project.config?.assetGeneration||{...PROJECT_DEFAULTS.assetGeneration},
   contentPermissions:project.config?.contentPermissions||{...PROJECT_DEFAULTS.contentPermissions}
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

 const handleStartEdit=()=>{
  if(!currentProject)return
  setEditForm({
   name:currentProject.name,
   userIdea:currentProject.concept?.description||'',
   references:'',
   platform:(currentProject.concept?.platform as Platform)||defaults.platform,
   scope:(currentProject.concept?.scope as Scope)||defaults.scope,
   llmProvider:(currentProject.config?.llmProvider as LLMProvider)||defaults.llmProvider,
   assetGeneration:currentProject.config?.assetGeneration||{...PROJECT_DEFAULTS.assetGeneration},
   contentPermissions:currentProject.config?.contentPermissions||{...PROJECT_DEFAULTS.contentPermissions}
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
     scope:editForm.scope
    },
    config:{
     ...currentProject.config,
     llmProvider:editForm.llmProvider,
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
  <div className="p-4 animate-nier-fade-in">
   {/*Error Message*/}
   {error&&(
    <div className="mb-4 p-3 bg-nier-bg-panel border border-nier-border-dark text-nier-text-main text-nier-small">
     {error}
     <button
      onClick={()=>setError(null)}
      className="ml-2 underline hover:no-underline"
     >
      閉じる
     </button>
    </div>
)}

   <div className="grid grid-cols-3 gap-3">
    {/*Left: Project List*/}
    <div className="col-span-1 space-y-3">
     <Card>
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
      <CardContent>
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
        <div className="space-y-2 nier-scroll-list-short">
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
               handleDeleteProject(project.id)
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
    <div className="col-span-2">
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
           スコープ（ゲームの規模）
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

         {/*LLM Provider*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-1">
           LLMプロバイダー
          </label>
          <select
           value={form.llmProvider}
           onChange={(e)=>setForm({...form,llmProvider:e.target.value as LLMProvider})}
           className="w-full px-3 py-2 bg-nier-bg-main border border-nier-border-light text-nier-body focus:border-nier-accent-gold focus:outline-none"
          >
           {llmProviders.map((opt)=>(
            <option key={opt.value} value={opt.value}>{opt.label}</option>
))}
          </select>
         </div>

         {/*Asset Generation Options*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           アセット自動生成
          </label>
          <div className="grid grid-cols-2 gap-2">
           {ASSET_SERVICE_OPTIONS.map((opt)=>(
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

         {/*Content Permissions*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-2">
           コンテンツ許可
          </label>
          <div className="flex gap-4">
           {CONTENT_PERMISSION_OPTIONS.map((opt)=>(
            <label
             key={opt.key}
             className="flex items-center gap-2 cursor-pointer"
            >
             <input
              type="checkbox"
              checked={form.contentPermissions[opt.key]}
              onChange={(e)=>setForm({
               ...form,
               contentPermissions:{...form.contentPermissions,[opt.key]:e.target.checked}
              })}
              className="w-4 h-4"
             />
             <span className="text-nier-small">{opt.label}</span>
            </label>
))}
          </div>
         </div>

         {/*Initial Files*/}
         <div>
          <label className="block text-nier-small text-nier-text-light mb-1">
           <Upload size={14} className="inline mr-1"/>
           初期ファイル（オプション）
          </label>
          <p className="text-nier-caption text-nier-text-light mb-2">
           企画書、仕様書、参考資料、アセットなどをアップロードできます
          </p>
          <FileUploader
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
             {ASSET_SERVICE_OPTIONS.map((opt)=>(
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

           {/*Content Permissions*/}
           <div>
            <label className="block text-nier-small text-nier-text-light mb-2">
             コンテンツ許可
            </label>
            <div className="flex gap-4">
             {CONTENT_PERMISSION_OPTIONS.map((opt)=>(
              <label
               key={opt.key}
               className="flex items-center gap-2 cursor-pointer"
              >
               <input
                type="checkbox"
                checked={editForm.contentPermissions[opt.key]}
                onChange={(e)=>setEditForm({
                 ...editForm,
                 contentPermissions:{...editForm.contentPermissions,[opt.key]:e.target.checked}
                })}
                className="w-4 h-4"
               />
               <span className="text-nier-small">{opt.label}</span>
              </label>
))}
            </div>
           </div>

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
          {/*開始/再開: draft または paused の時のみ*/}
          {(currentProject.status==='draft'||currentProject.status==='paused')&&(
           <Button onClick={handleStartProject} disabled={isLoading}>
            {isLoading?<Loader2 size={14} className="mr-1.5 animate-spin"/>:<Play size={14} className="mr-1.5"/>}
            {currentProject.status==='paused'?'再開' : '開始'}
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
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
     <Card className="w-96">
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
  </div>
)
}
