export function cn(...classes:(string|boolean|undefined|null)[]):string{
 return classes.filter(Boolean).join(' ')
}

export function formatSize(bytes:number):string{
 if(bytes>=1024*1024*1024)return`${(bytes/(1024*1024*1024)).toFixed(1)}GB`
 if(bytes>=1024*1024)return`${(bytes/(1024*1024)).toFixed(1)}MB`
 if(bytes>=1024)return`${(bytes/1024).toFixed(1)}KB`
 return`${bytes}B`
}

export function formatDate(dateStr:string):string{
 const d=new Date(dateStr)
 return d.toLocaleString('ja-JP',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})
}
