export function formatSize(bytes:number):string{
 if(bytes<1024)return`${bytes} B`
 if(bytes<1024*1024)return`${(bytes/1024).toFixed(1)} KB`
 if(bytes<1024*1024*1024)return`${(bytes/(1024*1024)).toFixed(1)} MB`
 return`${(bytes/(1024*1024*1024)).toFixed(1)} GB`
}

export function formatDate(dateStr:string):string{
 return new Date(dateStr).toLocaleString('ja-JP')
}
