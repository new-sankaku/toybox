import{forwardRef,HTMLAttributes,ReactNode}from'react'
import{cn}from'@/lib/utils'

export interface PanelProps extends HTMLAttributes<HTMLDivElement>{
 title?:string
 headerRight?:ReactNode
 noPadding?:boolean
}

const Panel = forwardRef<HTMLDivElement,PanelProps>(
 ({className,title,headerRight,noPadding,children,...props},ref) => {
  return(
   <div
    ref={ref}
    className={cn('bg-nier-bg-panel border border-nier-border-light',className)}
    {...props}
   >
    {title && (
     <div className="flex items-center justify-between bg-nier-bg-header text-nier-text-header px-4 py-2">
      <span className="text-nier-small tracking-nier">{title}</span>
      {headerRight}
     </div>
    )}
    <div className={cn(!noPadding && 'p-4')}>
     {children}
    </div>
   </div>
  )
 }
)
Panel.displayName = 'Panel'

export{Panel}
