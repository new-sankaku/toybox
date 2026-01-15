import { forwardRef, HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'
import { cva, type VariantProps } from 'class-variance-authority'

const categoryMarkerVariants = cva('nier-category-marker', {
  variants: {
    status: {
      system: 'system',
      running: 'running',
      pending: 'pending',
      complete: 'complete',
      info: 'info'
    },
    size: {
      sm: 'w-0.5 h-3',
      default: 'w-1 h-4',
      lg: 'w-1.5 h-5'
    }
  },
  defaultVariants: {
    status: 'info',
    size: 'default'
  }
})

export interface CategoryMarkerProps
  extends HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof categoryMarkerVariants> {}

const CategoryMarker = forwardRef<HTMLDivElement, CategoryMarkerProps>(
  ({ className, status, size, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(categoryMarkerVariants({ status, size }), className)}
      {...props}
    />
  )
)
CategoryMarker.displayName = 'CategoryMarker'

export { CategoryMarker, categoryMarkerVariants }
