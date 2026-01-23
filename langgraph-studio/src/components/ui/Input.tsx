import{forwardRef,InputHTMLAttributes}from'react'
import{cn}from'@/lib/utils'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement>{
 label?:string
 error?:string
}

const Input=forwardRef<HTMLInputElement,InputProps>(
 ({className,label,error,id,...props},ref)=>{
  const inputId=id||`input-${Math.random().toString(36).slice(2,9)}`

  return(
   <div className="w-full">
    {label&&(
     <label
      htmlFor={inputId}
      className="block text-nier-small text-nier-text-light mb-1 tracking-nier"
     >
      {label}
     </label>
)}
    <input
     id={inputId}
     ref={ref}
     className={cn(
      'nier-input',
      error&&'border-nier-accent-red',
      className
)}
     {...props}
    />
    {error&&(
     <p className="mt-1 text-nier-caption text-nier-accent-red">{error}</p>
)}
   </div>
)
 }
)
Input.displayName='Input'

export{Input}
