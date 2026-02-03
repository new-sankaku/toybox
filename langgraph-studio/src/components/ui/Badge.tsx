import{HTMLAttributes}from'react'
import{cva,type VariantProps}from'class-variance-authority'
import{cn}from'@/lib/utils'

const badgeVariants=cva(
 'inline-flex items-center px-2 py-0.5 text-nier-caption tracking-nier font-normal',
 {
  variants:{
   variant:{
    default:'nier-surface-selected',
    outline:'border border-nier-border-dark text-nier-text-main',
    red:'bg-nier-accent-red/20 text-nier-accent-red border border-nier-accent-red/40',
    orange:'bg-nier-accent-orange/20 text-nier-accent-orange border border-nier-accent-orange/40',
    green:'bg-nier-accent-green/20 text-nier-accent-green border border-nier-accent-green/40',
    blue:'bg-nier-accent-blue/20 text-nier-accent-blue border border-nier-accent-blue/40'
   }
  },
  defaultVariants:{
   variant:'default'
  }
 }
)

export interface BadgeProps
 extends HTMLAttributes<HTMLSpanElement>,
 VariantProps<typeof badgeVariants>{}

function Badge({className,variant,...props}:BadgeProps){
 return(
  <span className={cn(badgeVariants({variant}),className)} {...props}/>
)
}

export{Badge,badgeVariants}
