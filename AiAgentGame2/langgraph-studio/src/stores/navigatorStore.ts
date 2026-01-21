import{create}from'zustand'

export interface NavigatorMessage{
 id:string
 speaker:string
 text:string
 timestamp:number
}

interface NavigatorState{
 isActive:boolean
 isConnecting:boolean
 currentMessage:NavigatorMessage|null
 messageQueue:NavigatorMessage[]
 showMessage:(speaker:string,text:string)=>void
 dismissMessage:()=>void
 clearAll:()=>void
}

export const useNavigatorStore=create<NavigatorState>((set,get)=>({
 isActive:false,
 isConnecting:false,
 currentMessage:null,
 messageQueue:[],

 showMessage:(speaker:string,text:string)=>{
  const message:NavigatorMessage={
   id:`msg-${Date.now()}`,
   speaker,
   text,
   timestamp:Date.now()
  }

  const state=get()
  if(state.currentMessage){
   set({messageQueue:[...state.messageQueue,message]})
  }else{
   set({isConnecting:true,currentMessage:message})
   setTimeout(()=>{
    set({isConnecting:false,isActive:true})
   },800)
  }
 },

 dismissMessage:()=>{
  const state=get()
  if(state.messageQueue.length>0){
   const[nextMessage,...remainingQueue]=state.messageQueue
   set({isConnecting:true,currentMessage:nextMessage,messageQueue:remainingQueue})
   setTimeout(()=>{
    set({isConnecting:false})
   },500)
  }else{
   set({isActive:false,currentMessage:null})
  }
 },

 clearAll:()=>{
  set({isActive:false,isConnecting:false,currentMessage:null,messageQueue:[]})
 }
}))
