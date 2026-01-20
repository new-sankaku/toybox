import{forwardRef,TextareaHTMLAttributes}from'react'
import{cn}from'@/lib/utils'

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement>{
 label?:string
 error?:string
}

const Textarea = forwardRef<HTMLTextAreaElement,TextareaProps>(
 ({className,label,error,id,...props},ref) => {
  const textareaId = id || `textarea-${Math.random().toString(36).slice(2,9)}`

  return(
   <div className="w-full">
    {label && (
     <label
      htmlFor={textareaId}
      className="block text-nier-small text-nier-text-light mb-1 tracking-nier"
     >
      {label}
     </label>
    )}
    <textarea
     id={textareaId}
     ref={ref}
     className={cn(
      'w-full px-3 py-2 bg-nier-bg-main border border-nier-border-dark',
      'text-nier-text-main tracking-nier resize-none',
      'focus:outline-none focus:border-nier-text-main',
      'placeholder:text-nier-text-light',
      error && 'border-nier-accent-red',
      className
     )}
     {...props}
    />
    {error && (
     <p className="mt-1 text-nier-caption text-nier-accent-red">{error}</p>
    )}
   </div>
  )
 }
)
Textarea.displayName = 'Textarea'

export{Textarea}
