import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{Monitor,Save}from'lucide-react'
import{API_ENDPOINTS}from'@/constants/api'
import{api}from'@/services/apiService'

interface DisplayConfig{
 sequenceFormat:string
 dashboardAnimation:boolean
}

const defaultConfig:DisplayConfig={
 sequenceFormat:'detailed',
 dashboardAnimation:true
}

export function DisplaySettings():JSX.Element{
 const[config,setConfig]=useState<DisplayConfig>(defaultConfig)
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState(false)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 useEffect(()=>{
  const fetch=async()=>{
   try{
    const res=await api.get(API_ENDPOINTS.config.displaySettings)
    setConfig(res.data)
   }catch{
    setConfig(defaultConfig)
   }finally{
    setLoading(false)
   }
  }
  fetch()
 },[])

 const handleSave=useCallback(async()=>{
  setSaving(true)
  setMessage(null)
  try{
   const res=await api.put(API_ENDPOINTS.config.displaySettings,config)
   setConfig(res.data)
   setMessage({text:'表示設定を保存しました',type:'success'})
   setTimeout(()=>setMessage(null),3000)
  }catch{
   setMessage({text:'保存に失敗しました',type:'error'})
   setTimeout(()=>setMessage(null),3000)
  }finally{
   setSaving(false)
  }
 },[config])

 if(loading){
  return<div className="nier-surface-panel text-center py-8">読み込み中...</div>
 }

 return(
  <div className="space-y-4">
   {message&&(
    <div className={`px-4 py-2 text-nier-small border ${
     message.type==='success'?'border-nier-accent-green text-nier-accent-green':'border-nier-accent-red text-nier-accent-red'
    }`}>
     {message.text}
    </div>
)}

   <Card>
    <CardHeader>
     <Monitor size={16}/>
     <span className="text-nier-small font-medium">表示設定</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light space-y-4">
     <div>
      <label className="text-nier-small text-nier-text-light mb-2 block">シーケンス表示形式</label>
      <div className="flex gap-2">
       <button
        className={`px-3 py-1.5 text-nier-small border transition-colors ${
         config.sequenceFormat==='compact'
          ?'nier-surface-selected border-nier-border-dark'
          :'nier-surface-panel-muted border-nier-border-light hover:bg-nier-bg-selected'
        }`}
        onClick={()=>setConfig(prev=>({...prev,sequenceFormat:'compact'}))}
       >
        コンパクト
       </button>
       <button
        className={`px-3 py-1.5 text-nier-small border transition-colors ${
         config.sequenceFormat==='detailed'
          ?'nier-surface-selected border-nier-border-dark'
          :'nier-surface-panel-muted border-nier-border-light hover:bg-nier-bg-selected'
        }`}
        onClick={()=>setConfig(prev=>({...prev,sequenceFormat:'detailed'}))}
       >
        詳細
       </button>
      </div>
     </div>

     <label className="flex items-center gap-3 cursor-pointer">
      <input
       type="checkbox"
       className="nier-checkbox"
       checked={config.dashboardAnimation}
       onChange={(e)=>setConfig(prev=>({...prev,dashboardAnimation:e.target.checked}))}
      />
      <span className="text-nier-small">ダッシュボードアニメーション</span>
     </label>

     <Button variant="primary" size="sm" onClick={handleSave} disabled={saving} className="gap-1.5">
      <Save size={14}/>
      {saving?'保存中...':'設定を保存'}
     </Button>
    </CardContent>
   </Card>
  </div>
)
}
