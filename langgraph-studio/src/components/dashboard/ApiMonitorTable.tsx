import{useState,useEffect,useCallback}from'react'
import{providerMonitorApi,type ProviderMonitorInfo,type ProviderStatus}from'@/services/apiService'
import ApiLogModal from'./ApiLogModal'

interface ProviderDisplayInfo{
 id:string
 name:string
 status:ProviderStatus
 generating:number
 failed:number
}

const PROVIDER_NAMES:Record<string,string>={
 anthropic:'Claude',
 openai:'OpenAI',
 google:'Gemini',
 'stability-ai':'Stability',
 'local-comfyui':'ComfyUI',
 'local-voicevox':'VOICEVOX',
 'local-rvc':'RVC',
 azure:'Azure',
 aws:'AWS',
 cohere:'Cohere',
 mistral:'Mistral'
}

const STATUS_LABELS:Record<ProviderStatus,string>={
 connected:'接続中',
 disconnected:'接続断',
 api_error:'APIエラー',
 cost_exceeded:'Cost超過',
 unknown:'Unknown'
}

const STATUS_CLASSES:Record<ProviderStatus,string>={
 connected:'text-nier-accent-green border-b-nier-accent-green',
 disconnected:'text-nier-text-light border-b-nier-border-dark',
 api_error:'text-nier-accent-red border-b-nier-accent-red',
 cost_exceeded:'text-nier-accent-orange border-b-nier-accent-orange',
 unknown:'text-nier-accent-yellow border-b-nier-accent-yellow'
}

const MARKER_CLASSES:Record<ProviderStatus,string>={
 connected:'bg-nier-accent-green',
 disconnected:'bg-nier-text-light',
 api_error:'bg-nier-accent-red',
 cost_exceeded:'bg-nier-accent-orange',
 unknown:'bg-nier-accent-yellow'
}

export default function ApiMonitorTable():JSX.Element{
 const[providers,setProviders]=useState<ProviderDisplayInfo[]>([])
 const[selectedProviderId,setSelectedProviderId]=useState<string|null>(null)
 const[isModalOpen,setIsModalOpen]=useState(false)

 const fetchMonitorData=useCallback(async()=>{
  try{
   const data=await providerMonitorApi.getAll()
   const list:ProviderDisplayInfo[]=Object.entries(data).map(([id,info]:[string,ProviderMonitorInfo])=>({
    id,
    name:PROVIDER_NAMES[id]||id,
    status:info.status,
    generating:info.generating,
    failed:info.failed
   }))
   list.sort((a,b)=>a.name.localeCompare(b.name))
   setProviders(list)
  }catch{
   setProviders([])
  }
 },[])

 useEffect(()=>{
  fetchMonitorData()
  const interval=setInterval(fetchMonitorData,3000)
  return()=>clearInterval(interval)
 },[fetchMonitorData])

 const handleProviderClick=(providerId:string)=>{
  setSelectedProviderId(providerId)
  setIsModalOpen(true)
 }

 const handleCloseModal=()=>{
  setIsModalOpen(false)
  setSelectedProviderId(null)
 }

 return(
  <div className="nier-card h-full flex flex-col">
   <div className="overflow-auto flex-1">
    <table className="w-full text-sm">
     <thead className="nier-surface-header sticky top-0">
      <tr>
       <th className="text-left py-1.5 px-2 font-normal tracking-nier">PROVIDER</th>
       <th className="text-left py-1.5 px-2 font-normal tracking-nier">STATUS</th>
       <th className="text-center py-1.5 px-2 font-normal tracking-nier">生成中</th>
       <th className="text-center py-1.5 px-2 font-normal tracking-nier">失敗</th>
      </tr>
     </thead>
     <tbody className="nier-surface-panel">
      {providers.length===0?(
       <tr>
        <td colSpan={4} className="py-4 text-center text-nier-text-light">
         プロバイダーデータを取得中...
        </td>
       </tr>
):(
       providers.map(provider=>(
        <tr
         key={provider.id}
         className="border-b border-nier-border-light last:border-b-0 hover:bg-nier-bg-selected cursor-pointer transition-colors"
         onClick={()=>handleProviderClick(provider.id)}
        >
         <td className="py-1.5 px-2">
          <div className="flex items-center gap-2">
           <span className={`w-1 h-4 flex-shrink-0 ${MARKER_CLASSES[provider.status]}`}/>
           <span>{provider.name}</span>
          </div>
         </td>
         <td className="py-1.5 px-2">
          <span className={`px-1.5 py-0.5 text-[10px] tracking-nier border-b-2 ${STATUS_CLASSES[provider.status]}`}>
           {STATUS_LABELS[provider.status]}
          </span>
         </td>
         <td className="py-1.5 px-2 text-center">
          {provider.generating>0?(
           <span className="inline-flex items-center gap-1">
            <span className="api-spinner api-spinner-sm"/>
            <span>{provider.generating}</span>
           </span>
):(
           <span className="text-nier-text-light">0</span>
)}
         </td>
         <td className="py-1.5 px-2 text-center">
          {provider.failed>0?(
           <span className="text-nier-accent-red">{provider.failed}</span>
):(
           <span className="text-nier-text-light">0</span>
)}
         </td>
        </tr>
))
)}
     </tbody>
    </table>
   </div>
   {isModalOpen&&selectedProviderId&&(
    <ApiLogModal
     providerId={selectedProviderId}
     providerName={PROVIDER_NAMES[selectedProviderId]||selectedProviderId}
     onClose={handleCloseModal}
    />
)}
  </div>
)
}
