import{create}from'zustand'

export interface SpeechEvent{
 id:string
 agentId:string
 message:string
 source:'llm'|'pool'
 timestamp:string
 expiresAt:number
}

const SPEECH_DURATION_MS=8000
const MAX_SPEECHES=20

interface SpeechState{
 speeches:SpeechEvent[]
 addSpeech:(agentId:string,message:string,source:'llm'|'pool')=>void
 getAgentSpeech:(agentId:string)=>SpeechEvent|undefined
 cleanup:()=>void
 clear:()=>void
}

export const useSpeechStore=create<SpeechState>((set,get)=>({
 speeches:[],
 addSpeech:(agentId,message,source)=>{
  const now=Date.now()
  const speech:SpeechEvent={
   id:`sp-${now}-${Math.random().toString(36).slice(2,7)}`,
   agentId,
   message,
   source,
   timestamp:new Date().toISOString(),
   expiresAt:now+SPEECH_DURATION_MS,
  }
  set((state)=>({
   speeches:[speech,...state.speeches.filter(s=>s.agentId!==agentId)].slice(0,MAX_SPEECHES)
  }))
 },
 getAgentSpeech:(agentId)=>{
  const now=Date.now()
  return get().speeches.find(s=>s.agentId===agentId&&s.expiresAt>now)
 },
 cleanup:()=>{
  const now=Date.now()
  set((state)=>({
   speeches:state.speeches.filter(s=>s.expiresAt>now)
  }))
 },
 clear:()=>set({speeches:[]})
}))
