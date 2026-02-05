import{useState,useEffect,useMemo,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{DiamondMarker}from'@/components/ui/DiamondMarker'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigationStore}from'@/stores/navigationStore'
import{useAssetStore}from'@/stores/assetStore'
import{assetApi}from'@/services/apiService'
import{FolderOpen}from'lucide-react'
import{
 type Asset,
 type AssetType,
 type ViewMode,
 type ApprovalFilter,
 convertApiAsset
}from'./types'
import{useAudioPlayer,useAssetSelection}from'./hooks'
import{
 BulkActionBar,
 FilterSidebar,
 AssetGrid,
 AssetList,
 AssetDetailModal
}from'./components'

export default function DataView():JSX.Element{
 const{currentProject}=useProjectStore()
 const{tabResetCounter}=useNavigationStore()
 const assetStoreAssets=useAssetStore(s=>s.assets)
 const setAssets=useAssetStore(s=>s.setAssets)
 const setAssetError=useAssetStore(s=>s.setError)

 const[loading,setLoading]=useState(false)
 const[filterType,setFilterType]=useState<AssetType|'all'>('all')
 const[approvalFilter,setApprovalFilter]=useState<ApprovalFilter>('pending')
 const[viewMode,setViewMode]=useState<ViewMode>('grid')
 const[selectedAsset,setSelectedAsset]=useState<Asset|null>(null)
 const[isBulkUpdating,setIsBulkUpdating]=useState(false)

 const assets=useMemo(()=>assetStoreAssets.map(convertApiAsset),[assetStoreAssets])

 const filteredAssets=useMemo(()=>assets
  .filter(a=>filterType==='all'||a.type===filterType)
  .filter(a=>approvalFilter==='all'||a.approvalStatus===approvalFilter)
 ,[assets,filterType,approvalFilter])

 const{
  audioRef,
  playingAudio,
  handlePlayAudio,
  stopAudio,
  handleEnded,
  handleError
 }=useAudioPlayer()

 const{
  selectedIds,
  toggleSelect,
  toggleSelectAll,
  clearSelection,
  isAllSelected
 }=useAssetSelection(filteredAssets)

 const selectedAssetIndex=useMemo(()=>{
  if(!selectedAsset)return-1
  return filteredAssets.findIndex(a=>a.id===selectedAsset.id)
 },[selectedAsset,filteredAssets])

 useEffect(()=>{
  setSelectedAsset(null)
  clearSelection()
  stopAudio()
 },[tabResetCounter,clearSelection,stopAudio])

 useEffect(()=>{
  if(!currentProject){
   setAssets([])
   return
  }

  const fetchAssets=async()=>{
   setLoading(true)
   try{
    const data=await assetApi.listByProject(currentProject.id)
    setAssets(data)
   }catch(error){
    console.error('Failed to fetch assets:',error)
    setAssetError(error instanceof Error?error.message:'アセットの取得に失敗しました')
   }finally{
    setLoading(false)
   }
  }

  fetchAssets()
 },[currentProject?.id])

 const refreshAssets=useCallback(async()=>{
  if(!currentProject)return
  try{
   const data=await assetApi.listByProject(currentProject.id)
   setAssets(data)
  }catch(error){
   console.error('Failed to refresh assets:',error)
  }
 },[currentProject])

 const navigateToPrev=useCallback(()=>{
  if(selectedAssetIndex>0){
   setSelectedAsset(filteredAssets[selectedAssetIndex-1])
  }
 },[selectedAssetIndex,filteredAssets])

 const navigateToNext=useCallback(()=>{
  if(selectedAssetIndex<filteredAssets.length-1){
   setSelectedAsset(filteredAssets[selectedAssetIndex+1])
  }else{
   setSelectedAsset(null)
  }
 },[selectedAssetIndex,filteredAssets])

 const handleApprove=useCallback(async(assetId:string)=>{
  if(!currentProject)return
  try{
   await assetApi.updateStatus(currentProject.id,assetId,'approved')
   await refreshAssets()
   if(selectedAsset?.id===assetId){
    navigateToNext()
   }
  }catch(error){
   console.error('Failed to approve asset:',error)
  }
 },[currentProject,refreshAssets,selectedAsset,navigateToNext])

 const handleReject=useCallback(async(assetId:string)=>{
  if(!currentProject)return
  try{
   await assetApi.updateStatus(currentProject.id,assetId,'rejected')
   await refreshAssets()
   if(selectedAsset?.id===assetId){
    navigateToNext()
   }
  }catch(error){
   console.error('Failed to reject asset:',error)
  }
 },[currentProject,refreshAssets,selectedAsset,navigateToNext])

 const handleBulkApprove=useCallback(async()=>{
  if(!currentProject||selectedIds.size===0||isBulkUpdating)return
  setIsBulkUpdating(true)
  try{
   await assetApi.bulkUpdateStatus(currentProject.id,Array.from(selectedIds),'approved')
   await refreshAssets()
   clearSelection()
  }catch(error){
   console.error('Failed to bulk approve:',error)
  }finally{
   setIsBulkUpdating(false)
  }
 },[currentProject,selectedIds,isBulkUpdating,refreshAssets,clearSelection])

 const handleBulkReject=useCallback(async()=>{
  if(!currentProject||selectedIds.size===0||isBulkUpdating)return
  setIsBulkUpdating(true)
  try{
   await assetApi.bulkUpdateStatus(currentProject.id,Array.from(selectedIds),'rejected')
   await refreshAssets()
   clearSelection()
  }catch(error){
   console.error('Failed to bulk reject:',error)
  }finally{
   setIsBulkUpdating(false)
  }
 },[currentProject,selectedIds,isBulkUpdating,refreshAssets,clearSelection])

 const handleRequestRegeneration=useCallback(async(assetId:string,feedback:string)=>{
  if(!currentProject)return
  await assetApi.requestRegeneration(currentProject.id,assetId,feedback)
  await refreshAssets()
  navigateToNext()
 },[currentProject,refreshAssets,navigateToNext])

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

 const assetCounts={
  all:assets.length,
  image:assets.filter(a=>a.type==='image').length,
  audio:assets.filter(a=>a.type==='audio').length,
  video:assets.filter(a=>a.type==='video').length,
  document:assets.filter(a=>a.type==='document').length,
  code:assets.filter(a=>a.type==='code').length
 }

 const approvalCounts={
  all:assets.length,
  approved:assets.filter(a=>a.approvalStatus==='approved').length,
  pending:assets.filter(a=>a.approvalStatus==='pending').length,
  rejected:assets.filter(a=>a.approvalStatus==='rejected').length
 }

 return(
  <div className="p-4 animate-nier-fade-in h-full flex gap-3 overflow-hidden">
   <Card className="flex-1 flex flex-col overflow-hidden">
    <CardHeader className="flex-shrink-0">
     <DiamondMarker>アセット一覧</DiamondMarker>
     <span className="text-nier-caption text-nier-text-light ml-2">
      ({filteredAssets.length}件)
     </span>
    </CardHeader>
    <BulkActionBar
     selectedIds={selectedIds}
     isAllSelected={isAllSelected}
     isBulkUpdating={isBulkUpdating}
     onToggleSelectAll={toggleSelectAll}
     onBulkApprove={handleBulkApprove}
     onBulkReject={handleBulkReject}
     onClearSelection={clearSelection}
    />
    <CardContent className="flex-1 overflow-y-auto">
     {loading&&assets.length===0?(
      <div className="text-center py-8 text-nier-text-light">
       <p className="text-nier-small">読み込み中...</p>
      </div>
):filteredAssets.length===0?(
      <div className="text-center py-12 text-nier-text-light">
       <FolderOpen size={40} className="mx-auto mb-3 opacity-50"/>
       <p className="text-nier-body mb-1">アセットがありません</p>
       <p className="text-nier-caption">プロジェクトを実行すると、AIが生成した画像・音声・コードなどがここに表示されます</p>
      </div>
):viewMode==='grid'?(
      <AssetGrid
       assets={filteredAssets}
       selectedIds={selectedIds}
       playingAudio={playingAudio}
       onSelectAsset={setSelectedAsset}
       onToggleSelect={toggleSelect}
       onPlayAudio={handlePlayAudio}
       onApprove={handleApprove}
       onReject={handleReject}
      />
):(
      <AssetList
       assets={filteredAssets}
       selectedIds={selectedIds}
       playingAudio={playingAudio}
       isAllSelected={isAllSelected}
       onSelectAsset={setSelectedAsset}
       onToggleSelect={toggleSelect}
       onToggleSelectAll={toggleSelectAll}
       onPlayAudio={handlePlayAudio}
       onApprove={handleApprove}
       onReject={handleReject}
      />
)}
    </CardContent>
   </Card>

   <FilterSidebar
    filterType={filterType}
    approvalFilter={approvalFilter}
    viewMode={viewMode}
    assetCounts={assetCounts}
    approvalCounts={approvalCounts}
    onFilterTypeChange={setFilterType}
    onApprovalFilterChange={setApprovalFilter}
    onViewModeChange={setViewMode}
   />

   {selectedAsset&&(
    <AssetDetailModal
     asset={selectedAsset}
     assetIndex={selectedAssetIndex}
     totalAssets={filteredAssets.length}
     playingAudio={playingAudio}
     onClose={()=>setSelectedAsset(null)}
     onNavigatePrev={navigateToPrev}
     onNavigateNext={navigateToNext}
     onPlayAudio={handlePlayAudio}
     onApprove={handleApprove}
     onReject={handleReject}
     onRequestRegeneration={handleRequestRegeneration}
    />
)}

   <audio
    ref={audioRef}
    onEnded={handleEnded}
    onError={handleError}
   />
  </div>
)
}
