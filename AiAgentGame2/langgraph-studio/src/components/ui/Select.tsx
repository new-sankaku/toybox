import{forwardRef,SelectHTMLAttributes}from'react'
import{cn}from'@/lib/utils'

export interface SelectOption{
 value:string
 label:string
 disabled?:boolean
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement>{
 label?:string
 error?:string
 options:SelectOption[]
 placeholder?:string
}

const Select=forwardRef<HTMLSelectElement,SelectProps>(
 ({className,label,error,options,placeholder,id,...props},ref)=>{
  const selectId=id||`select-${Math.random().toString(36).slice(2,9)}`

  return(
   <div className="w-full">
    {label&&(
     <label
      htmlFor={selectId}
      className="block text-nier-small text-nier-text-light mb-1 tracking-nier"
     >
      {label}
     </label>
)}
    <select
     id={selectId}
     ref={ref}
     className={cn(
      'w-full px-3 py-2 bg-nier-bg-main border border-nier-border-dark',
      'text-nier-text-main tracking-nier appearance-none cursor-pointer',
      'focus:outline-none focus:border-nier-text-main',
      'bg-[url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'12\' height=\'12\' viewBox=\'0 0 12 12\'%3E%3Cpath fill=\'%23454138\' d=\'M6 8L2 4h8z\'/%3E%3C/svg%3E")] bg-no-repeat bg-[right_12px_center]',
      error&&'border-nier-accent-red',
      className
)}
     {...props}
    >
     {placeholder&&(
      <option value="" disabled>
       {placeholder}
      </option>
)}
     {options.map((option)=>(
      <option
       key={option.value}
       value={option.value}
       disabled={option.disabled}
      >
       {option.label}
      </option>
))}
    </select>
    {error&&(
     <p className="mt-1 text-nier-caption text-nier-accent-red">{error}</p>
)}
   </div>
)
 }
)
Select.displayName='Select'

export{Select}
