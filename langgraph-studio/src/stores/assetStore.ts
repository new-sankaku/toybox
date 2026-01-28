import{create}from'zustand'
import type{ApiAsset}from'@/services/apiService'

interface AssetState{
 assets:ApiAsset[]
 isLoading:boolean
 error:string|null
 setAssets:(assets:ApiAsset[])=>void
 addAsset:(asset:ApiAsset)=>void
 updateAsset:(id:string,updates:Partial<ApiAsset>)=>void
 addOrUpdateAsset:(asset:ApiAsset)=>void
 setLoading:(loading:boolean)=>void
 setError:(error:string|null)=>void
 reset:()=>void
 getAssetsByProject:(projectId:string)=>ApiAsset[]
 getPendingCount:()=>number
}

export const useAssetStore=create<AssetState>((set,get)=>({
 assets:[],
 isLoading:false,
 error:null,

 setAssets:(assets)=>set({assets}),

 addAsset:(asset)=>
  set((state)=>({
   assets:[...state.assets,asset]
  })),

 updateAsset:(id,updates)=>
  set((state)=>({
   assets:state.assets.map((asset)=>
    asset.id===id?{...asset,...updates}:asset
)
  })),

 addOrUpdateAsset:(asset)=>
  set((state)=>{
   const idx=state.assets.findIndex(a=>a.id===asset.id)
   if(idx>=0){
    const updated=[...state.assets]
    updated[idx]={...updated[idx],...asset}
    return{assets:updated}
   }
   return{assets:[...state.assets,asset]}
  }),

 setLoading:(loading)=>set({isLoading:loading}),

 setError:(error)=>set({error}),

 reset:()=>set({
  assets:[],
  isLoading:false,
  error:null
 }),

 getAssetsByProject:(projectId)=>{
  return get().assets.filter((asset)=>
   asset.id.startsWith(projectId)||true
)
 },

 getPendingCount:()=>{
  return get().assets.filter((a)=>a.approvalStatus==='pending').length
 }
}))

export const usePendingAssetsCount=()=>{
 return useAssetStore((state)=>
  state.assets.filter((a)=>a.approvalStatus==='pending').length
)
}

export const useAssetsByApprovalStatus=(status:'approved'|'pending'|'rejected')=>{
 return useAssetStore((state)=>
  state.assets.filter((a)=>a.approvalStatus===status)
)
}
