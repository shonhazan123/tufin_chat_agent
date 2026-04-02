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

// ---------------------------------------------------------------------------
// Debug / reasoning tree types (mirrors backend TaskDebugResponse)
// ---------------------------------------------------------------------------

export type ReasoningStep = {
  id: string
  label: string
  node_type: 'planner' | 'tool' | 'responder' | 'error'
  status: 'ok' | 'error'
  model?: string | null
  duration_ms?: number | null
  tokens?: { input: number | null; output: number | null } | null
  input_summary?: string | null
  output_summary?: string | null
  wave?: number | null
  children?: ReasoningStep[]
}

export type TaskDebugData = {
  task_id: string
  task_text: string
  status: string
  final_answer: string
  error_message?: string | null
  created_at: string
  completed_at?: string | null
  latency_ms?: number | null
  total_input_tokens?: number | null
  total_output_tokens?: number | null
  reasoning_tree: ReasoningStep[]
}
