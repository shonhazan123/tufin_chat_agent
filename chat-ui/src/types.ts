export type AssistantMessage = {
  id: string
  role: 'assistant'
  content: string
  status: 'pending' | 'done' | 'error'
  /** Server task id when using POST /api/v1/task */
  taskId?: string
  /** Graph invocation latency (ms) */
  latencyMs?: number | null
  totalInputTokens?: number | null
  totalOutputTokens?: number | null
}

export type UserMessage = {
  id: string
  role: 'user'
  content: string
}

export type ChatMessage = UserMessage | AssistantMessage
