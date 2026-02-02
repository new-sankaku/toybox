import{HTMLAttributes,forwardRef}from'react'
import{cn}from'@/lib/utils'

export interface DiamondMarkerProps extends HTMLAttributes<HTMLDivElement>{
 children:React.ReactNode
}

const DiamondMarker=forwardRef<HTMLDivElement,DiamondMarkerProps>(
 ({className,children,...props},ref)=>(
  <div
   ref={ref}
   className={cn('nier-diamond',className)}
   {...props}
  >
   {children}
  </div>
)
)
DiamondMarker.displayName='DiamondMarker'

export{DiamondMarker}
