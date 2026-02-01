import{Card,CardHeader,CardContent}from'@/components/ui/Card'
import{Button}from'@/components/ui/Button'
import{AlertTriangle,Loader2}from'lucide-react'

interface ConfirmDialogProps{
 title:string
 message:string
 subMessage?:string
 confirmLabel:string
 onConfirm:()=>void
 onCancel:()=>void
 isLoading?:boolean
 variant?:'danger'|'default'
}

export function ConfirmDialog({
 title,
 message,
 subMessage,
 confirmLabel,
 onConfirm,
 onCancel,
 isLoading=false,
 variant='danger'
}:ConfirmDialogProps){
 return(
  <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
   <Card className="w-full max-w-[90vw] md:max-w-sm lg:max-w-md">
    <CardHeader>
     <div className="flex items-center gap-2">
      <AlertTriangle size={18}/>
      <span>{title}</span>
     </div>
    </CardHeader>
    <CardContent>
     <p className="text-nier-body mb-4">{message}</p>
     {subMessage&&(
      <p className="text-nier-small text-nier-text-main mb-6">{subMessage}</p>
     )}
     <div className="flex gap-3 justify-end">
      <Button variant="secondary" onClick={onCancel}>
       キャンセル
      </Button>
      <Button
       variant={variant}
       onClick={onConfirm}
       disabled={isLoading}
      >
       {isLoading&&<Loader2 size={14} className="mr-1.5 animate-spin"/>}
       {confirmLabel}
      </Button>
     </div>
    </CardContent>
   </Card>
  </div>
 )
}
