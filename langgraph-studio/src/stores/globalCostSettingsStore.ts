import{create}from'zustand'
import{globalCostApi,costReportApi,type GlobalCostSettings,type BudgetStatus,type CostHistoryResponse,type CostSummary}from'@/services/apiService'

interface GlobalCostSettingsState{
 settings:GlobalCostSettings|null
 budgetStatus:BudgetStatus|null
 history:CostHistoryResponse|null
 summary:CostSummary|null
 loading:boolean
 error:string|null
 fetchSettings:()=>Promise<void>
 updateSettings:(data:Partial<GlobalCostSettings>)=>Promise<void>
 fetchBudgetStatus:()=>Promise<void>
 fetchHistory:(params?:{project_id?:string;year?:number;month?:number;limit?:number;offset?:number})=>Promise<void>
 fetchSummary:(params?:{year?:number;month?:number})=>Promise<void>
}

export const useGlobalCostSettingsStore=create<GlobalCostSettingsState>((set)=>({
 settings:null,
 budgetStatus:null,
 history:null,
 summary:null,
 loading:false,
 error:null,
 fetchSettings:async()=>{
  set({loading:true,error:null})
  try{
   const settings=await globalCostApi.getSettings()
   set({settings,loading:false})
  }catch(e){
   set({error:e instanceof Error?e.message:'Failed to fetch settings',loading:false})
  }
 },
 updateSettings:async(data)=>{
  set({loading:true,error:null})
  try{
   const settings=await globalCostApi.updateSettings(data)
   set({settings,loading:false})
  }catch(e){
   set({error:e instanceof Error?e.message:'Failed to update settings',loading:false})
  }
 },
 fetchBudgetStatus:async()=>{
  try{
   const budgetStatus=await globalCostApi.getBudgetStatus()
   set({budgetStatus})
  }catch(e){
   set({error:e instanceof Error?e.message:'Failed to fetch budget status'})
  }
 },
 fetchHistory:async(params)=>{
  set({loading:true,error:null})
  try{
   const history=await costReportApi.getHistory(params)
   set({history,loading:false})
  }catch(e){
   set({error:e instanceof Error?e.message:'Failed to fetch history',loading:false})
  }
 },
 fetchSummary:async(params)=>{
  try{
   const summary=await costReportApi.getSummary(params)
   set({summary})
  }catch(e){
   set({error:e instanceof Error?e.message:'Failed to fetch summary'})
  }
 }
}))
