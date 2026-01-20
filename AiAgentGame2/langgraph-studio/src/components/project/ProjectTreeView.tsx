import{useState,useRef}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{ChevronDown,ChevronRight,Download,Upload,RefreshCw,Archive}from'lucide-react'

export interface FileNode{
 id:string
 name:string
 type:'file'|'directory'
 path:string
 modified?:boolean
 children?:FileNode[]
 size?:number
 mimeType?:string
}

interface ProjectTreeViewProps{
 projectId:string
 rootNode:FileNode
 onDownload?:(node:FileNode)=>void
 onReplace?:(node:FileNode,file:File)=>void
 onDownloadAll?:()=>void
 onRefresh?:()=>void
}

interface TreeNodeProps{
 node:FileNode
 depth:number
 onDownload?:(node:FileNode)=>void
 onReplace?:(node:FileNode,file:File)=>void
}

function TreeNode({node,depth,onDownload,onReplace}:TreeNodeProps){
 const[expanded,setExpanded]=useState(depth<2)
 const fileInputRef=useRef<HTMLInputElement>(null)

 const handleReplace=(e:React.ChangeEvent<HTMLInputElement>)=>{
  const file=e.target.files?.[0]
  if(file&&onReplace){
   onReplace(node,file)
  }
  e.target.value=''
 }

 const formatSize=(bytes?:number)=>{
  if(!bytes)return''
  if(bytes<1024)return`${bytes}B`
  if(bytes<1024*1024)return`${(bytes/1024).toFixed(1)}KB`
  return`${(bytes/1024/1024).toFixed(1)}MB`
 }

 const indent=depth*16

 if(node.type==='directory'){
  return(
   <div>
    <div
     className={cn(
      'flex items-center py-1 px-2 cursor-pointer',
      'hover:bg-nier-bg-panel transition-colors'
     )}
     style={{paddingLeft:`${indent}px`}}
     onClick={()=>setExpanded(!expanded)}
    >
     {expanded?<ChevronDown size={14}/>:<ChevronRight size={14}/>}
     <span className="ml-1 text-nier-small text-nier-text-main">{node.name}/</span>
    </div>
    {expanded&&node.children?.map(child=>(
     <TreeNode
      key={child.id}
      node={child}
      depth={depth+1}
      onDownload={onDownload}
      onReplace={onReplace}
     />
    ))}
   </div>
  )
 }

 return(
  <div
   className={cn(
    'flex items-center justify-between py-1 px-2',
    'hover:bg-nier-bg-panel transition-colors group'
   )}
   style={{paddingLeft:`${indent+18}px`}}
  >
   <div className="flex items-center gap-2 min-w-0">
    <span className={cn(
     'text-nier-small truncate',
     node.modified?'text-nier-accent-yellow':'text-nier-text-main'
    )}>
     {node.name}
    </span>
    {node.modified&&<span className="text-nier-caption text-nier-accent-yellow">*</span>}
    {node.size&&(
     <span className="text-nier-caption text-nier-text-light">{formatSize(node.size)}</span>
    )}
   </div>
   <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
    <button
     onClick={()=>onDownload?.(node)}
     className="p-1 text-nier-text-light hover:text-nier-text-main transition-colors"
     title="ダウンロード"
    >
     <Download size={14}/>
    </button>
    <button
     onClick={()=>fileInputRef.current?.click()}
     className="p-1 text-nier-text-light hover:text-nier-text-main transition-colors"
     title="差し替え"
    >
     <Upload size={14}/>
    </button>
    <input
     ref={fileInputRef}
     type="file"
     className="hidden"
     onChange={handleReplace}
    />
   </div>
  </div>
 )
}

export function ProjectTreeView({
 projectId,
 rootNode,
 onDownload,
 onReplace,
 onDownloadAll,
 onRefresh
}:ProjectTreeViewProps):JSX.Element{
 const countFiles=(node:FileNode):number=>{
  if(node.type==='file')return 1
  return node.children?.reduce((sum,child)=>sum+countFiles(child),0)||0
 }

 const countModified=(node:FileNode):number=>{
  if(node.type==='file')return node.modified?1:0
  return node.children?.reduce((sum,child)=>sum+countModified(child),0)||0
 }

 const totalFiles=countFiles(rootNode)
 const modifiedFiles=countModified(rootNode)

 return(
  <Card>
   <CardHeader>
    <DiamondMarker>プロジェクト構造</DiamondMarker>
   </CardHeader>
   <CardContent className="space-y-3">
    <div className="flex items-center justify-between">
     <div className="text-nier-small text-nier-text-light">
      {totalFiles} ファイル
      {modifiedFiles>0&&(
       <span className="text-nier-accent-yellow ml-2">({modifiedFiles} 変更あり)</span>
      )}
     </div>
     <div className="flex gap-2">
      <Button variant="ghost" size="sm" onClick={onRefresh}>
       <RefreshCw size={14}/>
       <span className="ml-1">更新</span>
      </Button>
      <Button variant="ghost" size="sm" onClick={onDownloadAll}>
       <Archive size={14}/>
       <span className="ml-1">全てダウンロード</span>
      </Button>
     </div>
    </div>

    <div className="border border-nier-border-light bg-nier-bg-panel max-h-96 overflow-y-auto">
     <TreeNode
      node={rootNode}
      depth={0}
      onDownload={onDownload}
      onReplace={onReplace}
     />
    </div>

    <div className="text-nier-caption text-nier-text-light">
     * = 変更あり
    </div>
   </CardContent>
  </Card>
 )
}

export const MOCK_PROJECT_TREE:FileNode={
 id:'root',
 name:'project-root',
 type:'directory',
 path:'/',
 children:[
  {
   id:'src',
   name:'src',
   type:'directory',
   path:'/src',
   children:[
    {id:'main',name:'main.py',type:'file',path:'/src/main.py',modified:true,size:4521},
    {id:'utils',name:'utils.py',type:'file',path:'/src/utils.py',size:1234},
    {
     id:'components',
     name:'components',
     type:'directory',
     path:'/src/components',
     children:[
      {id:'button',name:'Button.tsx',type:'file',path:'/src/components/Button.tsx',size:892},
      {id:'modal',name:'Modal.tsx',type:'file',path:'/src/components/Modal.tsx',modified:true,size:2341}
     ]
    }
   ]
  },
  {
   id:'assets',
   name:'assets',
   type:'directory',
   path:'/assets',
   children:[
    {id:'logo',name:'logo.png',type:'file',path:'/assets/logo.png',size:15234,mimeType:'image/png'},
    {id:'bgm',name:'bgm.mp3',type:'file',path:'/assets/bgm.mp3',size:3456789,mimeType:'audio/mpeg'}
   ]
  },
  {id:'readme',name:'README.md',type:'file',path:'/README.md',size:567},
  {id:'package',name:'package.json',type:'file',path:'/package.json',size:1892}
 ]
}
