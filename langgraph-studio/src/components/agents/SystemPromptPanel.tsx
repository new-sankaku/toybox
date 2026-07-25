import{useState,useCallback}from'react'
import{ChevronDown,ChevronRight,AlertTriangle,FileText,Settings,Edit3,Save}from'lucide-react'
import{Button}from'@/components/ui/Button'
import{agentApi}from'@/services/apiService'
import type{AgentSystemPrompt,PromptComponent}from'@/types/agent'

interface SystemPromptPanelProps{
 data:AgentSystemPrompt
 agentId?:string
}

interface CollapsibleSectionProps{
 title:string
 icon:React.ReactNode
 children:React.ReactNode
 defaultOpen?:boolean
}

function CollapsibleSection({title,icon,children,defaultOpen=true}:CollapsibleSectionProps){
 const[isOpen,setIsOpen]=useState(defaultOpen)
 return(
  <div className="border border-nier-border-light">
   <button
    onClick={()=>setIsOpen(!isOpen)}
    className="w-full flex items-center gap-2 px-3 py-2 bg-nier-bg-panel hover:bg-nier-bg-selected transition-colors"
   >
    {isOpen?<ChevronDown size={14} className="text-nier-text-light"/>:<ChevronRight size={14} className="text-nier-text-light"/>}
    {icon}
    <span className="text-nier-body font-medium text-nier-text-main">{title}</span>
   </button>
   {isOpen&&(
    <div className="px-3 py-2 bg-nier-bg-main">
     {children}
    </div>
)}
  </div>
)
}

interface ComponentItemProps{
 component:PromptComponent
 isEditing:boolean
 editedContent:string
 onContentChange:(content:string)=>void
}

function ComponentItem({component,isEditing,editedContent,onContentChange}:ComponentItemProps){
 const[expanded,setExpanded]=useState(false)
 const contentPreview=component.content.slice(0,200)
 const hasMore=component.content.length>200
 return(
  <div className="py-2 border-b border-nier-border-light last:border-b-0">
   <div className="flex items-start justify-between gap-2">
    <div className="flex-1">
     <div className="flex items-center gap-2">
      <span className="text-nier-body font-medium text-nier-text-main">{component.label}</span>
     </div>
     <div className="mt-1">
      {isEditing?(
       <textarea
        className="w-full text-nier-caption font-mono nier-surface-panel-muted p-2 border border-nier-border-light resize-y min-h-[80px]"
        value={editedContent}
        onChange={(e)=>onContentChange(e.target.value)}
        rows={Math.min(20,editedContent.split('\n').length+2)}
       />
):(
       <>
        <pre className="text-nier-caption whitespace-pre-wrap font-mono nier-surface-panel-muted p-2 border border-nier-border-light overflow-x-auto">
         {expanded?component.content:contentPreview}
         {hasMore&&!expanded&&'...'}
        </pre>
        {hasMore&&(
         <button
          onClick={()=>setExpanded(!expanded)}
          className="mt-1 text-nier-caption text-nier-text-light hover:text-nier-text-main"
         >
          {expanded?'折りたたむ':'すべて表示'}
         </button>
)}
       </>
)}
     </div>
    </div>
   </div>
  </div>
)
}

export function SystemPromptPanel({data,agentId}:SystemPromptPanelProps):JSX.Element{
 const[isEditing,setIsEditing]=useState(false)
 const[saving,setSaving]=useState(false)
 const[saveMessage,setSaveMessage]=useState<{text:string;type:'success'|'error'}|null>(null)
 const[editedComponents,setEditedComponents]=useState<Record<string,string>>({})

 const startEditing=useCallback(()=>{
  const initial:Record<string,string>={}
  data.systemComponents.forEach((c,i)=>{initial[`system-${i}`]=c.content})
  data.userComponents.forEach((c,i)=>{initial[`user-${i}`]=c.content})
  setEditedComponents(initial)
  setIsEditing(true)
 },[data])

 const cancelEditing=useCallback(()=>{
  setIsEditing(false)
  setEditedComponents({})
 },[])

 const getFullPromptContent=useCallback(():string=>{
  const parts:string[]=[]
  data.systemComponents.forEach((_,i)=>{
   parts.push(editedComponents[`system-${i}`]||'')
  })
  data.userComponents.forEach((_,i)=>{
   parts.push(editedComponents[`user-${i}`]||'')
  })
  return parts.join('\n\n')
 },[data,editedComponents])

 const handleSaveToProject=useCallback(async()=>{
  if(!agentId)return
  setSaving(true)
  setSaveMessage(null)
  try{
   await agentApi.savePromptToProject(agentId,getFullPromptContent())
   setSaveMessage({text:'このプロジェクトに保存しました',type:'success'})
   setIsEditing(false)
  }catch{
   setSaveMessage({text:'保存に失敗しました',type:'error'})
  }finally{
   setSaving(false)
   setTimeout(()=>setSaveMessage(null),3000)
  }
 },[agentId,getFullPromptContent])

 const handleSaveToGlobal=useCallback(async()=>{
  if(!agentId)return
  setSaving(true)
  setSaveMessage(null)
  try{
   await agentApi.savePromptToGlobal(agentId,getFullPromptContent())
   setSaveMessage({text:'全てのプロジェクトに保存しました',type:'success'})
   setIsEditing(false)
  }catch{
   setSaveMessage({text:'保存に失敗しました',type:'error'})
  }finally{
   setSaving(false)
   setTimeout(()=>setSaveMessage(null),3000)
  }
 },[agentId,getFullPromptContent])

 return(
  <div className="space-y-3">
   {saveMessage&&(
    <div className={`px-3 py-1.5 text-nier-caption border ${
     saveMessage.type==='success'?'border-nier-accent-green text-nier-accent-green':'border-nier-accent-red text-nier-accent-red'
    }`}>
     {saveMessage.text}
    </div>
)}

   {agentId&&(
    <div className="flex items-center gap-2">
     {!isEditing?(
      <Button size="sm" variant="default" onClick={startEditing} className="gap-1.5">
       <Edit3 size={12}/>
       編集
      </Button>
):(
      <>
       <Button size="sm" variant="secondary" onClick={cancelEditing} disabled={saving}>
        キャンセル
       </Button>
       <Button size="sm" variant="default" onClick={handleSaveToProject} disabled={saving} className="gap-1.5">
        <Save size={12}/>
        {saving?'保存中...':'このプロジェクトに保存'}
       </Button>
       <Button size="sm" variant="primary" onClick={handleSaveToGlobal} disabled={saving} className="gap-1.5">
        <Save size={12}/>
        {saving?'保存中...':'全てのプロジェクトに保存'}
       </Button>
      </>
)}
    </div>
)}

   {data.hasQualityFeedback&&(
    <div className="flex items-start gap-2 px-3 py-2 border border-nier-accent-orange nier-surface-panel">
     <AlertTriangle size={14} className="text-nier-accent-orange flex-shrink-0 mt-0.5"/>
     <p className="text-nier-caption text-nier-text-main">
      このエージェントは品質チェックフィードバックを受けてリトライされました
     </p>
    </div>
)}

   <CollapsibleSection
    title="System Prompt 構成"
    icon={<Settings size={14} className="text-nier-text-light"/>}
    defaultOpen={true}
   >
    {data.systemComponents.length>0?(
     <div className="space-y-0">
      {data.systemComponents
       .sort((a,b)=>a.order-b.order)
       .map((comp,idx)=>(
        <ComponentItem
         key={idx}
         component={comp}
         isEditing={isEditing}
         editedContent={editedComponents[`system-${idx}`]||comp.content}
         onContentChange={(content)=>setEditedComponents(prev=>({...prev,[`system-${idx}`]:content}))}
        />
))}
     </div>
):(
     <p className="text-nier-caption text-nier-text-light py-2">構成要素がありません</p>
)}
   </CollapsibleSection>

   <CollapsibleSection
    title="User Prompt 構成"
    icon={<FileText size={14} className="text-nier-text-light"/>}
    defaultOpen={true}
   >
    {data.userComponents.length>0?(
     <div className="space-y-0">
      {data.userComponents
       .sort((a,b)=>a.order-b.order)
       .map((comp,idx)=>(
        <ComponentItem
         key={idx}
         component={comp}
         isEditing={isEditing}
         editedContent={editedComponents[`user-${idx}`]||comp.content}
         onContentChange={(content)=>setEditedComponents(prev=>({...prev,[`user-${idx}`]:content}))}
        />
))}
     </div>
):(
     <p className="text-nier-caption text-nier-text-light py-2">構成要素がありません</p>
)}
   </CollapsibleSection>

   {data.principles.length>0&&(
    <div className="px-3 py-2 nier-surface-panel border border-nier-border-light">
     <p className="text-nier-caption text-nier-text-light mb-1">適用原則:</p>
     <div className="flex flex-wrap gap-1">
      {data.principles.map((p,idx)=>(
       <span
        key={idx}
        className="px-2 py-0.5 text-nier-caption nier-surface-selected border border-nier-border-light"
       >
        {p}
       </span>
))}
     </div>
    </div>
)}

   {data.basePromptFile&&(
    <div className="px-3 py-2 nier-surface-panel border border-nier-border-light">
     <p className="text-nier-caption text-nier-text-light">
      ベースプロンプトファイル:<span className="font-mono">{data.basePromptFile}</span>
     </p>
    </div>
)}
  </div>
)
}
