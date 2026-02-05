import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{cn}from'@/lib/utils'
import{FolderOpen,Grid,List}from'lucide-react'
import{useUIConfigStore}from'@/stores/uiConfigStore'
import{
 type AssetType,
 type ViewMode,
 type ApprovalFilter,
 typeIcons
}from'../types'

interface FilterSidebarProps{
 filterType:AssetType|'all'
 approvalFilter:ApprovalFilter
 viewMode:ViewMode
 assetCounts:{all:number;image:number;audio:number;video:number;document:number;code:number}
 approvalCounts:{all:number;approved:number;pending:number;rejected:number}
 onFilterTypeChange:(type:AssetType|'all')=>void
 onApprovalFilterChange:(filter:ApprovalFilter)=>void
 onViewModeChange:(mode:ViewMode)=>void
}

export function FilterSidebar({
 filterType,
 approvalFilter,
 viewMode,
 assetCounts,
 approvalCounts,
 onFilterTypeChange,
 onApprovalFilterChange,
 onViewModeChange
}:FilterSidebarProps):JSX.Element{
 const uiConfig=useUIConfigStore()

 return(
  <div className="w-40 md:w-48 flex-shrink-0 flex flex-col gap-3 overflow-y-auto">
   <Card>
    <CardHeader>
     <DiamondMarker>タイプ</DiamondMarker>
    </CardHeader>
    <CardContent className="py-2">
     <div className="flex flex-col gap-1">
      {(['all','image','audio','video','document','code']as const).map(type=>{
       const Icon=type==='all'?FolderOpen:typeIcons[type]
       const label=type==='all'?'全て':uiConfig.getAssetTypeLabel(type)
       const count=assetCounts[type]
       return(
        <button
         key={type}
         className={cn(
          'flex items-center gap-2 px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
          filterType===type
           ?'nier-surface-selected'
           :'text-nier-text-light hover:bg-nier-bg-panel'
         )}
         onClick={()=>onFilterTypeChange(type)}
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

   <Card>
    <CardHeader>
     <DiamondMarker>承認状態</DiamondMarker>
    </CardHeader>
    <CardContent className="py-2">
     <div className="flex flex-col gap-1">
      {(['all','pending','approved','rejected']as const).map(status=>{
       const label=status==='all'?'全状態':uiConfig.getApprovalStatusLabel(status)
       const count=approvalCounts[status]
       return(
        <button
         key={status}
         className={cn(
          'flex items-center justify-between px-2 py-1.5 text-nier-small tracking-nier transition-colors text-left',
          approvalFilter===status
           ?'nier-surface-selected'
           :'text-nier-text-light hover:bg-nier-bg-panel'
         )}
         onClick={()=>onApprovalFilterChange(status)}
        >
         <span>{label}</span>
         <span className="text-nier-caption opacity-70">({count})</span>
        </button>
       )
      })}
     </div>
    </CardContent>
   </Card>

   <Card>
    <CardHeader>
     <DiamondMarker>表示</DiamondMarker>
    </CardHeader>
    <CardContent className="py-2">
     <div className="flex items-center gap-1">
      <button
       onClick={()=>onViewModeChange('grid')}
       className={cn(
        'flex-1 flex items-center justify-center gap-1 p-1.5 transition-colors text-nier-small',
        viewMode==='grid'?'nier-surface-selected':'text-nier-text-light hover:bg-nier-bg-hover'
       )}
      >
       <Grid size={14}/>
       グリッド
      </button>
      <button
       onClick={()=>onViewModeChange('list')}
       className={cn(
        'flex-1 flex items-center justify-center gap-1 p-1.5 transition-colors text-nier-small',
        viewMode==='list'?'nier-surface-selected':'text-nier-text-light hover:bg-nier-bg-hover'
       )}
      >
       <List size={14}/>
       リスト
      </button>
     </div>
    </CardContent>
   </Card>
  </div>
 )
}
