import{create}from'zustand'

interface AuthState{
 token:string|null
 setToken:(token:string)=>void
 logout:()=>void
 isAuthenticated:()=>boolean
}

export const useAuthStore=create<AuthState>((set,get)=>({
 token:sessionStorage.getItem('admin_token'),
 setToken:(token:string)=>{
  sessionStorage.setItem('admin_token',token)
  set({token})
 },
 logout:()=>{
  sessionStorage.removeItem('admin_token')
  set({token:null})
 },
 isAuthenticated:()=>!!get().token
}))
