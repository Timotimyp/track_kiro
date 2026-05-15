interface ToastProps {
  message: string | null
  variant?: 'success' | 'error'
}

export function Toast({ message, variant = 'success' }: ToastProps) {
  return (
    <div className={`toast ${message ? 'show' : ''} ${variant === 'error' ? 'error' : ''}`}>
      <div className="toast-dot" />
      <span>{message || ''}</span>
    </div>
  )
}
