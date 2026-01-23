import{useCallback,useState}from'react'
import Editor,{loader}from'@monaco-editor/react'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{Copy,Check,Download}from'lucide-react'

loader.config({
 paths:{
  vs:'https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs'
 }
})

interface CodeViewerProps{
 code:string
 language?:string
 filename?:string
 showLineNumbers?:boolean
 maxHeight?:string
 className?:string
 onCopy?:()=>void
}

const monacoOptions={
 readOnly:true,
 minimap:{enabled:false},
 lineNumbers:'on'as const,
 scrollBeyondLastLine:false,
 wordWrap:'on'as const,
 renderWhitespace:'none'as const,
 fontFamily:'"Consolas", "Courier New", monospace',
 fontSize:13,
 lineHeight:20,
 padding:{top:12,bottom:12},
 scrollbar:{
  vertical:'auto'as const,
  horizontal:'auto'as const,
  verticalScrollbarSize:6,
  horizontalScrollbarSize:6
 }
}

const nierTheme={
 base:'vs'as const,
 inherit:true,
 rules:[
  {token:'comment',foreground:'7A756A',fontStyle:'italic'},
  {token:'keyword',foreground:'B85C5C'},
  {token:'string',foreground:'7AAA7A'},
  {token:'number',foreground:'C4956C'},
  {token:'type',foreground:'6B8FAA'}
],
 colors:{
  'editor.background':'#E8E4D4',
  'editor.foreground':'#454138',
  'editor.lineHighlightBackground':'#DAD5C3',
  'editor.selectionBackground':'#CCC7B5',
  'editorLineNumber.foreground':'#7A756A',
  'editorLineNumber.activeForeground':'#454138',
  'editorCursor.foreground':'#454138',
  'editor.inactiveSelectionBackground':'#DAD5C3'
 }
}

export function CodeViewer({
 code,
 language='typescript',
 filename,
 showLineNumbers=true,
 maxHeight='400px',
 className,
 onCopy
}:CodeViewerProps):JSX.Element{
 const[copied,setCopied]=useState(false)

 const handleCopy=useCallback(async()=>{
  try{
   await navigator.clipboard.writeText(code)
   setCopied(true)
   onCopy?.()
   setTimeout(()=>setCopied(false),2000)
  }catch(err){
   console.error('Failed to copy:',err)
  }
 },[code,onCopy])

 const handleDownload=useCallback(()=>{
  const blob=new Blob([code],{type:'text/plain'})
  const url=URL.createObjectURL(blob)
  const a=document.createElement('a')
  a.href=url
  a.download=filename||`code.${language}`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
 },[code,filename,language])

 const lineCount=code.split('\n').length

 return(
  <div className={cn('code-viewer border border-nier-border-light',className)}>
   {/*Header*/}
   {filename&&(
    <div className="flex items-center justify-between bg-nier-bg-header text-nier-text-header px-4 py-2">
     <div className="flex items-center gap-3">
      <span className="text-nier-small tracking-nier">{filename}</span>
      <span className="text-nier-caption text-nier-text-header/70">
       {lineCount} lines|{language}
      </span>
     </div>
     <div className="flex items-center gap-2">
      <Button
       variant="ghost"
       size="sm"
       className="text-nier-text-header hover:bg-white/10"
       onClick={handleCopy}
      >
       {copied?(
        <Check size={14} className="text-nier-accent-green"/>
) : (
        <Copy size={14}/>
)}
       <span className="ml-1.5 text-nier-caption">
        {copied?'Copied!' : 'Copy'}
       </span>
      </Button>
      <Button
       variant="ghost"
       size="sm"
       className="text-nier-text-header hover:bg-white/10"
       onClick={handleDownload}
      >
       <Download size={14}/>
       <span className="ml-1.5 text-nier-caption">Download</span>
      </Button>
     </div>
    </div>
)}

   {/*Editor*/}
   <div style={{height:maxHeight}}>
    <Editor
     height="100%"
     language={language}
     value={code}
     options={{
      ...monacoOptions,
      lineNumbers:showLineNumbers?'on' : 'off'
     }}
     theme="nier-theme"
     beforeMount={(monaco)=>{
      monaco.editor.defineTheme('nier-theme',nierTheme)
     }}
     loading={
      <div className="flex items-center justify-center h-full bg-nier-bg-main text-nier-text-light">
       Loading editor...
      </div>
     }
    />
   </div>

   {/*Footer*/}
   {!filename&&(
    <div className="flex items-center justify-between bg-nier-bg-panel px-4 py-2 border-t border-nier-border-light">
     <span className="text-nier-caption text-nier-text-light">
      {lineCount} lines|{language}
     </span>
     <div className="flex items-center gap-2">
      <Button
       variant="ghost"
       size="sm"
       onClick={handleCopy}
      >
       {copied?(
        <Check size={14} className="text-nier-accent-green"/>
) : (
        <Copy size={14}/>
)}
      </Button>
     </div>
    </div>
)}
  </div>
)
}
