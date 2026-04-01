export type AssistantMessage = {
  id: string
  role: 'assistant'
  content: string
  status: 'pending' | 'done' | 'error'
  trace?: unknown
  /** Server task id when using POST /api/v1/task */
  taskId?: string
}

export type UserMessage = {
  id: string
  role: 'user'
  content: string
}

export type ChatMessage = UserMessage | AssistantMessage
