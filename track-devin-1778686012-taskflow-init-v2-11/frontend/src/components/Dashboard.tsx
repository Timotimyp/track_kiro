import type { Task } from '../types'
import { isOverdue } from '../utils'
import { TaskTable } from './TaskTable'

interface DashboardProps {
  tasks: Task[]
  onToggle: (task: Task) => void
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
}

export function Dashboard({ tasks, onToggle, onEdit, onDelete }: DashboardProps) {
  const total = tasks.length
  const done = tasks.filter((t) => t.status === 'done').length
  const inprog = tasks.filter((t) => t.status === 'inprog').length
  const todo = tasks.filter((t) => t.status === 'todo').length
  const overdue = tasks.filter((t) => isOverdue(t)).length
  const pct = total === 0 ? 0 : Math.round((done / total) * 100)

  return (
    <div>
      <div className="stats-row">
        <StatCard color="blue" icon="≡" label="Total" num={total} caption="Total Tasks" />
        <StatCard color="amber" icon="▷" label="Active" num={inprog} caption="In Progress" />
        <StatCard color="green" icon="✓" label="Done" num={done} caption="Completed" />
        <StatCard color="red" icon="!" label="Alert" num={overdue} caption="Overdue" />
      </div>

      <div className="prog-section">
        <div className="prog-header">
          <div className="prog-title">Overall Completion</div>
          <div className="prog-pct">{pct}% complete</div>
        </div>
        <div className="prog-bar">
          <div className="prog-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="prog-labels">
          <div className="prog-leg">
            <div className="prog-dot" style={{ background: 'var(--green)' }} />
            {done} Done
          </div>
          <div className="prog-leg">
            <div className="prog-dot" style={{ background: 'var(--amber)' }} />
            {inprog} In Progress
          </div>
          <div className="prog-leg">
            <div className="prog-dot" style={{ background: 'var(--text3)' }} />
            {todo} To Do
          </div>
        </div>
      </div>

      <TaskTable
        tasks={[...tasks]
          .sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
          .slice(0, 5)}
        label="Recent Tasks"
        onToggle={onToggle}
        onEdit={onEdit}
        onDelete={onDelete}
      />
    </div>
  )
}

function StatCard({
  color,
  icon,
  label,
  num,
  caption,
}: {
  color: 'blue' | 'amber' | 'green' | 'red'
  icon: string
  label: string
  num: number
  caption: string
}) {
  const bgVar = `var(--${color}-bg)`
  const colVar = `var(--${color})`
  return (
    <div className="stat-card">
      <div className="stat-top">
        <div className="stat-icon" style={{ background: bgVar, color: colVar }}>
          {icon}
        </div>
        <span className="stat-change" style={{ background: bgVar, color: colVar }}>
          {label}
        </span>
      </div>
      <div className="stat-num">{num}</div>
      <div className="stat-lbl">{caption}</div>
    </div>
  )
}
