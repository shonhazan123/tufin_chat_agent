import { useCallback, useState } from 'react'
import type { ChatMessage } from '../types'
import { MessageList } from './MessageList'
import { Composer } from './Composer'

function newId() {
  return crypto.randomUUID()
}

function apiBase(): string {
  const raw = import.meta.env.VITE_API_BASE_URL
  return (typeof raw === 'string' && raw.length > 0
    ? raw
    : 'http://127.0.0.1:8000'
  ).replace(/\/$/, '')
}

export function ChatShell() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState(false)

  const send = useCallback((raw: string) => {
    const text = raw.trimEnd()
    if (text === '' || pending) return

    const userId = newId()
    const assistantId = newId()

    setMessages((m) => [
      ...m,
      { id: userId, role: 'user', content: text },
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        status: 'pending',
      },
    ])
    setPending(true)

    const run = async () => {
      const key = import.meta.env.VITE_API_KEY
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      }
      if (typeof key === 'string' && key.length > 0) {
        headers['X-API-Key'] = key
      }
      try {
        const res = await fetch(`${apiBase()}/api/v1/task`, {
          method: 'POST',
          headers,
          body: JSON.stringify({ task: text }),
        })
        const data = (await res.json()) as {
          task_id?: string
          final_answer?: string
          latency_ms?: number | null
          total_input_tokens?: number | null
          total_output_tokens?: number | null
          error?: { message?: string }
        }
        if (!res.ok) {
          const msg =
            data.error?.message ??
            (typeof data === 'object' && data !== null && 'detail' in data
              ? String((data as { detail?: unknown }).detail)
              : res.statusText)
          throw new Error(msg || `HTTP ${res.status}`)
        }
        const body = data.final_answer ?? ''
        const taskId = data.task_id
        setMessages((m) =>
          m.map((msg) =>
            msg.id === assistantId && msg.role === 'assistant'
              ? {
                  ...msg,
                  content: body,
                  status: 'done' as const,
                  taskId,
                  latencyMs: data.latency_ms,
                  totalInputTokens: data.total_input_tokens,
                  totalOutputTokens: data.total_output_tokens,
                }
              : msg,
          ),
        )
      } catch (e) {
        const err = e instanceof Error ? e.message : String(e)
        setMessages((m) =>
          m.map((msg) =>
            msg.id === assistantId && msg.role === 'assistant'
              ? {
                  ...msg,
                  content: `**Error:** ${err}`,
                  status: 'error' as const,
                }
              : msg,
          ),
        )
      } finally {
        setPending(false)
      }
    }

    void run()
  }, [pending])

  const base = apiBase()

  return (
    <div className="flex h-[100dvh] flex-col bg-[#0f0f10] text-[#fafafa]">
      <header className="shrink-0 border-b border-[#27272a] bg-[#141414] px-4 py-3 sm:px-6">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4">
          <h1 className="text-lg font-medium tracking-tight text-[#fafafa]">
            Tufin Agent
          </h1>
          <span
            className="max-w-[14rem] truncate rounded-full border border-[#3f3f46] bg-[#1c1c1f] px-2.5 py-1 text-xs font-medium text-[#86efac]"
            title={base}
          >
            API · {base}
          </span>
        </div>
      </header>

      <MessageList messages={messages} />

      <Composer onSend={send} disabled={pending} />
    </div>
  )
}
