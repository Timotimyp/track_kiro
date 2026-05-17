import { forwardRef } from 'react'
import type { MicrosoftAuthState } from '../useMicrosoftAuth'

interface TopbarProps {
  title: string
  search: string
  onSearchChange: (value: string) => void
  onExport: () => void
  onNewTask: () => void
  onOpenAssistant: () => void
  onToggleMenu?: () => void
  ms: MicrosoftAuthState
}

export const Topbar = forwardRef<HTMLInputElement, TopbarProps>(function Topbar(
  { title, search, onSearchChange, onExport, onNewTask, onOpenAssistant, onToggleMenu, ms },
  ref,
) {
  return (
    <div className="topbar">
      {onToggleMenu && (
        <button
          className="topbar-burger"
          onClick={onToggleMenu}
          aria-label="Toggle menu"
        >
          <span></span>
          <span></span>
          <span></span>
        </button>
      )}
      <div className="topbar-title">{title}</div>
      <div className="search-box">
        <span style={{ fontSize: 14, color: 'var(--text3)' }}>🔍</span>
        <input
          ref={ref}
          type="text"
          placeholder="Search tasks…"
          value={search}
          onChange={(e) => onSearchChange(e.target.value)}
        />
      </div>
      {ms.enabled && (
        ms.isSignedIn ? (
          <button
            className="topbar-btn btn-ms"
            onClick={ms.signOut}
            title={ms.username ?? undefined}
          >
            <span className="ms-badge" aria-hidden>MS</span>
            <span className="ms-name">{ms.displayName ?? ms.username}</span>
            <span className="ms-signout-x" aria-hidden>✕</span>
          </button>
        ) : (
          <button
            className="topbar-btn btn-ms"
            onClick={ms.signIn}
            title="Sign in with Microsoft to check your Outlook calendar"
          >
            <span className="ms-badge" aria-hidden>MS</span>
            Sign in with Microsoft
          </button>
        )
      )}
      <button
        className="topbar-btn btn-assistant"
        onClick={onOpenAssistant}
        title="Voice / AI assistant"
      >
        🎙 AI
      </button>
      <button className="topbar-btn btn-ghost btn-export" onClick={onExport}>
        ⬇ Export
      </button>
      <button className="topbar-btn btn-primary btn-new" onClick={onNewTask}>
        + New Task
      </button>
    </div>
  )
})
