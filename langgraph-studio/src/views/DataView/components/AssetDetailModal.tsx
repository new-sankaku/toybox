import{useState}from'react'
import ReactMarkdown from'react-markdown'
import remarkGfm from'remark-gfm'
import{Button}from'@/components/ui/Button'
import{cn}from'@/lib/utils'
import{
 Music,Play,Pause,X,Download,Check,XCircle,
 ChevronLeft,ChevronRight,RefreshCw,FileText
}from'lucide-react'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import{fileUploadApi}from'@/services/apiService'
import{type Asset,approvalStatusClasses,typeIcons}from'../types'

interface AssetDetailModalProps{
 asset:Asset
 assetIndex:number
 totalAssets:number
 playingAudio:string|null
 onClose:()=>void
 onNavigatePrev:()=>void
 onNavigateNext:()=>void
 onPlayAudio:(assetId:string,audioUrl?:string)=>void
 onApprove:(assetId:string)=>void
 onReject:(assetId:string)=>void
 onRequestRegeneration:(assetId:string,feedback:string)=>Promise<void>
}

export function AssetDetailModal({
 asset,
 assetIndex,
 totalAssets,
 playingAudio,
 onClose,
 onNavigatePrev,
 onNavigateNext,
 onPlayAudio,
 onApprove,
 onReject,
 onRequestRegeneration
}:AssetDetailModalProps):JSX.Element{
 const uiConfig=useUIConfigStore()
 const[regenFeedback,setRegenFeedback]=useState('')
 const[isSubmittingRegen,setIsSubmittingRegen]=useState(false)

 const handleRequestRegeneration=async()=>{
  if(!regenFeedback.trim()||isSubmittingRegen)return
  setIsSubmittingRegen(true)
  try{
   await onRequestRegeneration(asset.id,regenFeedback.trim())
   setRegenFeedback('')
  }finally{
   setIsSubmittingRegen(false)
  }
 }

 const Icon=typeIcons[asset.type]||FileText

 return(
  <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50 p-4">
   <div className="nier-surface-main border border-nier-border-light w-full max-w-[95vw] md:max-w-5xl max-h-[90vh] overflow-hidden flex flex-col">
    <div className="flex items-center justify-between px-4 py-3 nier-surface-header border-b border-nier-border-light flex-shrink-0">
     <div className="flex items-center gap-3">
      <button
       onClick={onNavigatePrev}
       disabled={assetIndex<=0}
       className={cn(
        "p-1 transition-colors",
        assetIndex>0?"text-nier-text-header hover:bg-white/10":"text-nier-text-light/50 cursor-not-allowed"
)}
       title="前のアセット"
      >
       <ChevronLeft size={20}/>
      </button>
      <button
       onClick={onNavigateNext}
       disabled={assetIndex>=totalAssets-1}
       className={cn(
        "p-1 transition-colors",
        assetIndex<totalAssets-1?"text-nier-text-header hover:bg-white/10":"text-nier-text-light/50 cursor-not-allowed"
)}
       title="次のアセット"
      >
       <ChevronRight size={20}/>
      </button>
      <Icon size={16} className="text-nier-text-header"/>
      <span className="text-nier-body font-medium text-nier-text-header">{asset.name}</span>
     </div>
     <div className="flex items-center gap-3">
      <span className="text-nier-small text-nier-text-header">
       {assetIndex+1}/{totalAssets}
      </span>
      <button
       onClick={()=>{onClose();setRegenFeedback('')}}
       className="p-1 hover:bg-white/10 transition-colors text-nier-text-header"
      >
       <X size={20}/>
      </button>
     </div>
    </div>

    <div className="flex-1 overflow-hidden flex">
     <div className="flex-1 overflow-auto p-6 flex items-center justify-center bg-nier-bg-selected">
      {asset.type==='image'&&asset.url&&(
       <img
        src={asset.url}
        alt={asset.name}
        className="max-w-full max-h-full object-contain"
       />
)}

      {asset.type==='audio'&&(
       <div className="flex flex-col items-center">
        <div className="w-32 h-32 rounded-full nier-surface-panel border-2 border-nier-border-dark flex items-center justify-center mb-6">
         <Music size={48} className="text-nier-text-light"/>
        </div>
        <div className="text-nier-h2 text-nier-text-main mb-2">{asset.name}</div>
        <div className="text-nier-small text-nier-text-light mb-6">
         {asset.duration}|{asset.size}
        </div>
        <button
         onClick={()=>onPlayAudio(asset.id,asset.url)}
         className="px-6 py-2 nier-surface-panel border border-nier-border-dark flex items-center gap-2 hover:bg-nier-bg-main transition-colors"
        >
         {playingAudio===asset.id?(
          <>
           <Pause size={20}/>
           停止
          </>
):(
          <>
           <Play size={20}/>
           再生
          </>
)}
        </button>
       </div>
)}

      {asset.type==='video'&&asset.url&&(
       <div className="flex flex-col items-center w-full max-w-2xl">
        <video
         src={asset.url}
         controls
         className="w-full max-h-[70vh] bg-black"
         preload="metadata"
        />
        <div className="text-nier-small text-nier-text-light mt-4">
         {asset.duration&&<span>{asset.duration}|</span>}
         {asset.size}
        </div>
       </div>
)}

      {asset.type==='document'&&(
       <div className="nier-surface-panel border border-nier-border-light p-6 prose prose-sm max-w-none w-full h-full overflow-auto">
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
            <code className="block nier-surface-main p-4 text-nier-caption font-mono overflow-x-auto">{children}</code>
):(
            <code className="nier-surface-main px-1 py-0.5 text-nier-caption font-mono">{children}</code>
)
          },
          pre:({children})=><pre className="mb-4">{children}</pre>,
          blockquote:({children})=><blockquote className="border-l-4 border-nier-border-dark pl-4 italic text-nier-text-light mb-3">{children}</blockquote>,
          table:({children})=><table className="w-full border-collapse mb-4 text-nier-small">{children}</table>,
          th:({children})=><th className="border border-nier-border-light nier-surface-panel px-3 py-2 text-left font-medium">{children}</th>,
          td:({children})=><td className="border border-nier-border-light px-3 py-2">{children}</td>,
          hr:()=><hr className="border-nier-border-light my-6"/>,
          strong:({children})=><strong className="font-medium text-nier-text-main">{children}</strong>,
          em:({children})=><em className="italic text-nier-text-light">{children}</em>,
         }}
        >
         {asset.content||''}
        </ReactMarkdown>
       </div>
)}

      {asset.type==='code'&&(
       <div className="nier-surface-panel border border-nier-border-light p-6 overflow-auto w-full h-full">
        <pre className="text-nier-small font-mono whitespace-pre-wrap text-nier-text-main">
         {asset.content||''}
        </pre>
       </div>
)}
     </div>

     <div className="w-64 flex-shrink-0 border-l border-nier-border-light overflow-y-auto nier-surface-panel">
      <div className="p-4 space-y-4">
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">タイプ</span>
        <span className="text-nier-small text-nier-text-main">
         {uiConfig.getAssetTypeLabel(asset.type)}
        </span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">状態</span>
        <span className={approvalStatusClasses[asset.approvalStatus]}>
         {uiConfig.getApprovalStatusLabel(asset.approvalStatus)}
        </span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">サイズ</span>
        <span className="text-nier-small text-nier-text-main">{asset.size}</span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">生成エージェント</span>
        <span className="text-nier-small text-nier-text-main">{asset.agent}</span>
       </div>
       <div>
        <span className="text-nier-caption text-nier-text-light block mb-1">作成日時</span>
        <span className="text-nier-small text-nier-text-main">
         {new Date(asset.createdAt).toLocaleString('ja-JP')}
        </span>
       </div>

       <div className="pt-4 border-t border-nier-border-light space-y-2">
        {asset.approvalStatus!=='approved'&&(
         <Button className="w-full" onClick={()=>onApprove(asset.id)}>
          <Check size={14} className="mr-1.5"/>
          承認
         </Button>
)}
        {asset.approvalStatus!=='rejected'&&(
         <Button
          className="w-full"
          variant="secondary"
          onClick={()=>onReject(asset.id)}
         >
          <XCircle size={14} className="mr-1.5"/>
          却下
         </Button>
)}
        <Button
         className="w-full"
         variant="secondary"
         onClick={()=>{
          const url=fileUploadApi.getDownloadUrl(asset.id)
          window.open(url,'_blank')
         }}
        >
         <Download size={14} className="mr-1.5"/>
         ダウンロード
        </Button>
       </div>

       <div className="pt-4 border-t border-nier-border-light">
        <label className="text-nier-caption text-nier-text-light block mb-2">
         再生成の指示
        </label>
        <textarea
         value={regenFeedback}
         onChange={(e)=>setRegenFeedback(e.target.value)}
         placeholder="例: 背景をもう少し暗めにして..."
         className="w-full h-24 p-2 text-nier-small nier-surface-main border border-nier-border-light resize-none focus:outline-none focus:border-nier-accent-orange"
        />
        <Button
         size="sm"
         className="w-full mt-2"
         onClick={handleRequestRegeneration}
         disabled={!regenFeedback.trim()||isSubmittingRegen}
        >
         <RefreshCw size={12} className="mr-1"/>
         再生成を依頼
        </Button>
       </div>
      </div>
     </div>
    </div>
   </div>
  </div>
)
}
