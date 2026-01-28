import{create}from'zustand'
import type{BackupEntry,ArchiveEntry,ArchiveStats,CleanupEstimate,RecoveryStatus,SystemStats}from'@/types/dataManagement'

interface DataManagementState{
 backups:BackupEntry[]
 archives:ArchiveEntry[]
 archiveStats:ArchiveStats|null
 cleanupEstimate:CleanupEstimate|null
 recoveryStatus:RecoveryStatus|null
 systemStats:SystemStats|null
 loading:Record<string,boolean>
 error:string|null
 fetchBackups:()=>Promise<void>
 createBackup:()=>Promise<void>
 restoreBackup:(name:string)=>Promise<boolean>
 deleteBackup:(name:string)=>Promise<void>
 fetchArchives:()=>Promise<void>
 fetchArchiveStats:(projectId?:string)=>Promise<void>
 fetchCleanupEstimate:(projectId?:string)=>Promise<void>
 runCleanup:(projectId?:string)=>Promise<number>
 setRetention:(days:number)=>Promise<void>
 exportArchive:(projectId:string)=>Promise<string|null>
 exportAndCleanup:(projectId:string)=>Promise<{filename:string;deleted:number}|null>
 deleteArchive:(name:string)=>Promise<void>
 fetchRecoveryStatus:()=>Promise<void>
 retryAllRecovery:()=>Promise<number>
 fetchSystemStats:()=>Promise<void>
}

export const useDataManagementStore=create<DataManagementState>((set,get)=>({
 backups:[],
 archives:[],
 archiveStats:null,
 cleanupEstimate:null,
 recoveryStatus:null,
 systemStats:null,
 loading:{},
 error:null,

 fetchBackups:async()=>{
  set({loading:{...get().loading,backups:true},error:null})
  try{
   const{backupApi}=await import('@/services/apiService')
   const data=await backupApi.list()
   set({backups:data})
  }catch(e){
   set({error:e instanceof Error?e.message:'バックアップの取得に失敗しました'})
  }finally{
   set({loading:{...get().loading,backups:false}})
  }
 },

 createBackup:async()=>{
  set({loading:{...get().loading,createBackup:true},error:null})
  try{
   const{backupApi}=await import('@/services/apiService')
   await backupApi.create()
   await get().fetchBackups()
  }catch(e){
   set({error:e instanceof Error?e.message:'バックアップの作成に失敗しました'})
  }finally{
   set({loading:{...get().loading,createBackup:false}})
  }
 },

 restoreBackup:async(name)=>{
  set({loading:{...get().loading,restore:true},error:null})
  try{
   const{backupApi}=await import('@/services/apiService')
   const result=await backupApi.restore(name)
   return result.success
  }catch(e){
   set({error:e instanceof Error?e.message:'バックアップの復元に失敗しました'})
   return false
  }finally{
   set({loading:{...get().loading,restore:false}})
  }
 },

 deleteBackup:async(name)=>{
  set({loading:{...get().loading,deleteBackup:true},error:null})
  try{
   const{backupApi}=await import('@/services/apiService')
   await backupApi.delete(name)
   await get().fetchBackups()
  }catch(e){
   set({error:e instanceof Error?e.message:'バックアップの削除に失敗しました'})
  }finally{
   set({loading:{...get().loading,deleteBackup:false}})
  }
 },

 fetchArchives:async()=>{
  set({loading:{...get().loading,archives:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   const data=await archiveApi.list()
   set({archives:data})
  }catch(e){
   set({error:e instanceof Error?e.message:'アーカイブの取得に失敗しました'})
  }finally{
   set({loading:{...get().loading,archives:false}})
  }
 },

 fetchArchiveStats:async(projectId?)=>{
  set({loading:{...get().loading,archiveStats:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   const data=await archiveApi.getStats(projectId)
   set({archiveStats:data})
  }catch(e){
   set({error:e instanceof Error?e.message:'アーカイブ統計の取得に失敗しました'})
  }finally{
   set({loading:{...get().loading,archiveStats:false}})
  }
 },

 fetchCleanupEstimate:async(projectId?)=>{
  set({loading:{...get().loading,estimate:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   const data=await archiveApi.estimate(projectId)
   set({cleanupEstimate:data})
  }catch(e){
   set({error:e instanceof Error?e.message:'見積もりの取得に失敗しました'})
  }finally{
   set({loading:{...get().loading,estimate:false}})
  }
 },

 runCleanup:async(projectId?)=>{
  set({loading:{...get().loading,cleanup:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   const result=await archiveApi.cleanup(projectId)
   await get().fetchArchiveStats(projectId)
   return result.deleted
  }catch(e){
   set({error:e instanceof Error?e.message:'クリーンアップに失敗しました'})
   return 0
  }finally{
   set({loading:{...get().loading,cleanup:false}})
  }
 },

 setRetention:async(days)=>{
  set({loading:{...get().loading,retention:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   await archiveApi.setRetention(days)
  }catch(e){
   set({error:e instanceof Error?e.message:'保持期間の設定に失敗しました'})
  }finally{
   set({loading:{...get().loading,retention:false}})
  }
 },

 exportArchive:async(projectId)=>{
  set({loading:{...get().loading,export:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   const result=await archiveApi.export(projectId)
   return result.filename
  }catch(e){
   set({error:e instanceof Error?e.message:'エクスポートに失敗しました'})
   return null
  }finally{
   set({loading:{...get().loading,export:false}})
  }
 },

 exportAndCleanup:async(projectId)=>{
  set({loading:{...get().loading,exportCleanup:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   const result=await archiveApi.exportAndCleanup(projectId)
   await get().fetchArchiveStats(projectId)
   return result
  }catch(e){
   set({error:e instanceof Error?e.message:'エクスポート&クリーンアップに失敗しました'})
   return null
  }finally{
   set({loading:{...get().loading,exportCleanup:false}})
  }
 },

 deleteArchive:async(name)=>{
  set({loading:{...get().loading,deleteArchive:true},error:null})
  try{
   const{archiveApi}=await import('@/services/apiService')
   await archiveApi.delete(name)
   await get().fetchArchives()
  }catch(e){
   set({error:e instanceof Error?e.message:'アーカイブの削除に失敗しました'})
  }finally{
   set({loading:{...get().loading,deleteArchive:false}})
  }
 },

 fetchRecoveryStatus:async()=>{
  set({loading:{...get().loading,recovery:true},error:null})
  try{
   const{recoveryApi}=await import('@/services/apiService')
   const data=await recoveryApi.getStatus()
   set({recoveryStatus:data})
  }catch(e){
   set({error:e instanceof Error?e.message:'リカバリー状態の取得に失敗しました'})
  }finally{
   set({loading:{...get().loading,recovery:false}})
  }
 },

 retryAllRecovery:async()=>{
  set({loading:{...get().loading,retryAll:true},error:null})
  try{
   const{recoveryApi}=await import('@/services/apiService')
   const result=await recoveryApi.retryAll()
   await get().fetchRecoveryStatus()
   return result.retriedCount
  }catch(e){
   set({error:e instanceof Error?e.message:'リトライに失敗しました'})
   return 0
  }finally{
   set({loading:{...get().loading,retryAll:false}})
  }
 },

 fetchSystemStats:async()=>{
  set({loading:{...get().loading,system:true},error:null})
  try{
   const{systemApi}=await import('@/services/apiService')
   const data=await systemApi.getStats()
   set({systemStats:data})
  }catch(e){
   set({error:e instanceof Error?e.message:'システム情報の取得に失敗しました'})
  }finally{
   set({loading:{...get().loading,system:false}})
  }
 }
}))
