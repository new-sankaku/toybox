import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'
import { CheckCircle, XCircle, RotateCcw, MessageSquare } from 'lucide-react'

interface ApprovalButtonsProps {
  onApprove: () => void
  onReject: () => void
  onRequestChanges: () => void
  onAddComment?: () => void
  disabled?: boolean
  layout?: 'horizontal' | 'vertical'
  size?: 'sm' | 'md' | 'lg'
}

export function ApprovalButtons({
  onApprove,
  onReject,
  onRequestChanges,
  onAddComment,
  disabled = false,
  layout = 'vertical',
  size = 'md'
}: ApprovalButtonsProps): JSX.Element {
  const isHorizontal = layout === 'horizontal'

  const buttonClasses = cn(
    isHorizontal ? '' : 'w-full justify-start gap-3',
    size === 'sm' && 'text-nier-small py-1.5',
    size === 'lg' && 'text-nier-body py-3'
  )

  return (
    <div
      className={cn(
        isHorizontal ? 'flex items-center gap-3' : 'space-y-3'
      )}
    >
      {/* Approve Button */}
      <Button
        variant="success"
        className={buttonClasses}
        onClick={onApprove}
        disabled={disabled}
      >
        <CheckCircle size={size === 'sm' ? 14 : size === 'lg' ? 20 : 18} />
        {!isHorizontal && <span>承認</span>}
      </Button>

      {/* Request Changes Button */}
      <Button
        className={buttonClasses}
        onClick={onRequestChanges}
        disabled={disabled}
      >
        <RotateCcw size={size === 'sm' ? 14 : size === 'lg' ? 20 : 18} />
        {!isHorizontal && <span>変更を要求</span>}
      </Button>

      {/* Reject Button */}
      <Button
        variant="danger"
        className={buttonClasses}
        onClick={onReject}
        disabled={disabled}
      >
        <XCircle size={size === 'sm' ? 14 : size === 'lg' ? 20 : 18} />
        {!isHorizontal && <span>却下</span>}
      </Button>

      {/* Add Comment Button (Optional) */}
      {onAddComment && !isHorizontal && (
        <Button
          variant="ghost"
          className={cn(buttonClasses, 'text-nier-text-light')}
          onClick={onAddComment}
          disabled={disabled}
        >
          <MessageSquare size={size === 'sm' ? 14 : size === 'lg' ? 20 : 18} />
          <span>コメントを追加</span>
        </Button>
      )}
    </div>
  )
}

// Compact version for inline use
export function ApprovalButtonsCompact({
  onApprove,
  onReject,
  onRequestChanges,
  disabled = false
}: Omit<ApprovalButtonsProps, 'onAddComment' | 'layout' | 'size'>): JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <button
        className={cn(
          'p-1.5 rounded-sm transition-colors',
          'hover:bg-nier-accent-green/20 text-nier-accent-green',
          disabled && 'opacity-50 cursor-not-allowed'
        )}
        onClick={onApprove}
        disabled={disabled}
        title="承認"
      >
        <CheckCircle size={16} />
      </button>
      <button
        className={cn(
          'p-1.5 rounded-sm transition-colors',
          'hover:bg-nier-accent-orange/20 text-nier-accent-orange',
          disabled && 'opacity-50 cursor-not-allowed'
        )}
        onClick={onRequestChanges}
        disabled={disabled}
        title="変更を要求"
      >
        <RotateCcw size={16} />
      </button>
      <button
        className={cn(
          'p-1.5 rounded-sm transition-colors',
          'hover:bg-nier-accent-red/20 text-nier-accent-red',
          disabled && 'opacity-50 cursor-not-allowed'
        )}
        onClick={onReject}
        disabled={disabled}
        title="却下"
      >
        <XCircle size={16} />
      </button>
    </div>
  )
}
