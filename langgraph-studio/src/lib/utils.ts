import{type ClassValue,clsx}from'clsx'
import{twMerge}from'tailwind-merge'


export function cn(...inputs:ClassValue[]):string{
 return twMerge(clsx(inputs))
}


export function formatDuration(seconds:number):string{
 const hours=Math.floor(seconds/3600)
 const minutes=Math.floor((seconds%3600)/60)
 const secs=Math.floor(seconds%60)

 return[hours,minutes,secs]
  .map((v)=>v.toString().padStart(2,'0'))
  .join(':')
}


export function formatNumber(num:number):string{
 return num.toLocaleString()
}


export function formatBytes(bytes:number):string{
 if(bytes===0)return'0 B'

 const k=1024
 const sizes=['B','KB','MB','GB','TB']
 const i=Math.floor(Math.log(bytes)/Math.log(k))

 return`${parseFloat((bytes/Math.pow(k,i)).toFixed(1))} ${sizes[i]}`
}


export function formatDate(date:Date|string):string{
 const d=typeof date==='string'?new Date(date) : date
 return d.toLocaleString('ja-JP',{
  year:'numeric',
  month:'2-digit',
  day:'2-digit',
  hour:'2-digit',
  minute:'2-digit',
  second:'2-digit'
 })
}


export function formatRelativeTime(date:Date|string):string{
 const d=typeof date==='string'?new Date(date) : date
 const now=new Date()
 const diff=now.getTime()-d.getTime()

 const seconds=Math.floor(diff/1000)
 const minutes=Math.floor(seconds/60)
 const hours=Math.floor(minutes/60)
 const days=Math.floor(hours/24)

 if(days>0)return`${days}日前`
 if(hours>0)return`${hours}時間前`
 if(minutes>0)return`${minutes}分前`
 return'今'
}
