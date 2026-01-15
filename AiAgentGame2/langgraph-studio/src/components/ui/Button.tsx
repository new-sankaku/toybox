import * as React from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 tracking-nier font-normal transition-all duration-nier-fast disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default:
          'bg-nier-bg-panel border border-nier-border-dark text-nier-text-main hover:bg-nier-bg-selected active:bg-nier-bg-header active:text-nier-text-header',
        primary:
          'bg-nier-bg-header text-nier-text-header hover:bg-nier-text-main',
        danger:
          'bg-nier-bg-panel border border-nier-accent-red text-nier-accent-red hover:bg-nier-accent-red hover:text-white',
        success:
          'bg-nier-bg-panel border border-nier-accent-green text-nier-accent-green hover:bg-nier-accent-green hover:text-white',
        ghost:
          'hover:bg-nier-bg-selected text-nier-text-main',
        link:
          'text-nier-text-main underline-offset-4 hover:underline'
      },
      size: {
        default: 'h-10 px-6 py-2',
        sm: 'h-8 px-4 text-nier-small',
        lg: 'h-12 px-8 text-nier-h2',
        icon: 'h-10 w-10'
      }
    },
    defaultVariants: {
      variant: 'default',
      size: 'default'
    }
  }
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    )
  }
)
Button.displayName = 'Button'

export { Button, buttonVariants }
