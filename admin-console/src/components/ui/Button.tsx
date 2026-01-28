import{cn}from'@/lib/utils'
import{type ButtonHTMLAttributes}from'react'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>{
 variant?:'default'|'primary'|'secondary'|'danger'|'ghost'
 size?:'sm'|'md'
}

const variants:Record<string,string>={
 default:'bg-nier-bg-panel border border-nier-border-light text-nier-text-main hover:bg-nier-bg-selected',
 primary:'bg-nier-bg-header text-nier-text-header hover:opacity-90',
 secondary:'bg-nier-bg-panel border border-nier-border-dark text-nier-text-main hover:bg-nier-bg-selected',
 danger:'bg-nier-accent-red text-white hover:opacity-90',
 ghost:'text-nier-text-light hover:text-nier-text-main hover:bg-nier-bg-panel'
}

const sizes:Record<string,string>={
 sm:'px-3 py-1.5 text-nier-caption',
 md:'px-4 py-2 text-nier-small'
}

export function Button({variant='default',size='md',className,disabled,...props}:ButtonProps){
 return(
  <button
   className={cn(
    'inline-flex items-center justify-center transition-colors',
    variants[variant],
    sizes[size],
    disabled&&'opacity-50 cursor-not-allowed',
    className
   )}
   disabled={disabled}
   {...props}
  />
 )
}
