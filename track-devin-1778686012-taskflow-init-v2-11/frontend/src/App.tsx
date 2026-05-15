import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api'
import { useMicrosoftAuth } from './useMicrosoftAuth'
import { AssistantPanel } from './components/AssistantPanel'
import { Dashboard } from './components/Dashboard'
import { Sidebar } from './components/Sidebar'
import { TaskModal } from './components/TaskModal'
import { TaskTable } from './components/TaskTable'
import { Toast } from './components/Toast'
import { Topbar } from './components/Topbar'
import type {
  AssistantConflict,
  AssistantResponse,
  Filter,
  Project,
  SortKey,
  Task,
  TaskInput,
  User,
  View,
} from './types'
import { VIEW_TITLES, applyFilter, applySearch, applySort, applyView, exportTasksToCsv } from './utils'

interface ToastState {
  message: string
  variant: 'success' | 'error'
}

function App() {
  const ms = useMicrosoftAuth()
  const [tasks, setTasks] = useState<Task[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState<View>('dashboard')
  const [filter, setFilter] = useState<Filter>('all')
  const [sort, setSort] = useState<SortKey>('')
  const [search, setSearch] = useState('')
  const [modal, setModal] = useState<{
    key: number
    editing: Task | null
    prefill: TaskInput | null
    recommendation: string | null
    conflict: AssistantConflict | null
  } | null>(null)
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const toastTimer = useRef<number | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const showToast = useCallback((message: string, variant: 'success' | 'error' = 'success') => {
    setToast({ message, variant })
    if (toastTimer.current) window.clearTimeout(toastTimer.current)
    toastTimer.current = window.setTimeout(() => setToast(null), 2500)
  }, [])

  const refresh = useCallback(async () => {
    try {
      const [t, p, u] = await Promise.all([api.listTasks(), api.listProjects(), api.listUsers()])
      setTasks(t)
      setProjects(p)
      setUsers(u)
    } catch (err) {
      console.error(err)
      showToast('Failed to load data', 'error')
    } finally {
      setLoading(false)
    }
  }, [showToast])

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh()
  }, [refresh])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        setModal(null)
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        searchRef.current?.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const title = VIEW_TITLES[view] ?? view

  const filteredTasks = useMemo(() => {
    const byView = applyView(tasks, view)
    const byFilter = applyFilter(byView, filter)
    const byQuery = applySearch(byFilter, search)
    return applySort(byQuery, sort)
  }, [tasks, view, filter, search, sort])

  function selectView(next: View) {
    setView(next)
    setFilter('all')
    setSort('')
  }

  function openCreate() {
    setModal({
      key: Date.now(),
      editing: null,
      prefill: null,
      recommendation: null,
      conflict: null,
    })
  }

  function openEdit(task: Task) {
    setModal({
      key: Date.now(),
      editing: task,
      prefill: null,
      recommendation: null,
      conflict: null,
    })
  }

  async function handleAssistantSubmit(text: string, language: 'ru-RU' | 'en-US'): Promise<AssistantResponse> {
    const token = ms.isSignedIn ? await ms.getToken() : null
    return api.askAssistant(text, language, token)
  }

  function handleAssistantSuggestion(response: AssistantResponse) {
    const prefill: TaskInput = {
      title: response.task.title,
      desc: response.task.desc ?? '',
      status: response.task.status,
      priority: response.task.priority,
      tag: response.task.tag,
      assignee: response.task.assignee,
      due: response.task.due ?? '',
      due_time: response.task.due_time ?? '',
      proj: response.task.proj,
    }
    setAssistantOpen(false)
    setModal({
      key: Date.now(),
      editing: null,
      prefill,
      recommendation: response.recommendation,
      conflict: response.conflict,
    })
  }

  async function handleSave(
    data: TaskInput,
    id: string | null,
    opts: { addToOutlook?: boolean } = {},
  ) {
    try {
      const payload: TaskInput = {
        ...data,
        due: data.due ? data.due : null,
        due_time: data.due_time ? data.due_time : null,
      }
      if (id) {
        const updated = await api.updateTask(id, payload)
        setTasks((prev) => prev.map((t) => (t.id === id ? updated : t)))
        showToast('Task updated!')
      } else {
        // The login flow already requested Calendars.ReadWrite, so the cached
        // token has write access. No additional consent popup needed.
        const token =
          opts.addToOutlook && ms.isSignedIn ? await ms.getToken() : null
        const created = await api.createTask(payload, {
          addToOutlook: opts.addToOutlook,
          token,
        })
        setTasks((prev) => [...prev, created])
        if (opts.addToOutlook) {
          showToast(
            created.outlook_event_id
              ? 'Task added & sent to Outlook!'
              : 'Task added (Outlook sync failed \u2014 see backend logs)',
            created.outlook_event_id ? 'success' : 'error',
          )
        } else {
          showToast('Task added!')
        }
      }
      setModal(null)
    } catch (err) {
      console.error(err)
      showToast('Failed to save task', 'error')
    }
  }

  async function handleToggle(task: Task) {
    const nextStatus = task.status === 'done' ? 'todo' : 'done'
    try {
      const updated = await api.updateTask(task.id, { status: nextStatus })
      setTasks((prev) => prev.map((t) => (t.id === task.id ? updated : t)))
      showToast(nextStatus === 'done' ? 'Task completed! ✓' : 'Task reopened')
    } catch (err) {
      console.error(err)
      showToast('Failed to update task', 'error')
    }
  }

  async function handleDelete(task: Task) {
    try {
      await api.deleteTask(task.id)
      setTasks((prev) => prev.filter((t) => t.id !== task.id))
      showToast('Task deleted')
    } catch (err) {
      console.error(err)
      showToast('Failed to delete task', 'error')
    }
  }

  function handleSearchChange(value: string) {
    setSearch(value)
    if (view === 'dashboard' && value.trim()) setView('all')
  }

  function handleExport() {
    exportTasksToCsv(tasks)
    showToast('Exported as CSV!')
  }

  return (
    <div className="app">
      <Sidebar view={view} tasks={tasks} projects={projects} onSelect={selectView} />
      <div className="main">
        <Topbar
          ref={searchRef}
          title={title}
          search={search}
          onSearchChange={handleSearchChange}
          onExport={handleExport}
          onNewTask={openCreate}
          onOpenAssistant={() => setAssistantOpen(true)}
          ms={ms}
        />
        <div className="content">
          {loading ? (
            <div className="loading">Loading…</div>
          ) : view === 'dashboard' ? (
            <Dashboard tasks={tasks} onToggle={handleToggle} onEdit={openEdit} onDelete={handleDelete} />
          ) : (
            <TaskTable
              tasks={filteredTasks}
              totalCount={tasks.length}
              showFilters
              filter={filter}
              onFilterChange={setFilter}
              onSortChange={setSort}
              onToggle={handleToggle}
              onEdit={openEdit}
              onDelete={handleDelete}
            />
          )}
        </div>
      </div>
      {modal && (
        <TaskModal
          key={modal.key}
          initial={modal.editing}
          prefill={modal.prefill}
          recommendation={modal.recommendation}
          conflict={modal.conflict}
          projects={projects}
          users={users}
          msSignedIn={ms.isSignedIn}
          onClose={() => setModal(null)}
          onSave={handleSave}
        />
      )}
      {assistantOpen && (
        <AssistantPanel
          onClose={() => setAssistantOpen(false)}
          onSuggestion={handleAssistantSuggestion}
          onError={(message) => showToast(message, 'error')}
          onSubmit={handleAssistantSubmit}
          msSignedIn={ms.isSignedIn}
        />
      )}
      <Toast message={toast?.message ?? null} variant={toast?.variant} />
    </div>
  )
}

export default App
