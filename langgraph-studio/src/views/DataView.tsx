import{useState,useEffect,useRef}from'react'
import ReactMarkdown from'react-markdown'
import remarkGfm from'remark-gfm'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{Button}from'@/components/ui/Button'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{assetApi,fileUploadApi,type ApiAsset}from'@/services/apiService'
import{cn}from'@/lib/utils'
import{
 Image,
 Music,
 FileText,
 Code,
 Download,
 Play,
 Pause,
 Eye,
 X,
 FolderOpen,
 Grid,
 List,
 Check,
 XCircle
}from'lucide-react'

type AssetType='image'|'audio'|'document'|'code'|'other'
type ViewMode='grid'|'list'
type ApprovalStatus='approved'|'pending'|'rejected'
type ApprovalFilter='all'|'approved'|'pending'|'rejected'

interface Asset{
 id:string
 name:string
 type:AssetType
 agent:string
 size:string
 createdAt:string
 url?:string
 thumbnail?:string
 duration?:string
 content?:string
 approvalStatus:ApprovalStatus
}

function convertApiAsset(apiAsset:ApiAsset):Asset{
 return{
  id:apiAsset.id,
  name:apiAsset.name,
  type:apiAsset.type,
  agent:apiAsset.agent,
  size:apiAsset.size,
  createdAt:apiAsset.createdAt,
  url:apiAsset.url||undefined,
  thumbnail:apiAsset.thumbnail||undefined,
  duration:apiAsset.duration||undefined,
  content:apiAsset.content||undefined,
  approvalStatus:apiAsset.approvalStatus,
 }
}

const approvalStatusLabels:Record<ApprovalStatus,string>={
 approved:'承認済',
 pending:'未承認',
 rejected:'却下'
}


const approvalBgColors:Record<ApprovalStatus,string>={
 approved:'bg-nier-bg-selected border-nier-border-light',
 pending:'bg-nier-bg-selected border-nier-border-light',
 rejected:'bg-nier-bg-selected border-nier-border-light'
}

const typeIcons:Record<AssetType,typeof Image>={
 image:Image,
 audio:Music,
 document:FileText,
 code:Code,
 other:FolderOpen
}

const typeLabels:Record<AssetType,string>={
 image:'画像',
 audio:'音声',
 document:'ドキュメント',
 code:'コード',
 other:'その他'
}

const typeColors:Record<AssetType,string>={
 image:'text-nier-text-light',
 audio:'text-nier-text-light',
 document:'text-nier-text-light',
 code:'text-nier-text-light',
 other:'text-nier-text-light'
}

export default function DataView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{tabResetCounter}=useNavigationStore()
 const[assets,setAssets]=useState<Asset[]>([])
 const[loading,setLoading]=useState(false)
 const[filterType,setFilterType]=useState<AssetType|'all'>('all')
 const[approvalFilter,setApprovalFilter]=useState<ApprovalFilter>('pending')
 const[viewMode,setViewMode]=useState<ViewMode>('grid')
 const[selectedAsset,setSelectedAsset]=useState<Asset|null>(null)
 const[playingAudio,setPlayingAudio]=useState<string|null>(null)
 const audioRef=useRef<HTMLAudioElement|null>(null)

 useEffect(()=>{
  setSelectedAsset(null)
  if(audioRef.current){
   audioRef.current.pause()
  }
  setPlayingAudio(null)
 },[tabResetCounter])

 useEffect(()=>{
  if(!currentProject){
   setAssets([])
   return
  }

  const fetchAssets=async()=>{
   setLoading(true)
   try{
    const data=await assetApi.listByProject(currentProject.id)
    setAssets(data.map(convertApiAsset))
   }catch(error){
    console.error('Failed to fetch assets:',error)
    setAssets([])
   }finally{
    setLoading(false)
   }
  }

  fetchAssets()
 },[currentProject?.id])

 if(!currentProject){
  return(
   <div className="p-4 animate-nier-fade-in">
    <Card>
     <CardContent>
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={48} className="mx-auto mb-4 opacity-50"/>
       <p className="text-nier-body">プロジェクトを選択してください</p>
      </div>
     </CardContent>
    </Card>
   </div>
)
 }

 const filteredAssets=assets
  .filter(a=>filterType==='all'||a.type===filterType)
  .filter(a=>approvalFilter==='all'||a.approvalStatus===approvalFilter)

 const assetCounts={
  all:assets.length,
  image:assets.filter(a=>a.type==='image').length,
  audio:assets.filter(a=>a.type==='audio').length,
  document:assets.filter(a=>a.type==='document').length,
  code:assets.filter(a=>a.type==='code').length
 }

 const approvalCounts={
  all:assets.length,
  approved:assets.filter(a=>a.approvalStatus==='approved').length,
  pending:assets.filter(a=>a.approvalStatus==='pending').length,
  rejected:assets.filter(a=>a.approvalStatus==='rejected').length
 }

 const handlePlayAudio=(assetId:string,audioUrl?:string)=>{
  if(playingAudio===assetId){
   if(audioRef.current){
    audioRef.current.pause()
    audioRef.current.currentTime=0
   }
   setPlayingAudio(null)
  }else{
   if(audioRef.current&&audioUrl){
    const fullUrl=audioUrl.startsWith('http')
     ?audioUrl
     : `http://localhost:8000${audioUrl}`
    audioRef.current.src=fullUrl
    audioRef.current.play().catch(err=>{
     console.error('Failed to play audio:',err)
    })
   }
   setPlayingAudio(assetId)
  }
 }

 const selectNextPending=(updatedAssets:Asset[],currentId:string)=>{
  const pendingAssets=updatedAssets.filter(
   a=>a.approvalStatus==='pending'&&a.id!==currentId
)
  if(pendingAssets.length>0){
   const nextPending=pendingAssets.reduce((oldest,current)=>
    new Date(oldest.createdAt)<new Date(current.createdAt)?oldest : current
)
   setSelectedAsset(nextPending)
  }else{
   setSelectedAsset(null)
  }
 }

 const handleApprove=async(assetId:string)=>{
  if(!currentProject)return
  const currentId=assetId
  try{
   await assetApi.updateStatus(currentProject.id,assetId,'approved')
   const data=await assetApi.listByProject(currentProject.id)
   const updatedAssets=data.map(convertApiAsset)
   setAssets(updatedAssets)
   if(selectedAsset?.id===assetId){
    selectNextPending(updatedAssets,currentId)
   }
  }catch(error){
   console.error('Failed to approve asset:',error)
  }
 }

 const handleReject=async(assetId:string)=>{
  if(!currentProject)return
  const currentId=assetId
  try{
   await assetApi.updateStatus(currentProject.id,assetId,'rejected')
   const data=await assetApi.listByProject(currentProject.id)
   const updatedAssets=data.map(convertApiAsset)
   setAssets(updatedAssets)
   if(selectedAsset?.id===assetId){
    selectNextPending(updatedAssets,currentId)
   }
  }catch(error){
   console.error('Failed to reject asset:',error)
  }
 }

 return(
  <div className="p-4 animate-nier-fade-in h-full flex gap-3">
   {/*Asset Grid/List-Main Content*/}
   <Card className="flex-1 flex flex-col overflow-hidden">
    <CardHeader className="flex-shrink-0">
     <DiamondMarker>アセット一覧</DiamondMarker>
     <span className="text-nier-caption text-nier-text-light ml-2">
      ({filteredAssets.length}件)
     </span>
    </CardHeader>
    <CardContent className="flex-1 overflow-y-auto">
     {loading&&assets.length===0?(
      <div className="text-center py-8 text-nier-text-light">
       <p className="text-nier-small">読み込み中...</p>
      </div>
):filteredAssets.length===0?(
      <div className="text-center py-8 text-nier-text-light">
       <FolderOpen size={32} className="mx-auto mb-2 opacity-50"/>
       <p className="text-nier-small">アセットがありません</p>
      </div>
):viewMode==='grid'?(
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
     {filteredAssets.map(asset=>{
      const Icon=typeIcons[asset.type]||FolderOpen
      return(
       <div
        key={asset.id}
        className="bg-nier-bg-panel border border-nier-border-light cursor-pointer hover:border-nier-accent-gold transition-colors p-2"
        onClick={()=>setSelectedAsset(asset)}
       >
        {/*Thumbnail/Icon*/}
        <div className="aspect-square bg-nier-bg-selected mb-1.5 flex items-center justify-center overflow-hidden">
         {asset.type==='image'&&asset.thumbnail?(
          <img
           src={asset.thumbnail}
           alt={asset.name}
           className="w-full h-full object-cover"
          />
) : asset.type==='audio'?(
          <button
           onClick={(e)=>{
            e.stopPropagation()
            handlePlayAudio(asset.id,asset.url)
           }}
           className="w-10 h-10 rounded-full bg-nier-bg-panel border border-nier-border-dark flex items-center justify-center hover:bg-nier-bg-main transition-colors"
          >
           {playingAudio===asset.id?(
            <Pause size={16} className="text-nier-text-main"/>
) : (
            <Play size={16} className="text-nier-text-main ml-0.5"/>
)}
          </button>
) : (
          <Icon size={24} className={typeColors[asset.type]}/>
)}
        </div>

        {/*Info*/}
        <div className="text-nier-caption font-medium truncate" title={asset.name}>
         {asset.name}
        </div>

        {/*Size+Status+Actions in one row*/}
        <div className="text-[10px] text-nier-text-light mt-0.5 flex items-center justify-between">
         <span>{asset.size}</span>
         <div className="flex items-center gap-1">
          <span className="text-[10px] px-1 py-0.5 border bg-nier-bg-selected border-nier-border-light text-nier-text-light">
           {asset.approvalStatus==='approved'?'承認' : asset.approvalStatus==='rejected'?'却下' : '未承認'}
          </span>
          {asset.approvalStatus!=='approved'&&(
           <button
            onClick={(e)=>{
             e.stopPropagation()
             handleApprove(asset.id)
            }}
            className="p-0.5 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
            title="承認"
           >
            <Check size={12}/>
           </button>
)}
          {asset.approvalStatus!=='rejected'&&(
           <button
            onClick={(e)=>{
             e.stopPropagation()
             handleReject(asset.id)
            }}
            className="p-0.5 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
            title="却下"
           >
            <XCircle size={12}/>
           </button>
)}
         </div>
        </div>
       </div>
)
     })}
      </div>
):(
      <table className="w-full">
       <thead className="bg-nier-bg-header text-nier-text-header">
        <tr>
         <th className="px-4 py-2 text-left text-nier-small tracking-nier">ファイル名</th>
         <th className="px-4 py-2 text-left text-nier-small tracking-nier">タイプ</th>
         <th className="px-4 py-2 text-left text-nier-small tracking-nier">状態</th>
         <th className="px-4 py-2 text-left text-nier-small tracking-nier">エージェント</th>
         <th className="px-4 py-2 text-left text-nier-small tracking-nier">サイズ</th>
         <th className="px-4 py-2 text-left text-nier-small tracking-nier">作成日時</th>
         <th className="px-4 py-2 text-left text-nier-small tracking-nier">操作</th>
        </tr>
       </thead>
       <tbody className="divide-y divide-nier-border-light">
        {filteredAssets.map(asset=>{
         const Icon=typeIcons[asset.type]||FolderOpen
         return(
          <tr key={asset.id} className="hover:bg-nier-bg-panel transition-colors">
           <td className="px-4 py-3">
            <div className="flex items-center gap-2">
             <Icon size={14} className={typeColors[asset.type]}/>
             <span className="text-nier-small">{asset.name}</span>
            </div>
           </td>
           <td className={cn('px-4 py-3 text-nier-small',typeColors[asset.type])}>
            {typeLabels[asset.type]}
           </td>
           <td className="px-4 py-3">
            <span className={cn('text-nier-caption px-1.5 py-0.5 border',approvalBgColors[asset.approvalStatus])}>
             {approvalStatusLabels[asset.approvalStatus]}
            </span>
           </td>
           <td className="px-4 py-3 text-nier-small text-nier-text-light">
            {asset.agent}
           </td>
           <td className="px-4 py-3 text-nier-small text-nier-text-light">
            {asset.size}
            {asset.duration&&` (${asset.duration})`}
           </td>
           <td className="px-4 py-3 text-nier-small text-nier-text-light">
            {new Date(asset.createdAt).toLocaleString('ja-JP')}
           </td>
           <td className="px-4 py-3">
            <div className="flex items-center gap-2">
             <button
              onClick={()=>setSelectedAsset(asset)}
              className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
              title="プレビュー"
             >
              <Eye size={14}/>
             </button>
             {asset.type==='audio'&&(
              <button
               onClick={()=>handlePlayAudio(asset.id,asset.url)}
               className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
               title={playingAudio===asset.id?'停止' : '再生'}
              >
               {playingAudio===asset.id?<Pause size={14}/>:<Play size={14}/>}
              </button>
)}
             {asset.approvalStatus!=='approved'&&(
              <button
               onClick={()=>handleApprove(asset.id)}
               className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
               title="承認"
              >
               <Check size={14}/>
              </button>
)}
             {asset.approvalStatus!=='rejected'&&(
              <button
               onClick={()=>handleReject(asset.id)}
               className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
               title="却下"
              >
               <XCircle size={14}/>
              </button>
)}
             <button
              className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light hover:text-nier-text-main"
              title="ダウンロード"
             >
              <Download size={14}/>
             </button>
            </div>
           </td>
          </tr>
)
        })}
       </tbody>
      </table>
)}
    </CardContent>
   </Card>

   {/*Filter Sidebar*/}
   <div className="w-40 md:w-48 flex-shrink-0 flex flex-col gap-3">
    {/*Type Filter*/}
    <Card>
     <CardHeader>
      <DiamondMarker>タイプ</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex flex-col gap-1">
       {(['all','image','audio','document','code']as const).map(type=>{
        const Icon=type==='all'?FolderOpen : typeIcons[type]
        const label=type==='all'?'全て' : typeLabels[type]
        const count=assetCounts[type]
        return(
         <button
          key={type}
          className={cn(
           'flex items-center gap-2 px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
           filterType===type
            ?'bg-nier-bg-selected text-nier-text-main'
            : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
          onClick={()=>setFilterType(type)}
         >
          <Icon size={14}/>
          <span className="flex-1">{label}</span>
          <span className="text-nier-caption opacity-70">({count})</span>
         </button>
)
       })}
      </div>
     </CardContent>
    </Card>

    {/*Approval Filter*/}
    <Card>
     <CardHeader>
      <DiamondMarker>承認状態</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex flex-col gap-1">
       {(['all','pending','approved','rejected']as const).map(status=>{
        const label=status==='all'?'全状態' : approvalStatusLabels[status]
        const count=approvalCounts[status]
        return(
         <button
          key={status}
          className={cn(
           'flex items-center justify-between px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
           approvalFilter===status
            ?'bg-nier-bg-selected text-nier-text-main'
            : 'text-nier-text-light hover:bg-nier-bg-panel'
)}
          onClick={()=>setApprovalFilter(status)}
         >
          <span>{label}</span>
          <span className="text-nier-caption opacity-70">({count})</span>
         </button>
)
       })}
      </div>
     </CardContent>
    </Card>

    {/*View Mode*/}
    <Card>
     <CardHeader>
      <DiamondMarker>表示</DiamondMarker>
     </CardHeader>
     <CardContent className="py-2">
      <div className="flex items-center gap-1">
       <button
        onClick={()=>setViewMode('grid')}
        className={cn(
         'flex-1 flex items-center justify-center gap-1 p-1.5 transition-colors text-nier-small',
         viewMode==='grid'?'bg-nier-bg-selected text-nier-text-main' : 'text-nier-text-light hover:bg-nier-bg-hover'
)}
       >
        <Grid size={14}/>
        グリッド
       </button>
       <button
        onClick={()=>setViewMode('list')}
        className={cn(
         'flex-1 flex items-center justify-center gap-1 p-1.5 transition-colors text-nier-small',
         viewMode==='list'?'bg-nier-bg-selected text-nier-text-main' : 'text-nier-text-light hover:bg-nier-bg-hover'
)}
       >
        <List size={14}/>
        リスト
       </button>
      </div>
     </CardContent>
    </Card>
   </div>

   {/*Preview Modal*/}
   {selectedAsset&&(
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
     <div className="bg-nier-bg-main border border-nier-border-light w-full max-w-[95vw] md:max-w-4xl max-h-[90vh] overflow-hidden">
      {/*Modal Header*/}
      <div className="flex items-center justify-between px-4 py-3 bg-nier-bg-header border-b border-nier-border-light">
       <div className="flex items-center gap-2">
        {(()=>{
         const Icon=typeIcons[selectedAsset.type]||FolderOpen
         return<Icon size={16} className={typeColors[selectedAsset.type]}/>
        })()}
        <span className="text-nier-body font-medium text-nier-text-header">{selectedAsset.name}</span>
       </div>
       <button
        onClick={()=>setSelectedAsset(null)}
        className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-header"
       >
        <X size={20}/>
       </button>
      </div>

      {/*Modal Content*/}
      <div className="p-6 overflow-auto max-h-[calc(90vh-60px)]">
       {selectedAsset.type==='image'&&selectedAsset.url&&(
        <div className="flex flex-col items-center">
         <img
          src={selectedAsset.url}
          alt={selectedAsset.name}
          className="max-w-full max-h-[60vh] object-contain"
         />
        </div>
)}

       {selectedAsset.type==='audio'&&(
        <div className="flex flex-col items-center py-12">
         <div className="w-32 h-32 rounded-full bg-nier-bg-selected border-2 border-nier-border-dark flex items-center justify-center mb-6">
          <Music size={48} className="text-nier-text-light"/>
         </div>
         <div className="text-nier-h2 text-nier-text-main mb-2">{selectedAsset.name}</div>
         <div className="text-nier-small text-nier-text-light mb-6">
          {selectedAsset.duration}|{selectedAsset.size}
         </div>
         <button
          onClick={()=>handlePlayAudio(selectedAsset.id,selectedAsset.url)}
          className="px-6 py-2 bg-nier-bg-panel border border-nier-border-dark text-nier-text-main flex items-center gap-2 hover:bg-nier-bg-selected transition-colors"
         >
          {playingAudio===selectedAsset.id?(
           <>
            <Pause size={20}/>
            停止
           </>
) : (
           <>
            <Play size={20}/>
            再生
           </>
)}
         </button>
        </div>
)}

       {selectedAsset.type==='document'&&(
        <div className="bg-nier-bg-panel border border-nier-border-light p-6 prose prose-sm max-w-none">
         <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
           h1:({children})=><h1 className="text-nier-h1 font-medium text-nier-text-main mb-4 border-b border-nier-border-light pb-2">{children}</h1>,
           h2:({children})=><h2 className="text-nier-h2 font-medium text-nier-text-main mt-6 mb-3">{children}</h2>,
           h3:({children})=><h3 className="text-nier-body font-medium text-nier-text-main mt-4 mb-2">{children}</h3>,
           p:({children})=><p className="text-nier-small text-nier-text-main mb-3 leading-relaxed">{children}</p>,
           ul:({children})=><ul className="list-disc list-inside text-nier-small text-nier-text-main mb-3 space-y-1">{children}</ul>,
           ol:({children})=><ol className="list-decimal list-inside text-nier-small text-nier-text-main mb-3 space-y-1">{children}</ol>,
           li:({children})=><li className="text-nier-text-main">{children}</li>,
           a:({href,children})=><a href={href} className="text-nier-text-main hover:underline">{children}</a>,
           code:({children,className})=>{
            const isBlock=className?.includes('language-')
            return isBlock?(
             <code className="block bg-nier-bg-main p-4 text-nier-caption font-mono text-nier-text-main overflow-x-auto">{children}</code>
) : (
             <code className="bg-nier-bg-main px-1 py-0.5 text-nier-caption font-mono text-nier-text-main">{children}</code>
)
           },
           pre:({children})=><pre className="mb-4">{children}</pre>,
           blockquote:({children})=><blockquote className="border-l-4 border-nier-border-dark pl-4 italic text-nier-text-light mb-3">{children}</blockquote>,
           table:({children})=><table className="w-full border-collapse mb-4 text-nier-small">{children}</table>,
           th:({children})=><th className="border border-nier-border-light bg-nier-bg-panel px-3 py-2 text-left font-medium">{children}</th>,
           td:({children})=><td className="border border-nier-border-light px-3 py-2">{children}</td>,
           hr:()=><hr className="border-nier-border-light my-6"/>,
           strong:({children})=><strong className="font-medium text-nier-text-main">{children}</strong>,
           em:({children})=><em className="italic text-nier-text-light">{children}</em>,
          }}
         >
          {selectedAsset.content||`# ${selectedAsset.name}\n\nコンテンツが利用できません。`}
         </ReactMarkdown>
        </div>
)}

       {selectedAsset.type==='code'&&(
        <div className="bg-nier-bg-panel border border-nier-border-light p-6 overflow-auto max-h-[60vh]">
         <pre className="text-nier-small font-mono whitespace-pre-wrap text-nier-text-main">
          {selectedAsset.content||`// ${selectedAsset.name}\n\n// コンテンツが利用できません`}
         </pre>
        </div>
)}

       {/*Asset Info*/}
       <div className="mt-6 pt-6 border-t border-nier-border-light">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4 text-nier-small">
         <div>
          <span className="text-nier-text-light block">タイプ</span>
          <span className={typeColors[selectedAsset.type]}>
           {typeLabels[selectedAsset.type]}
          </span>
         </div>
         <div>
          <span className="text-nier-text-light block">状態</span>
          <span className={cn('px-1.5 py-0.5 border inline-block',approvalBgColors[selectedAsset.approvalStatus])}>
           {approvalStatusLabels[selectedAsset.approvalStatus]}
          </span>
         </div>
         <div>
          <span className="text-nier-text-light block">サイズ</span>
          <span className="text-nier-text-main">{selectedAsset.size}</span>
         </div>
         <div>
          <span className="text-nier-text-light block">生成エージェント</span>
          <span className="text-nier-text-main">{selectedAsset.agent}</span>
         </div>
         <div>
          <span className="text-nier-text-light block">作成日時</span>
          <span className="text-nier-text-main">{new Date(selectedAsset.createdAt).toLocaleString('ja-JP')}</span>
         </div>
        </div>
       </div>

       {/*Actions*/}
       <div className="mt-6 flex gap-3">
        {selectedAsset.approvalStatus!=='approved'&&(
         <Button onClick={()=>handleApprove(selectedAsset.id)}>
          <Check size={14} className="mr-1.5"/>
          承認
         </Button>
)}
        {selectedAsset.approvalStatus!=='rejected'&&(
         <Button
          variant="secondary"
          onClick={()=>handleReject(selectedAsset.id)}
         >
          <XCircle size={14} className="mr-1.5"/>
          却下
         </Button>
)}
        <Button
         variant="secondary"
         onClick={()=>{
          const url=fileUploadApi.getDownloadUrl(selectedAsset.id)
          window.open(url,'_blank')
         }}
        >
         <Download size={14} className="mr-1.5"/>
         ダウンロード
        </Button>
        <Button variant="secondary" onClick={()=>setSelectedAsset(null)}>
         閉じる
        </Button>
       </div>
      </div>
     </div>
    </div>
)}

   {/*Hidden audio element for playback*/}
   <audio
    ref={audioRef}
    onEnded={()=>setPlayingAudio(null)}
    onError={(e)=>{
     console.error('Audio error:',e)
     setPlayingAudio(null)
    }}
   />
  </div>
)
}
