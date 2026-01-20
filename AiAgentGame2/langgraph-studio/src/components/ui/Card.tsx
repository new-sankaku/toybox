import{forwardRef,HTMLAttributes}from'react'
import{cn}from'@/lib/utils'

export interface CardProps extends HTMLAttributes<HTMLDivElement>{}

const Card=forwardRef<HTMLDivElement,CardProps>(
 ({className,...props},ref)=>(
  <div
   ref={ref}
   className={cn('nier-card',className)}
   {...props}
  />
)
)
Card.displayName='Card'

export interface CardHeaderProps extends HTMLAttributes<HTMLDivElement>{}

const CardHeader=forwardRef<HTMLDivElement,CardHeaderProps>(
 ({className,...props},ref)=>(
  <div
   ref={ref}
   className={cn('nier-card-header',className)}
   {...props}
  />
)
)
CardHeader.displayName='CardHeader'

export interface CardContentProps extends HTMLAttributes<HTMLDivElement>{}

const CardContent=forwardRef<HTMLDivElement,CardContentProps>(
 ({className,...props},ref)=>(
  <div
   ref={ref}
   className={cn('nier-card-body',className)}
   {...props}
  />
)
)
CardContent.displayName='CardContent'

export interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement>{}

const CardTitle=forwardRef<HTMLHeadingElement,CardTitleProps>(
 ({className,...props},ref)=>(
  <h3
   ref={ref}
   className={cn('text-nier-h2 font-medium tracking-nier',className)}
   {...props}
  />
)
)
CardTitle.displayName='CardTitle'

export interface CardDescriptionProps extends HTMLAttributes<HTMLParagraphElement>{}

const CardDescription=forwardRef<HTMLParagraphElement,CardDescriptionProps>(
 ({className,...props},ref)=>(
  <p
   ref={ref}
   className={cn('text-nier-small text-nier-text-light',className)}
   {...props}
  />
)
)
CardDescription.displayName='CardDescription'

export{Card,CardHeader,CardContent,CardTitle,CardDescription}
