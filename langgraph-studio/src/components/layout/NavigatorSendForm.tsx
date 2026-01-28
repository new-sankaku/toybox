import{useState,useCallback}from'react'
import{Button}from'@/components/ui/Button'
import{Send}from'lucide-react'
import{navigatorApi}from'@/services/apiService'
import{useProjectStore}from'@/stores/projectStore'
import{useNavigatorStore}from'@/stores/navigatorStore'
import{useToastStore}from'@/stores/toastStore'

type Priority='normal'|'high'|'critical'

const priorityOptions:{value:Priority;label:string}[]=[
 {value:'normal',label:'通常'},
 {value:'high',label:'高'},
 {value:'critical',label:'緊急'}
]

export default function NavigatorSendForm():JSX.Element{
 const{currentProject}=useProjectStore()
 const{showMessage}=useNavigatorStore()
 const addToast=useToastStore(s=>s.addToast)
 const[text,setText]=useState('')
 const[priority,setPriority]=useState<Priority>('normal')
 const[sending,setSending]=useState(false)

 const handleSend=useCallback(async()=>{
  if(!text.trim())return
  setSending(true)
  try{
   if(currentProject){
    await navigatorApi.sendMessage({projectId:currentProject.id,text:text.trim(),priority})
   }else{
    await navigatorApi.broadcast({text:text.trim(),priority})
   }
   showMessage('オペレーター',text.trim())
   addToast('メッセージを送信しました','success')
   setText('')
   setPriority('normal')
  }catch{
   addToast('メッセージの送信に失敗しました','error')
  }finally{
   setSending(false)
  }
 },[text,priority,currentProject,showMessage,addToast])

 return(
  <div className="border-t border-nier-border-light p-2 space-y-1.5">
   <div className="text-[9px] tracking-wider text-nier-text-light">NAVIGATOR</div>
   <textarea
    className="w-full bg-nier-bg-panel border border-nier-border-light px-2 py-1.5 text-nier-small focus:outline-none focus:border-nier-border-dark resize-none"
    rows={2}
    placeholder="メッセージを入力..."
    value={text}
    onChange={e=>setText(e.target.value)}
    onKeyDown={e=>{
     if(e.key==='Enter'&&!e.shiftKey){
      e.preventDefault()
      handleSend()
     }
    }}
   />
   <div className="flex items-center gap-1.5">
    <select
     className="bg-nier-bg-panel border border-nier-border-light px-1.5 py-1 text-[11px] focus:outline-none focus:border-nier-border-dark"
     value={priority}
     onChange={e=>setPriority(e.target.value as Priority)}
    >
     {priorityOptions.map(opt=>(
      <option key={opt.value} value={opt.value}>{opt.label}</option>
))}
    </select>
    <Button
     variant="primary" size="sm"
     className="ml-auto"
     onClick={handleSend}
     disabled={sending||!text.trim()}
    >
     <Send size={12}/>
     <span className="ml-1">{sending?'送信中':'送信'}</span>
    </Button>
   </div>
   {!currentProject&&(
    <div className="text-[9px] text-nier-text-light">
     プロジェクト未選択: 全体にブロードキャスト
    </div>
)}
  </div>
)
}
