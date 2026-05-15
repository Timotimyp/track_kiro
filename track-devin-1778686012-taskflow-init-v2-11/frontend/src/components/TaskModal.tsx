import { useEffect, useRef, useState } from 'react'
import type { AssistantConflict, Project, Task, TaskInput, User } from '../types'
import { formatDate, formatTime } from '../utils'

interface TaskModalProps {
  initial: Task | null
  prefill?: TaskInput | null
  recommendation?: string | null
  conflict?: AssistantConflict | null
  projects: Project[]
  users: User[]
  msSignedIn?: boolean
  onClose: () => void
  onSave: (
    data: TaskInput,
    id: string | null,
    opts?: { addToOutlook?: boolean },
  ) => Promise<void> | void
}

function defaultDate(): string {
  return new Date().toISOString().split('T')[0]
}

function formFromInitial(
  initial: Task | null,
  prefill: TaskInput | null | undefined,
  projects: Project[],
): TaskInput {
  if (initial) {
    return {
      title: initial.title,
      desc: initial.desc,
      status: initial.status,
      priority: initial.priority,
      tag: initial.tag,
      assignee: initial.assignee,
      due: initial.due ?? '',
      due_time: initial.due_time ?? '',
      proj: initial.proj,
    }
  }
  if (prefill) {
    return {
      ...prefill,
      due: prefill.due ?? '',
      due_time: prefill.due_time ?? '',
    }
  }
  return {
    title: '',
    desc: '',
    status: 'todo',
    priority: 'medium',
    tag: 'dev',
    assignee: 'YO',
    due: defaultDate(),
    due_time: '',
    proj: projects[0]?.name || 'Website Redesign',
  }
}

export function TaskModal({
  initial,
  prefill,
  recommendation,
  conflict,
  projects,
  users,
  msSignedIn,
  onClose,
  onSave,
}: TaskModalProps) {
  const [form, setForm] = useState<TaskInput>(() => formFromInitial(initial, prefill, projects))
  const [titleError, setTitleError] = useState(false)
  const [conflictDismissed, setConflictDismissed] = useState(false)
  const [addToOutlook, setAddToOutlook] = useState(false)
  const titleRef = useRef<HTMLInputElement>(null)

  const stillConflicts =
    !!conflict &&
    !conflictDismissed &&
    !!form.due &&
    !!form.due_time &&
    conflict.conflicts.some(
      (c) => c.due === form.due && c.due_time === form.due_time,
    )

  function applyAlternative(due: string, due_time: string) {
    setForm((f) => ({ ...f, due, due_time }))
  }

  useEffect(() => {
    titleRef.current?.focus()
  }, [])

  function update<K extends keyof TaskInput>(key: K, value: TaskInput[K]) {
    setForm((f) => ({ ...f, [key]: value }))
  }

  async function save() {
    const title = form.title.trim()
    if (!title) {
      setTitleError(true)
      titleRef.current?.focus()
      return
    }
    setTitleError(false)
    await onSave(
      { ...form, title, desc: form.desc.trim() },
      initial?.id ?? null,
      { addToOutlook: addToOutlook && !!form.due && !!form.due_time },
    )
  }

  return (
    <div className="modal-bg" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <div className="modal-title">
            {initial ? 'Edit Task' : prefill ? '✨ Review AI Suggestion' : 'Add New Task'}
          </div>
          <button className="modal-close" onClick={onClose}>
            ✕
          </button>
        </div>
        {recommendation && (
          <div className="assistant-recommendation">
            <span className="assistant-recommendation-icon">🤖</span>
            <span>{recommendation}</span>
          </div>
        )}
        {stillConflicts && conflict && (
          <div className="assistant-conflict" role="alert">
            <div className="assistant-conflict-header">
              <span className="assistant-conflict-icon">⚠️</span>
              <div>
                <div className="assistant-conflict-title">Конфликт по времени</div>
                <div className="assistant-conflict-body">
                  {conflict.conflicts.map((c) => (
                    <div key={c.id}>
                      <span className={`assistant-conflict-source assistant-conflict-source-${c.source}`}>
                        {c.source === 'outlook' ? 'Outlook' : 'TaskFlow'}
                      </span>{' '}
                      «{c.title}» уже стоит на {formatDate(c.due)} в {formatTime(c.due_time)}
                    </div>
                  ))}
                </div>
              </div>
            </div>
            {conflict.alternatives.length > 0 && (
              <div className="assistant-conflict-alts">
                <span className="assistant-conflict-alts-label">Свободные слоты:</span>
                {conflict.alternatives.map((alt) => (
                  <button
                    key={`${alt.due}T${alt.due_time}`}
                    type="button"
                    className="assistant-conflict-alt"
                    onClick={() => applyAlternative(alt.due, alt.due_time)}
                  >
                    {alt.due === conflict.conflicts[0]?.due
                      ? formatTime(alt.due_time)
                      : `${formatDate(alt.due)} · ${formatTime(alt.due_time)}`}
                  </button>
                ))}
              </div>
            )}
            <button
              type="button"
              className="assistant-conflict-dismiss"
              onClick={() => setConflictDismissed(true)}
            >
              Игнорировать и сохранить как есть
            </button>
          </div>
        )}
        <div className="form-group">
          <label className="form-label">Task Title *</label>
          <input
            ref={titleRef}
            className={`form-input ${titleError ? 'error' : ''}`}
            type="text"
            placeholder="What needs to be done?"
            value={form.title}
            onChange={(e) => update('title', e.target.value)}
          />
        </div>
        <div className="form-group">
          <label className="form-label">Description</label>
          <textarea
            className="form-input"
            rows={2}
            placeholder="Optional details…"
            style={{ resize: 'none' }}
            value={form.desc}
            onChange={(e) => update('desc', e.target.value)}
          />
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Priority</label>
            <select
              className="form-input form-select"
              value={form.priority}
              onChange={(e) => update('priority', e.target.value as TaskInput['priority'])}
            >
              <option value="high">🔴 High</option>
              <option value="medium">🟡 Medium</option>
              <option value="low">🟢 Low</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Category</label>
            <select
              className="form-input form-select"
              value={form.tag}
              onChange={(e) => update('tag', e.target.value as TaskInput['tag'])}
            >
              <option value="dev">Dev</option>
              <option value="design">Design</option>
              <option value="qa">QA</option>
              <option value="pm">PM</option>
            </select>
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Assignee</label>
            <select
              className="form-input form-select"
              value={form.assignee}
              onChange={(e) => update('assignee', e.target.value)}
            >
              {users.map((u) => (
                <option key={u.code} value={u.code}>
                  {u.code} — {u.name}
                </option>
              ))}
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Due Date</label>
            <input
              className="form-input"
              type="date"
              value={form.due ?? ''}
              onChange={(e) => update('due', e.target.value)}
            />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Time (optional)</label>
            <input
              className="form-input"
              type="time"
              value={form.due_time ?? ''}
              onChange={(e) => update('due_time', e.target.value)}
            />
          </div>
          <div className="form-group" />
        </div>
        <div className="form-group">
          <label className="form-label">Project</label>
          <select
            className="form-input form-select"
            value={form.proj}
            onChange={(e) => update('proj', e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.slug} value={p.name}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        {!initial && msSignedIn && (
          <label
            className={`outlook-checkbox ${!form.due || !form.due_time ? 'disabled' : ''}`}
            title={
              !form.due || !form.due_time
                ? 'Set both date and time to add this task to your Outlook calendar'
                : undefined
            }
          >
            <input
              type="checkbox"
              checked={addToOutlook}
              disabled={!form.due || !form.due_time}
              onChange={(e) => setAddToOutlook(e.target.checked)}
            />
            <span>📅 Also add to my Outlook Calendar</span>
          </label>
        )}
        <div className="modal-actions">
          <button className="topbar-btn btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="topbar-btn btn-primary" onClick={save}>
            Save Task
          </button>
        </div>
      </div>
    </div>
  )
}
