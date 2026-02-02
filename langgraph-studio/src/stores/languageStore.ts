import{create}from'zustand'
import{languagesApi,LanguageOption}from'@/services/apiService'

interface LanguageState{
 languages:LanguageOption[]
 defaultPrimary:string
 defaultLanguages:string[]
 isLoading:boolean
 error:string|null
 fetchLanguages:()=>Promise<void>
}

export const useLanguageStore=create<LanguageState>((set,get)=>({
 languages:[],
 defaultPrimary:'ja',
 defaultLanguages:['ja'],
 isLoading:false,
 error:null,

 fetchLanguages:async()=>{
  if(get().languages.length>0)return
  set({isLoading:true,error:null})
  try{
   const config=await languagesApi.getConfig()
   set({
    languages:config.languages,
    defaultPrimary:config.defaultPrimary,
    defaultLanguages:config.defaultLanguages,
    isLoading:false
   })
  }catch(e){
   set({error:'言語設定の取得に失敗',isLoading:false})
  }
 }
}))
