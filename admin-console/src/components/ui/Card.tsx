import{cn}from'@/lib/utils'
import{type HTMLAttributes}from'react'

export function Card({className,...props}:HTMLAttributes<HTMLDivElement>){
 return <div className={cn('bg-nier-bg-panel border border-nier-border-light',className)} {...props}/>
}

export function CardHeader({className,...props}:HTMLAttributes<HTMLDivElement>){
 return <div className={cn('px-4 py-3 flex items-center gap-2',className)} {...props}/>
}

export function CardContent({className,...props}:HTMLAttributes<HTMLDivElement>){
 return <div className={cn('px-4 py-3',className)} {...props}/>
}
