import{useState,useEffect,useCallback}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{Bell,Volume2,VolumeX,Save}from'lucide-react'
import{API_ENDPOINTS}from'@/constants/api'
import{api}from'@/services/apiService'

interface NotificationConfig{
 enabled:boolean
 categories:{
  checkpoint:boolean
  completion:boolean
  error:boolean
  budget:boolean
 }
 sound:boolean
}

const defaultConfig:NotificationConfig={
 enabled:false,
 categories:{checkpoint:true,completion:true,error:true,budget:true},
 sound:false
}

const categoryLabels:Record<string,string>={
 checkpoint:'チェックポイント承認',
 completion:'タスク完了',
 error:'エラー発生',
 budget:'予算アラート'
}

export function NotificationSettings():JSX.Element{
 const[config,setConfig]=useState<NotificationConfig>(defaultConfig)
 const[loading,setLoading]=useState(true)
 const[saving,setSaving]=useState(false)
 const[message,setMessage]=useState<{text:string;type:'success'|'error'}|null>(null)

 useEffect(()=>{
  const fetch=async()=>{
   try{
    const res=await api.get(API_ENDPOINTS.config.notificationSettings)
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
   const res=await api.put(API_ENDPOINTS.config.notificationSettings,config)
   setConfig(res.data)
   setMessage({text:'通知設定を保存しました',type:'success'})
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
     <Bell size={16}/>
     <span className="text-nier-small font-medium">Desktop通知</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light space-y-4">
     <label className="flex items-center gap-3 cursor-pointer">
      <input
       type="checkbox"
       className="nier-checkbox"
       checked={config.enabled}
       onChange={(e)=>setConfig(prev=>({...prev,enabled:e.target.checked}))}
      />
      <span className="text-nier-small">Desktop通知を有効にする</span>
     </label>

     {config.enabled&&(
      <div className="pl-6 space-y-2 border-l-2 border-nier-border-light">
       <div className="text-nier-caption text-nier-text-light mb-1">通知カテゴリ</div>
       {Object.entries(categoryLabels).map(([key,label])=>(
        <label key={key} className="flex items-center gap-3 cursor-pointer">
         <input
          type="checkbox"
          className="nier-checkbox"
          checked={config.categories[key as keyof typeof config.categories]}
          onChange={(e)=>setConfig(prev=>({
           ...prev,
           categories:{...prev.categories,[key]:e.target.checked}
          }))}
         />
         <span className="text-nier-small">{label}</span>
        </label>
))}
      </div>
)}

     <label className="flex items-center gap-3 cursor-pointer">
      <input
       type="checkbox"
       className="nier-checkbox"
       checked={config.sound}
       onChange={(e)=>setConfig(prev=>({...prev,sound:e.target.checked}))}
      />
      {config.sound?<Volume2 size={14}/>:<VolumeX size={14} className="text-nier-text-light"/>}
      <span className="text-nier-small">通知音を有効にする</span>
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
