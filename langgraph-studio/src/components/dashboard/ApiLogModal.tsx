import{useState,useEffect,useCallback}from'react'
import{providerMonitorApi,type ProviderLogEntry}from'@/services/apiService'

interface ApiLogModalProps{
 providerId:string
 providerName:string
 onClose:()=>void
}

type LogFilter='all'|'start'|'complete'|'error'

const FILTER_OPTIONS:{value:LogFilter;label:string}[]=[
 {value:'all',label:'ALL'},
 {value:'start',label:'START'},
 {value:'complete',label:'COMPLETE'},
 {value:'error',label:'ERROR'}
]

const TYPE_LABELS:Record<string,string>={
 start:'START',
 complete:'COMPLETE',
 error:'ERROR'
}

const TYPE_CLASSES:Record<string,string>={
 start:'text-nier-accent-blue',
 complete:'text-nier-accent-green',
 error:'text-nier-accent-red'
}

function formatTimestamp(ts:string|null):string{
 if(!ts)return'--:--:--'
 try{
  const date=new Date(ts)
  return date.toLocaleTimeString('ja-JP',{hour:'2-digit',minute:'2-digit',second:'2-digit'})
 }catch{
  return'--:--:--'
 }
}

function extractModelName(model:string):string{
 if(!model)return'Unknown'
 const parts=model.split('/')
 return parts.length>1?parts[1]:model
}

export default function ApiLogModal({providerId,providerName,onClose}:ApiLogModalProps):JSX.Element{
 const[logs,setLogs]=useState<ProviderLogEntry[]>([])
 const[filter,setFilter]=useState<LogFilter>('all')
 const[searchText,setSearchText]=useState('')
 const[isLoading,setIsLoading]=useState(true)

 const fetchLogs=useCallback(async()=>{
  try{
   setIsLoading(true)
   const data=await providerMonitorApi.getLogs(providerId,{limit:100})
   setLogs(data)
  }catch{
   setLogs([])
  }finally{
   setIsLoading(false)
  }
 },[providerId])

 useEffect(()=>{
  fetchLogs()
 },[fetchLogs])

 const filteredLogs=logs.filter(log=>{
  if(filter!=='all'&&log.type!==filter)return false
  if(searchText){
   const search=searchText.toLowerCase()
   const model=extractModelName(log.model).toLowerCase()
   const error=(log.errorMessage||'').toLowerCase()
   if(!model.includes(search)&&!error.includes(search))return false
  }
  return true
 })

 const handleBackdropClick=(e:React.MouseEvent)=>{
  if(e.target===e.currentTarget)onClose()
 }

 return(
  <div
   className="nier-modal-overlay"
   onClick={handleBackdropClick}
  >
   <div className="nier-modal w-[600px] max-w-[90vw]">
    <div className="nier-card-header justify-between">
     <div className="flex items-center gap-2">
      <span className="text-[10px] opacity-70">&#9671;</span>
      <span>{providerName} LOG</span>
     </div>
     <button
      onClick={onClose}
      className="text-nier-text-header hover:opacity-70 transition-opacity"
     >
      &#10005;
     </button>
    </div>
    <div className="nier-surface-panel p-3 border-b border-nier-border-light">
     <div className="flex items-center gap-3 flex-wrap">
      <div className="flex gap-1">
       {FILTER_OPTIONS.map(opt=>(
        <button
         key={opt.value}
         onClick={()=>setFilter(opt.value)}
         className={`px-2 py-0.5 text-xs tracking-nier transition-colors ${
          filter===opt.value
           ?'nier-surface-header'
           :'nier-surface-main hover:bg-nier-bg-selected'
         }`}
        >
         {opt.label}
        </button>
))}
      </div>
      <div className="flex-1 min-w-[150px]">
       <input
        type="text"
        placeholder="検索..."
        value={searchText}
        onChange={e=>setSearchText(e.target.value)}
        className="nier-input py-1 text-xs"
       />
      </div>
     </div>
    </div>
    <div className="nier-surface-panel overflow-y-auto max-h-[50vh]">
     {isLoading?(
      <div className="py-8 text-center text-nier-text-light">
       ログを取得中...
      </div>
):filteredLogs.length===0?(
      <div className="py-8 text-center text-nier-text-light">
       ログがありません
      </div>
):(
      <table className="w-full text-xs">
       <tbody>
        {filteredLogs.map(log=>(
         <tr
          key={log.id}
          className="border-b border-nier-border-light last:border-b-0 hover:bg-nier-bg-selected"
         >
          <td className="py-1.5 px-2 text-nier-text-light whitespace-nowrap w-[70px]">
           {formatTimestamp(log.timestamp)}
          </td>
          <td className="py-1.5 px-2 whitespace-nowrap w-[80px]">
           <span className={TYPE_CLASSES[log.type]||''}>
            {TYPE_LABELS[log.type]||log.type.toUpperCase()}
           </span>
          </td>
          <td className="py-1.5 px-2">
           <span className="text-nier-text-main">{extractModelName(log.model)}</span>
           {log.type==='error'&&log.errorMessage&&(
            <span className="ml-2 text-nier-accent-red">{log.errorMessage}</span>
)}
           {log.type==='complete'&&(log.tokensInput>0||log.tokensOutput>0)&&(
            <span className="ml-2 text-nier-text-light">
             ({log.tokensInput}→{log.tokensOutput})
            </span>
)}
          </td>
         </tr>
))}
       </tbody>
      </table>
)}
    </div>
    <div className="nier-surface-panel p-2 border-t border-nier-border-light flex justify-end">
     <button
      onClick={onClose}
      className="nier-btn text-xs"
     >
      閉じる
     </button>
    </div>
   </div>
  </div>
)
}
