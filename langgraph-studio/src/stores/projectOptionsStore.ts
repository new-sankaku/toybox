import{create}from'zustand'
import{configApi,type ProjectOptionsConfig,type PlatformOption,type ScopeOption}from'@/services/apiService'
import type{ProjectScaleOption,AssetServiceOption,ContentRatingOption,AssetGenerationOptions,ContentPermissions}from'@/config/projectOptions'

interface ProjectOptionsState{
 platforms:PlatformOption[]
 scopes:ScopeOption[]
 projectTemplates:{value:string;label:string}[]
 scaleOptions:ProjectScaleOption[]
 assetServiceOptions:AssetServiceOption[]
 violenceRatingOptions:ContentRatingOption[]
 sexualRatingOptions:ContentRatingOption[]
 projectDefaults:{assetGeneration:AssetGenerationOptions;contentPermissions:ContentPermissions}|null
 defaults:{platform:string;scope:string;projectTemplate:string}|null
 loaded:boolean
 loading:boolean
 error:string|null
 fetchOptions:()=>Promise<void>
}

export const useProjectOptionsStore=create<ProjectOptionsState>((set,get)=>({
 platforms:[],
 scopes:[],
 projectTemplates:[],
 scaleOptions:[],
 assetServiceOptions:[],
 violenceRatingOptions:[],
 sexualRatingOptions:[],
 projectDefaults:null,
 defaults:null,
 loaded:false,
 loading:false,
 error:null,
 fetchOptions:async()=>{
  if(get().loaded||get().loading)return
  set({loading:true,error:null})
  try{
   const options=await configApi.getProjectOptions()
   set({
    platforms:options.platforms,
    scopes:options.scopes,
    projectTemplates:options.projectTemplates,
    scaleOptions:options.scaleOptions||[],
    assetServiceOptions:options.assetServiceOptions||[],
    violenceRatingOptions:options.violenceRatingOptions||[],
    sexualRatingOptions:options.sexualRatingOptions||[],
    projectDefaults:options.projectDefaults||null,
    defaults:options.defaults,
    loaded:true,
    loading:false
   })
  }catch(error){
   console.error('Failed to fetch project options:',error)
   set({
    error:error instanceof Error?error.message:'プロジェクトオプションの取得に失敗しました',
    loading:false
   })
  }
 }
}))
