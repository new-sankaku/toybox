import{useState}from'react'
import{ChevronDown,ChevronRight,AlertTriangle,FileText,Settings}from'lucide-react'
import type{AgentSystemPrompt,PromptComponent}from'@/types/agent'

interface SystemPromptPanelProps{
 data:AgentSystemPrompt
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
}

function ComponentItem({component}:ComponentItemProps){
 const[expanded,setExpanded]=useState(false)
 const contentPreview=component.content.slice(0,200)
 const hasMore=component.content.length>200
 return(
  <div className="py-2 border-b border-nier-border-light last:border-b-0">
   <div className="flex items-start justify-between gap-2">
    <div className="flex-1">
     <div className="flex items-center gap-2">
      <span className="text-nier-body font-medium text-nier-text-main">{component.label}</span>
      {component.source&&(
       <span className="text-nier-caption text-nier-text-light truncate" style={{maxWidth:'clamp(100px,25%,250px)'}} title={component.source}>
        [{component.source.split('/').pop()}]
       </span>
)}
     </div>
     <div className="mt-1">
      <pre className="text-nier-caption text-nier-text-light whitespace-pre-wrap font-mono bg-nier-bg-panel p-2 border border-nier-border-light overflow-x-auto">
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
     </div>
    </div>
   </div>
  </div>
)
}

export function SystemPromptPanel({data}:SystemPromptPanelProps):JSX.Element{
 return(
  <div className="space-y-3">
   {data.hasQualityFeedback&&(
    <div className="flex items-start gap-2 px-3 py-2 border border-nier-accent-orange bg-nier-bg-panel">
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
        <ComponentItem key={idx} component={comp}/>
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
        <ComponentItem key={idx} component={comp}/>
))}
     </div>
):(
     <p className="text-nier-caption text-nier-text-light py-2">構成要素がありません</p>
)}
   </CollapsibleSection>

   {data.principles.length>0&&(
    <div className="px-3 py-2 bg-nier-bg-panel border border-nier-border-light">
     <p className="text-nier-caption text-nier-text-light mb-1">適用原則:</p>
     <div className="flex flex-wrap gap-1">
      {data.principles.map((p,idx)=>(
       <span
        key={idx}
        className="px-2 py-0.5 text-nier-caption bg-nier-bg-selected text-nier-text-main border border-nier-border-light"
       >
        {p}
       </span>
))}
     </div>
    </div>
)}

   {data.basePromptFile&&(
    <div className="px-3 py-2 bg-nier-bg-panel border border-nier-border-light">
     <p className="text-nier-caption text-nier-text-light">
      ベースプロンプトファイル:<span className="font-mono">{data.basePromptFile}</span>
     </p>
    </div>
)}
  </div>
)
}
