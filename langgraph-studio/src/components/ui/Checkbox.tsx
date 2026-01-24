import{forwardRef,InputHTMLAttributes}from'react'
import{cn}from'@/lib/utils'

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>,'onChange'>{
 label?:string
 checked?:boolean
 onChange?:(checked:boolean)=>void
}

const Checkbox=forwardRef<HTMLInputElement,CheckboxProps>(
 ({className,label,checked,onChange,disabled,id,...props},ref)=>{
  const inputId=id||`checkbox-${Math.random().toString(36).slice(2,9)}`

  return(
   <label
    htmlFor={inputId}
    className={cn(
     'flex items-center gap-2 cursor-pointer select-none',
     disabled&&'cursor-not-allowed opacity-50'
)}
   >
    <input
     type="checkbox"
     id={inputId}
     ref={ref}
     checked={checked}
     onChange={(e)=>onChange?.(e.target.checked)}
     disabled={disabled}
     className={cn(
      'w-4 h-4 border border-nier-border-light bg-nier-bg-panel',
      'checked:bg-nier-accent-orange checked:border-nier-accent-orange',
      'focus:ring-1 focus:ring-nier-accent-orange focus:ring-offset-0',
      'cursor-pointer disabled:cursor-not-allowed',
      className
)}
     {...props}
    />
    {label&&(
     <span className="text-nier-small text-nier-text-main">{label}</span>
)}
   </label>
)
 }
)
Checkbox.displayName='Checkbox'

export{Checkbox}
