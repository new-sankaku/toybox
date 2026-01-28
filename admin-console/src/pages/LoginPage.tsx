import{useState}from'react'
import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{useAuthStore}from'@/stores/authStore'
import{authApi}from'@/services/adminApi'
import{Shield}from'lucide-react'

export function LoginPage(){
 const setToken=useAuthStore(s=>s.setToken)
 const[input,setInput]=useState('')
 const[error,setError]=useState('')
 const[loading,setLoading]=useState(false)

 const handleSubmit=async(e:React.FormEvent)=>{
  e.preventDefault()
  if(!input.trim())return
  setLoading(true)
  setError('')
  try{
   await authApi.verify(input.trim())
   setToken(input.trim())
  }catch{
   setError('認証に失敗しました。トークンを確認してください。')
  }finally{
   setLoading(false)
  }
 }

 return(
  <div className="min-h-screen flex items-center justify-center p-4">
   <Card className="w-full max-w-sm">
    <CardHeader>
     <Shield size={18} className="text-nier-text-light"/>
     <span className="text-nier-h2 text-nier-text-main">Admin Console</span>
    </CardHeader>
    <CardContent className="border-t border-nier-border-light">
     <form onSubmit={handleSubmit} className="space-y-4">
      <div>
       <label className="block text-nier-caption text-nier-text-light mb-1">
        管理トークン
       </label>
       <input
        type="password"
        className="w-full bg-nier-bg-main border border-nier-border-light px-3 py-2 text-nier-small focus:outline-none focus:border-nier-border-dark"
        value={input}
        onChange={e=>setInput(e.target.value)}
        placeholder="ADMIN_TOKEN"
        autoFocus
       />
      </div>
      {error&&(
       <div className="text-nier-caption text-nier-accent-red">{error}</div>
      )}
      <Button variant="primary" className="w-full" disabled={loading||!input.trim()}>
       {loading?'認証中...':'認証'}
      </Button>
     </form>
    </CardContent>
   </Card>
  </div>
 )
}
