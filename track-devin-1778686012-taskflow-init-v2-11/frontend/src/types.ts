export type Status = 'todo' | 'inprog' | 'done'
export type Priority = 'high' | 'medium' | 'low'
export type Tag = 'dev' | 'design' | 'qa' | 'pm'

export interface Task {
  id: number
  title: string
  desc: string
  status: Status
  priority: Priority
  tag: Tag
  assignee: string
  due: string | null
  due_time: string | null
  proj: string
  created_at: string
  updated_at: string
  /**
   * Set only on the response of POST /api/tasks?add_to_outlook=true if
   * Graph successfully created the Outlook event. Used by the toast in
   * App.tsx to confirm the calendar sync.
   */
  outlook_event_id?: string | null
}

export type TaskInput = Omit<
  Task,
  'id' | 'created_at' | 'updated_at' | 'outlook_event_id'
>

export interface Project {
  name: string
  slug: string
  color: string
}

export interface User {
  code: string
  name: string
  color: string
}

export type View =
  | 'dashboard'
  | 'mytasks'
  | 'all'
  | 'overdue'
  | 'proj-website'
  | 'proj-backend'
  | 'proj-mobile'
  | 'proj-ops'

export type Filter = 'all' | 'todo' | 'inprog' | 'done' | 'high'
export type SortKey = '' | 'due' | 'priority' | 'status'

export type AssistantLanguage = 'ru-RU' | 'en-US'

export interface AssistantTaskSuggestion {
  title: string
  desc: string
  status: Status
  priority: Priority
  tag: Tag
  assignee: string
  due: string | null
  due_time: string | null
  proj: string
}

export interface AssistantConflictTask {
  id: string
  title: string
  due: string
  due_time: string
  source: 'taskflow' | 'outlook'
}

export interface AssistantAlternative {
  due: string
  due_time: string
}

export interface AssistantConflict {
  conflicts: AssistantConflictTask[]
  alternatives: AssistantAlternative[]
}

export interface AssistantResponse {
  recommendation: string
  task: AssistantTaskSuggestion
  conflict: AssistantConflict | null
}
