import{create}from'zustand'

export type ToastType='success'|'error'|'warning'|'info'

export interface ToastItem{
 id:string
 type:ToastType
 message:string
 duration:number
}

interface ToastState{
 toasts:ToastItem[]
 addToast:(type:ToastType,message:string,duration?:number)=>void
 removeToast:(id:string)=>void
}

const DEFAULT_DURATIONS:Record<ToastType,number>={
 success:4000,
 error:8000,
 warning:6000,
 info:4000
}

export const useToastStore=create<ToastState>((set)=>({
 toasts:[],
 addToast:(type,message,duration)=>{
  const id=`toast-${Date.now()}-${Math.random().toString(36).slice(2,7)}`
  const item:ToastItem={id,type,message,duration:duration??DEFAULT_DURATIONS[type]}
  set((state)=>({toasts:[...state.toasts,item]}))
 },
 removeToast:(id)=>{
  set((state)=>({toasts:state.toasts.filter(t=>t.id!==id)}))
 }
}))
