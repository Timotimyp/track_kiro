import type { Filter, SortKey, Task, View } from './types'

export const AVATAR_COLORS: Record<string, string> = {
  AK: '#7c6af7',
  BL: '#3ecf8e',
  CJ: '#f5a623',
  DM: '#4d9ef7',
  YO: '#f56060',
}

export const VIEW_TITLES: Record<View, string> = {
  dashboard: 'Dashboard',
  mytasks: 'My Tasks',
  all: 'All Tasks',
  overdue: 'Overdue Tasks',
  'proj-website': 'Website Redesign',
  'proj-backend': 'Backend API',
  'proj-mobile': 'Mobile App',
  'proj-ops': 'Operations',
}

const PROJECT_BY_SLUG: Partial<Record<View, string>> = {
  'proj-website': 'Website Redesign',
  'proj-backend': 'Backend API',
  'proj-mobile': 'Mobile App',
  'proj-ops': 'Operations',
}

export function today(): Date {
  const d = new Date()
  d.setHours(0, 0, 0, 0)
  return d
}

export function isOverdue(task: Task, now: Date = today()): boolean {
  if (task.status === 'done' || !task.due) return false
  return new Date(task.due) < now
}

export function formatDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return ''
  return value
}

export function statusLabel(status: Task['status']): string {
  return status === 'todo' ? 'To Do' : status === 'inprog' ? 'In Progress' : 'Done'
}

export function applyView(tasks: Task[], view: View): Task[] {
  if (view === 'mytasks') return tasks.filter((t) => t.assignee === 'YO')
  if (view === 'overdue') return tasks.filter((t) => isOverdue(t))
  const proj = PROJECT_BY_SLUG[view]
  if (proj) return tasks.filter((t) => t.proj === proj)
  return tasks
}

export function applyFilter(tasks: Task[], filter: Filter): Task[] {
  switch (filter) {
    case 'todo':
    case 'inprog':
    case 'done':
      return tasks.filter((t) => t.status === filter)
    case 'high':
      return tasks.filter((t) => t.priority === 'high')
    default:
      return tasks
  }
}

export function applySearch(tasks: Task[], query: string): Task[] {
  const q = query.trim().toLowerCase()
  if (!q) return tasks
  return tasks.filter(
    (t) => t.title.toLowerCase().includes(q) || t.proj.toLowerCase().includes(q),
  )
}

const PRIORITY_ORDER: Record<Task['priority'], number> = { high: 0, medium: 1, low: 2 }
const STATUS_ORDER: Record<Task['status'], number> = { inprog: 0, todo: 1, done: 2 }

export function applySort(tasks: Task[], sort: SortKey): Task[] {
  if (!sort) return tasks
  const copy = [...tasks]
  if (sort === 'priority') copy.sort((a, b) => PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority])
  else if (sort === 'due')
    copy.sort((a, b) => new Date(a.due || '9999').getTime() - new Date(b.due || '9999').getTime())
  else if (sort === 'status') copy.sort((a, b) => STATUS_ORDER[a.status] - STATUS_ORDER[b.status])
  return copy
}

export function exportTasksToCsv(tasks: Task[]): void {
  const rows: string[][] = [
    ['Title', 'Project', 'Priority', 'Category', 'Status', 'Assignee', 'Due Date', 'Due Time'],
  ]
  tasks.forEach((t) =>
    rows.push([
      t.title,
      t.proj,
      t.priority,
      t.tag,
      t.status,
      t.assignee,
      t.due || '',
      t.due_time || '',
    ]),
  )
  const csv = rows.map((r) => r.map((c) => `"${c}"`).join(',')).join('\n')
  const a = document.createElement('a')
  a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv)
  a.download = 'tasks.csv'
  a.click()
}
