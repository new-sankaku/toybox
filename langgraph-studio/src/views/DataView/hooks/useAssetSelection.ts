import{useState,useCallback}from'react'
import{type Asset}from'../types'

export function useAssetSelection(filteredAssets:Asset[]){
 const[selectedIds,setSelectedIds]=useState<Set<string>>(new Set())

 const toggleSelect=useCallback((assetId:string)=>{
  setSelectedIds(prev=>{
   const next=new Set(prev)
   if(next.has(assetId)){
    next.delete(assetId)
   }else{
    next.add(assetId)
   }
   return next
  })
 },[])

 const toggleSelectAll=useCallback(()=>{
  if(selectedIds.size===filteredAssets.length){
   setSelectedIds(new Set())
  }else{
   setSelectedIds(new Set(filteredAssets.map(a=>a.id)))
  }
 },[filteredAssets,selectedIds.size])

 const clearSelection=useCallback(()=>{
  setSelectedIds(new Set())
 },[])

 const isAllSelected=selectedIds.size===filteredAssets.length&&filteredAssets.length>0

 return{
  selectedIds,
  setSelectedIds,
  toggleSelect,
  toggleSelectAll,
  clearSelection,
  isAllSelected
 }
}
