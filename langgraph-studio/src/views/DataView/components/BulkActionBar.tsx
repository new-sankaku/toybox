import{Button}from'@/components/ui/Button'
import{Check,XCircle,CheckSquare,Square}from'lucide-react'

interface BulkActionBarProps{
 selectedIds:Set<string>
 isAllSelected:boolean
 isBulkUpdating:boolean
 onToggleSelectAll:()=>void
 onBulkApprove:()=>void
 onBulkReject:()=>void
 onClearSelection:()=>void
}

export function BulkActionBar({
 selectedIds,
 isAllSelected,
 isBulkUpdating,
 onToggleSelectAll,
 onBulkApprove,
 onBulkReject,
 onClearSelection
}:BulkActionBarProps):JSX.Element|null{
 if(selectedIds.size===0)return null

 return(
  <div className="px-4 py-2 nier-surface-panel border-b border-nier-border-light flex items-center gap-3">
   <button
    onClick={onToggleSelectAll}
    className="flex items-center gap-1.5 text-nier-small text-nier-text-main hover:text-nier-accent-orange transition-colors"
   >
    {isAllSelected?<CheckSquare size={14}/>:<Square size={14}/>}
    全選択
   </button>
   <span className="text-nier-small text-nier-text-light">選択中:{selectedIds.size}件</span>
   <div className="flex-1"/>
   <Button
    size="sm"
    onClick={onBulkApprove}
    disabled={isBulkUpdating}
   >
    <Check size={12} className="mr-1"/>
    一括承認
   </Button>
   <Button
    size="sm"
    variant="secondary"
    onClick={onBulkReject}
    disabled={isBulkUpdating}
   >
    <XCircle size={12} className="mr-1"/>
    一括却下
   </Button>
   <Button
    size="sm"
    variant="secondary"
    onClick={onClearSelection}
   >
    選択解除
   </Button>
  </div>
)
}
