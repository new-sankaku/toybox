import{cn}from'@/lib/utils'
import{Play,Pause,Check,XCircle,Download,CheckSquare,Square,FileText}from'lucide-react'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import{fileUploadApi}from'@/services/apiService'
import{
 type Asset,
 approvalStatusClasses,
 typeIcons,
 typeColors
}from'../types'

interface AssetListProps{
 assets:Asset[]
 selectedIds:Set<string>
 playingAudio:string|null
 isAllSelected:boolean
 onSelectAsset:(asset:Asset)=>void
 onToggleSelect:(assetId:string)=>void
 onToggleSelectAll:()=>void
 onPlayAudio:(assetId:string,audioUrl?:string)=>void
 onApprove:(assetId:string)=>void
 onReject:(assetId:string)=>void
}

export function AssetList({
 assets,
 selectedIds,
 playingAudio,
 isAllSelected,
 onSelectAsset,
 onToggleSelect,
 onToggleSelectAll,
 onPlayAudio,
 onApprove,
 onReject
}:AssetListProps):JSX.Element{
 const uiConfig=useUIConfigStore()

 return(
  <table className="w-full">
   <thead className="nier-surface-header">
    <tr>
     <th className="w-8 px-2 py-2">
      <button onClick={onToggleSelectAll}>
       {isAllSelected?
        <CheckSquare size={14} className="text-nier-accent-orange"/>:
        <Square size={14} className="text-nier-text-header"/>}
      </button>
     </th>
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
    {assets.map(asset=>{
     const Icon=typeIcons[asset.type]||FileText
     const isSelected=selectedIds.has(asset.id)
     return(
      <tr
       key={asset.id}
       className={cn(
        "hover:bg-nier-bg-panel transition-colors cursor-pointer",
        isSelected&&"bg-nier-bg-selected"
       )}
       onClick={()=>onSelectAsset(asset)}
      >
       <td className="px-2 py-3">
        <button onClick={(e)=>{e.stopPropagation();onToggleSelect(asset.id)}}>
         {isSelected?<CheckSquare size={14} className="text-nier-accent-orange"/>:<Square size={14} className="text-nier-text-light"/>}
        </button>
       </td>
       <td className="px-4 py-3">
        <div className="flex items-center gap-2">
         <Icon size={14} className={typeColors[asset.type]}/>
         <span className="text-nier-small">{asset.name}</span>
        </div>
       </td>
       <td className={cn('px-4 py-3 text-nier-small',typeColors[asset.type])}>
        {uiConfig.getAssetTypeLabel(asset.type)}
       </td>
       <td className="px-4 py-3">
        <span className={approvalStatusClasses[asset.approvalStatus]}>
         {uiConfig.getApprovalStatusLabel(asset.approvalStatus)}
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
         {asset.type==='audio'&&(
          <button
           onClick={(e)=>{e.stopPropagation();onPlayAudio(asset.id,asset.url)}}
           className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
           title={playingAudio===asset.id?'停止':'再生'}
          >
           {playingAudio===asset.id?<Pause size={14}/>:<Play size={14}/>}
          </button>
         )}
         {asset.approvalStatus!=='approved'&&(
          <button
           onClick={(e)=>{e.stopPropagation();onApprove(asset.id)}}
           className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
           title="承認"
          >
           <Check size={14}/>
          </button>
         )}
         {asset.approvalStatus!=='rejected'&&(
          <button
           onClick={(e)=>{e.stopPropagation();onReject(asset.id)}}
           className="p-1 hover:bg-nier-bg-selected transition-colors text-nier-text-light"
           title="却下"
          >
           <XCircle size={14}/>
          </button>
         )}
         <button
          onClick={(e)=>{
           e.stopPropagation()
           const url=fileUploadApi.getDownloadUrl(asset.id)
           window.open(url,'_blank')
          }}
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
 )
}
