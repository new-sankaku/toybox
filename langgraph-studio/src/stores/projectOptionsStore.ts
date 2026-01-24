import{create}from'zustand'
import{configApi,type ProjectOptionsConfig,type PlatformOption,type ScopeOption,type LLMProviderOption}from'@/services/apiService'

interface ProjectOptionsState{
 platforms:PlatformOption[]
 scopes:ScopeOption[]
 llmProviders:LLMProviderOption[]
 projectTemplates:{value:string;label:string}[]
 defaults:{platform:string;scope:string;llmProvider:string;projectTemplate:string}
 loaded:boolean
 loading:boolean
 error:string|null
 fetchOptions:()=>Promise<void>
}

const DEFAULT_OPTIONS:ProjectOptionsConfig={
 platforms:[],
 scopes:[],
 llmProviders:[],
 projectTemplates:[],
 defaults:{platform:'web',scope:'demo',llmProvider:'claude',projectTemplate:'rpg'}
}

export const useProjectOptionsStore=create<ProjectOptionsState>((set,get)=>({
 ...DEFAULT_OPTIONS,
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
    llmProviders:options.llmProviders,
    projectTemplates:options.projectTemplates,
    defaults:options.defaults,
    loaded:true,
    loading:false
   })
  }catch(error){
   console.error('Failed to fetch project options:',error)
   set({
    error:error instanceof Error?error.message:'Failed to fetch project options',
    loading:false
   })
  }
 }
}))
