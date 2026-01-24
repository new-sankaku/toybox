import{create}from'zustand'

export type MessageSource='client'|'server'
export type MessagePriority='low'|'normal'|'high'|'critical'

export interface NavigatorMessage {
 id: string
 speaker: string
 text: string
 timestamp: number
 source: MessageSource
 priority: MessagePriority
}

interface NavigatorState {
 isVisible: boolean
 currentMessage: NavigatorMessage|null
 messageQueue: NavigatorMessage[]
 showMessage: (speaker: string,text: string)=>void
 showServerMessage: (speaker: string,text: string,priority?: MessagePriority)=>void
 dismissMessage: ()=>void
 clearAll: ()=>void
}

export const useNavigatorStore=create<NavigatorState>((set,get)=>({
 isVisible:false,
 currentMessage:null,
 messageQueue:[],

 showMessage: (speaker: string,text: string)=>{
  const message: NavigatorMessage={
   id: `msg-${Date.now()}`,
   speaker,
   text,
   timestamp: Date.now(),
   source: 'client',
   priority: 'normal'
  }

  const state=get()
  if (state.currentMessage) {
   set({ messageQueue: [...state.messageQueue,message] })
  } else {
   set({ isVisible: true,currentMessage: message })
  }
 },

 showServerMessage: (speaker: string,text: string,priority: MessagePriority='normal')=>{
  const message: NavigatorMessage={
   id: `srv-${Date.now()}`,
   speaker,
   text,
   timestamp: Date.now(),
   source: 'server',
   priority
  }

  const state=get()

  if (priority==='critical'||priority==='high') {
   if (state.currentMessage) {
    set({ messageQueue: [message,...state.messageQueue] })
   } else {
    set({ isVisible: true,currentMessage: message })
   }
  } else {
   if (state.currentMessage) {
    set({ messageQueue: [...state.messageQueue,message] })
   } else {
    set({ isVisible: true,currentMessage: message })
   }
  }
 },

 dismissMessage: ()=>{
  const state=get()
  if (state.messageQueue.length>0) {
   const [nextMessage,...remainingQueue]=state.messageQueue
   set({
    currentMessage: nextMessage,
    messageQueue: remainingQueue
   })
  } else {
   set({ isVisible: false,currentMessage: null })
  }
 },

 clearAll: ()=>{
  set({ isVisible: false,currentMessage: null,messageQueue: [] })
 }
}))
