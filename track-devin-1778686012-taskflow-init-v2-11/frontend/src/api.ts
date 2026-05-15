import type { AssistantLanguage, AssistantResponse, Project, Task, TaskInput, User } from './types'

// In dev the Vite proxy points /api to localhost:8000. In production set
// VITE_API_BASE to the public backend URL (e.g. https://taskflow-backend
// .azurecontainerapps.io). Leave empty/undefined for same-origin routing.
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? ''
const BASE = `${API_BASE}/api`

interface RequestOptions extends RequestInit {
  token?: string | null
}

async function request<T>(path: string, init?: RequestOptions): Promise<T> {
  const headers = new Headers(init?.headers)
  headers.set('Content-Type', 'application/json')
  if (init?.token) headers.set('Authorization', `Bearer ${init.token}`)
  const res = await fetch(`${BASE}${path}`, { ...init, headers })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export interface CreateTaskOptions {
  addToOutlook?: boolean
  token?: string | null
}

/**
 * The user's IANA timezone (e.g. "Europe/Moscow"). Used so the backend can
 * give Microsoft Graph a real local time + zone rather than treating the
 * user's input as UTC (which silently shifted events by 3+ hours).
 */
function getBrowserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export const api = {
  listProjects: () => request<Project[]>('/projects'),
  listUsers: () => request<User[]>('/users'),
  listTasks: () => request<Task[]>('/tasks'),
  createTask: (payload: TaskInput, opts: CreateTaskOptions = {}) => {
    const params = new URLSearchParams()
    if (opts.addToOutlook) {
      params.set('add_to_outlook', 'true')
      params.set('tz', getBrowserTimezone())
    }
    const qs = params.toString() ? `?${params.toString()}` : ''
    return request<Task>(`/tasks${qs}`, {
      method: 'POST',
      body: JSON.stringify(payload),
      token: opts.token ?? null,
    })
  },
  updateTask: (id: number, payload: Partial<TaskInput>) =>
    request<Task>(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteTask: (id: number) => request<void>(`/tasks/${id}`, { method: 'DELETE' }),
  askAssistant: (text: string, language: AssistantLanguage, token?: string | null) =>
    request<AssistantResponse>('/assistant', {
      method: 'POST',
      body: JSON.stringify({ text, language, tz: getBrowserTimezone() }),
      token,
    }),
}
