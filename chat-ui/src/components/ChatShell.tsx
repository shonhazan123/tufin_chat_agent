import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../types'
import { MessageList } from './MessageList'
import { Composer } from './Composer'
import { ReasoningSidebar } from './ReasoningSidebar'

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

type HealthStatus = 'unknown' | 'ok' | 'degraded' | 'offline'

const POLL_INTERVAL = 10_000

export function ChatShell() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [pending, setPending] = useState(false)
  const [debugTaskId, setDebugTaskId] = useState<string | null>(null)
  const [health, setHealth] = useState<HealthStatus>('unknown')
  const [agentReady, setAgentReady] = useState<boolean | null>(null)
  const [provider, setProvider] = useState<string | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval>>(null)

  useEffect(() => {
    const base = apiBase()
    const check = async () => {
      try {
        const res = await fetch(`${base}/api/v1/health`)
        if (!res.ok) { setHealth('offline'); setAgentReady(false); setProvider(null); return }
        const data = (await res.json()) as { status?: string; agent?: string; provider?: string }
        setHealth(data.status === 'ok' ? 'ok' : 'degraded')
        setAgentReady(data.agent === 'ok')
        setProvider(data.provider ?? null)
      } catch {
        setHealth('offline')
        setAgentReady(false)
        setProvider(null)
      }
    }
    void check()
    timerRef.current = setInterval(check, POLL_INTERVAL)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [])

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
          total_cached_tokens?: number | null
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
                  totalCachedTokens: data.total_cached_tokens,
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
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setDebugTaskId('')}
              title="Open reasoning debugger"
              className="rounded-md border border-[#3f3f46] bg-[#1c1c1f] p-1.5 text-[#a1a1aa] transition-colors hover:border-[#7c3aed]/40 hover:bg-[#7c3aed]/10 hover:text-[#a78bfa]"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="8" />
                <path d="m21 21-4.3-4.3" />
              </svg>
            </button>
            <span
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                health === 'ok' && agentReady
                  ? 'border-[#059669]/40 bg-[#059669]/10 text-[#86efac]'
                  : health === 'offline' || agentReady === false
                    ? 'border-[#dc2626]/40 bg-[#dc2626]/10 text-[#fca5a5]'
                    : health === 'degraded'
                      ? 'border-[#d97706]/40 bg-[#d97706]/10 text-[#fcd34d]'
                      : 'border-[#3f3f46] bg-[#1c1c1f] text-[#71717a]'
              }`}
              title={`${base} — status: ${health}, agent: ${agentReady ? 'ready' : 'not ready'}${provider ? `, provider: ${provider}` : ''}`}
            >
              <span className={`inline-block h-2 w-2 rounded-full ${
                health === 'ok' && agentReady
                  ? 'bg-[#34d399] shadow-[0_0_6px_#34d399]'
                  : health === 'offline' || agentReady === false
                    ? 'bg-[#f87171] shadow-[0_0_6px_#f87171]'
                    : health === 'degraded'
                      ? 'bg-[#fbbf24] shadow-[0_0_6px_#fbbf24]'
                      : 'bg-[#71717a]'
              }`} />
              {health === 'ok' && agentReady
                ? `Active · ${provider === 'ollama' ? 'Ollama' : 'OpenAI'}`
                : health === 'offline'
                  ? 'Offline'
                  : agentReady === false
                    ? 'Agent Not Ready'
                    : health === 'degraded'
                      ? 'Degraded'
                      : 'Checking...'}
            </span>
          </div>
        </div>
      </header>

      <MessageList messages={messages} onDebug={(id) => setDebugTaskId(id)} />

      <Composer onSend={send} disabled={pending} />

      {debugTaskId !== null && (
        <ReasoningSidebar
          taskId={debugTaskId || null}
          apiBase={base}
          onClose={() => setDebugTaskId(null)}
        />
      )}
    </div>
  )
}
