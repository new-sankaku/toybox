import{cn}from'@/lib/utils'
import{Play,Pause,Check,XCircle,CheckSquare,Square,FileText}from'lucide-react'
import{
 type Asset,
 approvalStatusClasses,
 typeIcons,
 typeColors
}from'../types'

interface AssetGridProps{
 assets:Asset[]
 selectedIds:Set<string>
 playingAudio:string|null
 onSelectAsset:(asset:Asset)=>void
 onToggleSelect:(assetId:string)=>void
 onPlayAudio:(assetId:string,audioUrl?:string)=>void
 onApprove:(assetId:string)=>void
 onReject:(assetId:string)=>void
}

export function AssetGrid({
 assets,
 selectedIds,
 playingAudio,
 onSelectAsset,
 onToggleSelect,
 onPlayAudio,
 onApprove,
 onReject
}:AssetGridProps):JSX.Element{
 return(
  <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-2">
   {assets.map(asset=>{
    const Icon=typeIcons[asset.type]||FileText
    const isSelected=selectedIds.has(asset.id)
    return(
     <div
      key={asset.id}
      className={cn(
       "nier-surface-panel border cursor-pointer hover:border-nier-accent-gold transition-colors p-2 relative",
       isSelected?"border-nier-accent-orange":"border-nier-border-light"
      )}
      onClick={()=>onSelectAsset(asset)}
     >
      <button
       onClick={(e)=>{
        e.stopPropagation()
        onToggleSelect(asset.id)
       }}
       className="absolute top-1 left-1 p-0.5 bg-nier-bg-main/80 hover:bg-nier-bg-panel transition-colors z-10"
      >
       {isSelected?<CheckSquare size={14} className="text-nier-accent-orange"/>:<Square size={14} className="text-nier-text-light"/>}
      </button>
      <div className="aspect-square bg-nier-bg-selected mb-1.5 flex items-center justify-center overflow-hidden">
       {asset.type==='image'&&asset.thumbnail?(
        <img
         src={asset.thumbnail}
         alt={asset.name}
         className="w-full h-full object-cover"
        />
       ):asset.type==='video'&&asset.url?(
        <div className="relative w-full h-full">
         <video
          src={asset.url}
          className="w-full h-full object-cover"
          muted
          preload="metadata"
         />
         <div className="absolute inset-0 flex items-center justify-center bg-black/20">
          <Play size={24} className="text-white"/>
         </div>
        </div>
       ):asset.type==='audio'?(
        <button
         onClick={(e)=>{
          e.stopPropagation()
          onPlayAudio(asset.id,asset.url)
         }}
         className="w-10 h-10 rounded-full nier-surface-panel border border-nier-border-dark flex items-center justify-center hover:bg-nier-bg-main transition-colors"
        >
         {playingAudio===asset.id?(
          <Pause size={16} className="text-nier-text-main"/>
         ):(
          <Play size={16} className="text-nier-text-main ml-0.5"/>
         )}
        </button>
       ):(
        <Icon size={24} className={typeColors[asset.type]}/>
       )}
      </div>
      <div className="text-nier-caption font-medium truncate" title={asset.name}>
       {asset.name}
      </div>
      <div className="text-[10px] text-nier-text-light mt-0.5 flex items-center justify-between">
       <span>{asset.size}</span>
       <div className="flex items-center gap-1">
        <span className={approvalStatusClasses[asset.approvalStatus]}>
         {asset.approvalStatus==='approved'?'承認':asset.approvalStatus==='rejected'?'却下':'未承認'}
        </span>
        {asset.approvalStatus!=='approved'&&(
         <button
          onClick={(e)=>{
           e.stopPropagation()
           onApprove(asset.id)
          }}
          className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-accent-green"
          title="承認"
         >
          <Check size={14}/>
         </button>
        )}
        {asset.approvalStatus!=='rejected'&&(
         <button
          onClick={(e)=>{
           e.stopPropagation()
           onReject(asset.id)
          }}
          className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-accent-red"
          title="却下"
         >
          <XCircle size={14}/>
         </button>
        )}
       </div>
      </div>
     </div>
    )
   })}
  </div>
 )
}
