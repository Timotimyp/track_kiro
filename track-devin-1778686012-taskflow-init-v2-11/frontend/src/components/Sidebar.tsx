import type { Project, Task, View } from '../types'
import { isOverdue } from '../utils'

interface SidebarProps {
  view: View
  tasks: Task[]
  projects: Project[]
  onSelect: (view: View) => void
}

const PROJECT_SLUGS: Record<string, View> = {
  'Website Redesign': 'proj-website',
  'Backend API': 'proj-backend',
  'Mobile App': 'proj-mobile',
  Operations: 'proj-ops',
}

export function Sidebar({ view, tasks, projects, onSelect }: SidebarProps) {
  const myTasksCount = tasks.filter((t) => t.assignee === 'YO' && t.status !== 'done').length
  const overdueCount = tasks.filter((t) => isOverdue(t)).length

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <div className="logo-icon">T</div>
        <div>
          <div className="logo-name">TaskFlow</div>
          <div className="logo-sub">v1.0.0</div>
        </div>
      </div>

      <div className="nav-section">
        <div className="nav-label">Menu</div>
        <NavItem icon="⊞" label="Dashboard" active={view === 'dashboard'} onClick={() => onSelect('dashboard')} />
        <NavItem
          icon="✓"
          label="My Tasks"
          active={view === 'mytasks'}
          badge={myTasksCount}
          onClick={() => onSelect('mytasks')}
        />
        <NavItem
          icon="≡"
          label="All Tasks"
          active={view === 'all'}
          badge={tasks.length}
          onClick={() => onSelect('all')}
        />
        <NavItem
          icon="!"
          label="Overdue"
          active={view === 'overdue'}
          badge={overdueCount}
          badgeDanger
          onClick={() => onSelect('overdue')}
        />
      </div>

      <div className="nav-section">
        <div className="nav-label">Projects</div>
        <div className="sidebar-projects">
          {projects.map((p) => {
            const slug = PROJECT_SLUGS[p.name]
            const active = slug ? view === slug : false
            return (
              <div
                key={p.slug}
                className={`proj-item ${active ? 'active' : ''}`}
                onClick={() => slug && onSelect(slug)}
              >
                <div className="proj-dot" style={{ background: p.color }} /> {p.name}
              </div>
            )
          })}
        </div>
      </div>

      <div className="sidebar-bottom">
        <div className="user-row">
          <div className="user-av">YO</div>
          <div>
            <div className="user-name">You (Owner)</div>
            <div className="user-role">Admin</div>
          </div>
        </div>
      </div>
    </aside>
  )
}

function NavItem({
  icon,
  label,
  active,
  badge,
  badgeDanger,
  onClick,
}: {
  icon: string
  label: string
  active: boolean
  badge?: number
  badgeDanger?: boolean
  onClick: () => void
}) {
  return (
    <div className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}>
      <span className="nav-icon">{icon}</span> {label}
      {badge !== undefined && (
        <span className={`nav-badge ${badgeDanger ? 'danger' : ''}`}>{badge}</span>
      )}
    </div>
  )
}
