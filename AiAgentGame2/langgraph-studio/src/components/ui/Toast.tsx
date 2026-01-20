import{useEffect,useState,createContext,useContext,useCallback,ReactNode}from'react'
import{createPortal}from'react-dom'
import{X,CheckCircle,AlertCircle,AlertTriangle,Info}from'lucide-react'
import{cn}from'@/lib/utils'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast{
 id:string
 type:ToastType
 message:string
 duration?:number
}

interface ToastContextValue{
 toasts:Toast[]
 addToast:(toast:Omit<Toast,'id'>)=>void
 removeToast:(id:string)=>void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast(){
 const context = useContext(ToastContext)
 if(!context){
  throw new Error('useToast must be used within a ToastProvider')
 }
 return context
}

export function ToastProvider({children }:{children:ReactNode}){
 const[toasts,setToasts] = useState<Toast[]>([])

 const addToast = useCallback((toast:Omit<Toast,'id'>) => {
  const id = Math.random().toString(36).slice(2,9)
  setToasts((prev) => [...prev,{...toast,id}])
 },[])

 const removeToast = useCallback((id:string) => {
  setToasts((prev) => prev.filter((t) => t.id !== id))
 },[])

 return(
  <ToastContext.Provider value={{toasts,addToast,removeToast}}>
   {children}
   <ToastContainer />
  </ToastContext.Provider>
 )
}

function ToastContainer(){
 const{toasts,removeToast} = useToast()

 if(toasts.length === 0)return null

 return createPortal(
  <div className="fixed bottom-4 right-4 z-[300] flex flex-col gap-2">
   {toasts.map((toast) => (
    <ToastItem key={toast.id} toast={toast} onClose={() => removeToast(toast.id)} />
   ))}
  </div>,
  document.body
 )
}

const iconMap = {
 success:CheckCircle,
 error:AlertCircle,
 warning:AlertTriangle,
 info:Info
}

const colorMap = {
 success:'text-nier-accent-green border-nier-accent-green',
 error:'text-nier-accent-red border-nier-accent-red',
 warning:'text-nier-accent-orange border-nier-accent-orange',
 info:'text-nier-accent-blue border-nier-accent-blue'
}

interface ToastItemProps{
 toast:Toast
 onClose:()=>void
}

function ToastItem({toast,onClose}:ToastItemProps){
 const Icon = iconMap[toast.type]
 const duration = toast.duration ?? 5000

 useEffect(() => {
  if(duration > 0){
   const timer = setTimeout(onClose,duration)
   return() => clearTimeout(timer)
  }
 },[duration,onClose])

 return(
  <div
   className={cn(
    'nier-toast min-w-[300px] animate-nier-slide-in border-l-4',
    colorMap[toast.type]
   )}
  >
   <Icon size={18} className={colorMap[toast.type].split(' ')[0]} />
   <span className="flex-1 text-nier-small text-nier-text-main">{toast.message}</span>
   <button
    onClick={onClose}
    className="text-nier-text-light hover:text-nier-text-main transition-colors"
   >
    <X size={16} />
   </button>
  </div>
 )
}

export{ToastItem}
