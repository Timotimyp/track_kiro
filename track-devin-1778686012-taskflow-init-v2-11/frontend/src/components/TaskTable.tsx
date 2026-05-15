import type { Filter, SortKey, Task } from '../types'
import { AVATAR_COLORS, formatDate, formatTime, isOverdue, statusLabel } from '../utils'

interface TaskTableProps {
  tasks: Task[]
  totalCount?: number
  label?: string
  showFilters?: boolean
  filter?: Filter
  onFilterChange?: (filter: Filter) => void
  onSortChange?: (sort: SortKey) => void
  onToggle: (task: Task) => void
  onEdit: (task: Task) => void
  onDelete: (task: Task) => void
}

export function TaskTable({
  tasks,
  totalCount,
  label,
  showFilters,
  filter = 'all',
  onFilterChange,
  onSortChange,
  onToggle,
  onEdit,
  onDelete,
}: TaskTableProps) {
  return (
    <div>
      {showFilters && (
        <div className="filters-row">
          <FilterButton current={filter} value="all" label={`All (${totalCount ?? tasks.length})`} onClick={onFilterChange} />
          <FilterButton current={filter} value="todo" label="To Do" onClick={onFilterChange} />
          <FilterButton current={filter} value="inprog" label="In Progress" onClick={onFilterChange} />
          <FilterButton current={filter} value="done" label="Done" onClick={onFilterChange} />
          <FilterButton current={filter} value="high" label="🔴 High Priority" onClick={onFilterChange} />
          <div className="filters-right">
            <select
              className="sort-select"
              defaultValue=""
              onChange={(e) => onSortChange?.(e.target.value as SortKey)}
            >
              <option value="">Sort by…</option>
              <option value="due">Due Date</option>
              <option value="priority">Priority</option>
              <option value="status">Status</option>
            </select>
          </div>
        </div>
      )}
      <div className="section-head">
        {label && <div className="section-title">{label}</div>}
        <div className="section-meta">
          {tasks.length} task{tasks.length !== 1 ? 's' : ''}
        </div>
      </div>
      <div className="task-table">
        <div className="table-head">
          <div />
          <div>Task</div>
          <div>Category</div>
          <div>Priority</div>
          <div>Status</div>
          <div>Assignee</div>
          <div>Due</div>
        </div>
        {tasks.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">🎉</div>
            <div className="empty-text">No tasks here!</div>
          </div>
        ) : (
          tasks.map((t) => (
            <div
              key={t.id}
              className={`task-row ${t.status === 'done' ? 'done-row' : ''}`}
              onClick={() => onEdit(t)}
            >
              <div
                className={`chkbox ${t.status === 'done' ? 'checked' : ''}`}
                onClick={(e) => {
                  e.stopPropagation()
                  onToggle(t)
                }}
              />
              <div>
                <div className="task-name">{t.title}</div>
                <div className="task-proj">{t.proj}</div>
              </div>
              <div>
                <span className={`badge badge-${t.tag}`}>{t.tag}</span>
              </div>
              <div>
                <span className={`badge badge-${t.priority}`}>{t.priority}</span>
              </div>
              <div>
                <span className="status-dot">
                  <span className={`dot dot-${t.status}`} />
                  <span style={{ fontSize: 12, color: 'var(--text2)' }}>{statusLabel(t.status)}</span>
                </span>
              </div>
              <div className="assignee-cell">
                <div
                  className="av-sm"
                  style={{
                    background: `${AVATAR_COLORS[t.assignee] || '#888'}22`,
                    color: AVATAR_COLORS[t.assignee] || '#888',
                  }}
                >
                  {t.assignee}
                </div>
                <span style={{ fontSize: 12, color: 'var(--text3)' }}>{t.assignee}</span>
              </div>
              <div className="due-cell">
                <div className={`due-text ${isOverdue(t) ? 'due-over' : ''}`}>
                  <div>{formatDate(t.due)}</div>
                  {t.due_time && <div className="due-time">{formatTime(t.due_time)}</div>}
                </div>
                <div className="row-actions">
                  <button
                    className="act-btn"
                    title="Edit"
                    onClick={(e) => {
                      e.stopPropagation()
                      onEdit(t)
                    }}
                  >
                    ✎
                  </button>
                  <button
                    className="act-btn"
                    title="Delete"
                    style={{ color: 'var(--red)' }}
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(t)
                    }}
                  >
                    ✕
                  </button>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

function FilterButton({
  current,
  value,
  label,
  onClick,
}: {
  current: Filter
  value: Filter
  label: string
  onClick?: (value: Filter) => void
}) {
  return (
    <button
      className={`filter-btn ${current === value ? 'active' : ''}`}
      onClick={() => onClick?.(value)}
    >
      {label}
    </button>
  )
}
