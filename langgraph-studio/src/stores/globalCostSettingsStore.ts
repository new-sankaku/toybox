import{create}from'zustand'
import{globalCostApi,costReportApi,costAnalyticsApi,type GlobalCostSettings,type BudgetStatus,type CostHistoryResponse,type CostSummary,type DailyCostResponse,type CostPrediction}from'@/services/apiService'

interface GlobalCostSettingsState{
 settings:GlobalCostSettings|null
 budgetStatus:BudgetStatus|null
 history:CostHistoryResponse|null
 summary:CostSummary|null
 dailyCost:DailyCostResponse|null
 prediction:CostPrediction|null
 loading:boolean
 error:string|null
 fetchSettings:()=>Promise<void>
 updateSettings:(data:Partial<GlobalCostSettings>)=>Promise<void>
 fetchBudgetStatus:()=>Promise<void>
 fetchHistory:(params?:{project_id?:string;year?:number;month?:number;limit?:number;offset?:number})=>Promise<void>
 fetchSummary:(params?:{year?:number;month?:number})=>Promise<void>
 fetchDailyCost:(params?:{year?:number;month?:number;project_id?:string})=>Promise<void>
 fetchPrediction:()=>Promise<void>
}

export const useGlobalCostSettingsStore=create<GlobalCostSettingsState>((set)=>({
 settings:null,
 budgetStatus:null,
 history:null,
 summary:null,
 dailyCost:null,
 prediction:null,
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
 },
 fetchDailyCost:async(params)=>{
  try{
   const dailyCost=await costAnalyticsApi.getDaily(params)
   set({dailyCost})
  }catch(e){
   set({error:e instanceof Error?e.message:'Failed to fetch daily cost'})
  }
 },
 fetchPrediction:async()=>{
  try{
   const prediction=await costAnalyticsApi.getPrediction()
   set({prediction})
  }catch(e){
   set({error:e instanceof Error?e.message:'Failed to fetch prediction'})
  }
 }
}))
