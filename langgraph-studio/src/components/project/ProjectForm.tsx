import{useState,useEffect}from'react'
import{Input}from'@/components/ui/Input'
import{Select,SelectOption}from'@/components/ui/Select'
import{Textarea}from'@/components/ui/Textarea'
import{Button}from'@/components/ui/Button'
import{Panel}from'@/components/ui/Panel'
import{Checkbox}from'@/components/ui/Checkbox'
import{FileUploader}from'./FileUploader'
import{useLanguageStore}from'@/stores/languageStore'
import type{CreateProjectInput,GameConcept}from'@/types/project'
import type{FileCategory}from'@/types/uploadedFile'

interface SelectedFile{
 file:File
 category:FileCategory
 preview?:string
}

interface ProjectFormProps{
 onSubmit:(data:CreateProjectInput,files:File[])=>void
 onCancel?:()=>void
 isLoading?:boolean
 initialData?:Partial<CreateProjectInput>
}

const platformOptions:SelectOption[]=[
 {value:'web',label:'Web Browser'},
 {value:'desktop',label:'Desktop (Electron)'},
 {value:'mobile',label:'Mobile (PWA)'}
]

const scopeOptions:SelectOption[]=[
 {value:'mvp',label:'MVP-Minimal Viable Product'},
 {value:'full',label:'Full-Complete Game'}
]

const genreOptions:SelectOption[]=[
 {value:'rpg',label:'RPG'},
 {value:'action',label:'Action'},
 {value:'puzzle',label:'Puzzle'},
 {value:'adventure',label:'Adventure'},
 {value:'simulation',label:'Simulation'},
 {value:'strategy',label:'Strategy'},
 {value:'other',label:'Other'}
]

export function ProjectForm({onSubmit,onCancel,isLoading,initialData}:ProjectFormProps){
 const{languages:languageOptions,defaultPrimary,defaultLanguages,fetchLanguages}=useLanguageStore()

 const[name,setName]=useState(initialData?.name||'')
 const[description,setDescription]=useState(initialData?.description||'')
 const[conceptDescription,setConceptDescription]=useState(initialData?.concept?.description||'')
 const[platform,setPlatform]=useState<GameConcept['platform']>(initialData?.concept?.platform||'web')
 const[scope,setScope]=useState<GameConcept['scope']>(initialData?.concept?.scope||'mvp')
 const[genre,setGenre]=useState(initialData?.concept?.genre||'')
 const[primaryLanguage,setPrimaryLanguage]=useState(initialData?.concept?.primaryLanguage||'')
 const[languages,setLanguages]=useState<string[]>(initialData?.concept?.languages||[])
 const[selectedFiles,setSelectedFiles]=useState<SelectedFile[]>([])

 useEffect(()=>{
  fetchLanguages()
 },[fetchLanguages])

 useEffect(()=>{
  if(!primaryLanguage&&defaultPrimary){
   setPrimaryLanguage(defaultPrimary)
  }
  if(languages.length===0&&defaultLanguages.length>0){
   setLanguages(defaultLanguages)
  }
 },[defaultPrimary,defaultLanguages])

 const[errors,setErrors]=useState<Record<string,string>>({})

 const validate=():boolean=>{
  const newErrors:Record<string,string>={}

  if(!name.trim()){
   newErrors.name='Project name is required'
  }
  if(!conceptDescription.trim()){
   newErrors.conceptDescription='Game concept description is required'
  }
  if(conceptDescription.length<20){
   newErrors.conceptDescription='Please provide more detail (min 20 characters)'
  }

  setErrors(newErrors)
  return Object.keys(newErrors).length===0
 }

 const handleSubmit=(e:React.FormEvent)=>{
  e.preventDefault()
  if(!validate())return

  onSubmit({
   name:name.trim(),
   description:description.trim()||undefined,
   concept:{
    description:conceptDescription.trim(),
    platform,
    scope,
    genre:genre||undefined,
    primaryLanguage,
    languages
   }
  },selectedFiles.map(sf=>sf.file))
 }

 return(
  <form onSubmit={handleSubmit} className="space-y-6">

   <Panel title="PROJECT INFORMATION">
    <div className="space-y-4">
     <Input
      label="Project Name"
      value={name}
      onChange={(e)=>setName(e.target.value)}
      placeholder="My Awesome Game"
      error={errors.name}
      disabled={isLoading}
     />
     <Textarea
      label="Description (optional)"
      value={description}
      onChange={(e)=>setDescription(e.target.value)}
      placeholder="Brief description of your project..."
      rows={2}
      disabled={isLoading}
     />
    </div>
   </Panel>


   <Panel title="GAME CONCEPT">
    <div className="space-y-4">
     <Textarea
      label="Game Concept"
      value={conceptDescription}
      onChange={(e)=>setConceptDescription(e.target.value)}
      placeholder="Describe your game idea in detail. What is the gameplay like? What makes it unique? Who is the target audience?"
      rows={5}
      error={errors.conceptDescription}
      disabled={isLoading}
     />
     <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
      <Select
       label="Platform"
       options={platformOptions}
       value={platform}
       onChange={(e)=>setPlatform(e.target.value as GameConcept['platform'])}
       disabled={isLoading}
      />
      <Select
       label="Scope"
       options={scopeOptions}
       value={scope}
       onChange={(e)=>setScope(e.target.value as GameConcept['scope'])}
       disabled={isLoading}
      />
      <Select
       label="Genre"
       options={genreOptions}
       value={genre}
       onChange={(e)=>setGenre(e.target.value)}
       placeholder="Select genre..."
       disabled={isLoading}
      />
     </div>
    </div>
   </Panel>


   {languageOptions.length>0&&(
   <Panel title="LANGUAGE SETTINGS">
    <div className="space-y-4">
     <Select
      label="主要言語"
      options={languageOptions.map(l=>({value:l.value,label:`${l.label} (${l.nativeName})`}))}
      value={primaryLanguage}
      onChange={(e)=>{
       setPrimaryLanguage(e.target.value)
       if(!languages.includes(e.target.value)){
        setLanguages([...languages,e.target.value])
       }
      }}
      disabled={isLoading}
     />
     <div>
      <label className="block text-nier-small text-nier-text-light mb-2">対応言語</label>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
       {languageOptions.map(lang=>(
        <Checkbox
         key={lang.value}
         label={`${lang.label}`}
         checked={languages.includes(lang.value)}
         onChange={(checked)=>{
          if(checked){
           setLanguages([...languages,lang.value])
          }else if(lang.value!==primaryLanguage){
           setLanguages(languages.filter(l=>l!==lang.value))
          }
         }}
         disabled={isLoading||lang.value===primaryLanguage}
        />
))}
      </div>
      <p className="text-nier-caption text-nier-text-light mt-2">主要言語は必ず対応言語に含まれます</p>
     </div>
    </div>
   </Panel>
)}


   <Panel title="INITIAL FILES (Optional)">
    <div className="space-y-2">
     <p className="text-nier-caption text-nier-text-light">
      プロジェクト開始時に使用する企画書、仕様書、参考資料、アセットなどをアップロードできます。
     </p>
     <FileUploader
      files={selectedFiles}
      onFilesChange={setSelectedFiles}
      disabled={isLoading}
     />
    </div>
   </Panel>


   <div className="flex items-center justify-end gap-3">
    {onCancel&&(
     <Button type="button" variant="ghost" onClick={onCancel} disabled={isLoading}>
      Cancel
     </Button>
)}
    <Button type="submit" variant="primary" disabled={isLoading}>
     {isLoading?'Creating...' : 'Create Project'}
    </Button>
   </div>
  </form>
)
}
