import{useRef,useState,useCallback}from'react'

export function useAudioPlayer(){
 const audioRef=useRef<HTMLAudioElement|null>(null)
 const[playingAudio,setPlayingAudio]=useState<string|null>(null)

 const handlePlayAudio=useCallback((assetId:string,audioUrl?:string)=>{
  if(playingAudio===assetId){
   if(audioRef.current){
    audioRef.current.pause()
    audioRef.current.currentTime=0
   }
   setPlayingAudio(null)
  }else{
   if(audioRef.current&&audioUrl){
    audioRef.current.src=audioUrl
    audioRef.current.play().catch(err=>{
     console.error('Failed to play audio:',err)
    })
   }
   setPlayingAudio(assetId)
  }
 },[playingAudio])

 const stopAudio=useCallback(()=>{
  if(audioRef.current){
   audioRef.current.pause()
  }
  setPlayingAudio(null)
 },[])

 const handleEnded=useCallback(()=>setPlayingAudio(null),[])
 const handleError=useCallback((e:React.SyntheticEvent<HTMLAudioElement,Event>)=>{
  console.error('Audio error:',e)
  setPlayingAudio(null)
 },[])

 return{
  audioRef,
  playingAudio,
  handlePlayAudio,
  stopAudio,
  handleEnded,
  handleError
 }
}
