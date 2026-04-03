import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../types'
import { apiBase } from '../lib/api'
import { MessageList } from './MessageList'
import { Composer } from './Composer'
import { ModelStatusBanner } from './ModelStatusBanner'
import type { ModelPhase } from './ModelStatusBanner'
import { ReasoningSidebar } from './ReasoningSidebar'

function newId() {
  return crypto.randomUUID()
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
  const [modelPhase, setModelPhase] = useState<ModelPhase>('not_started')
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
          <div className="flex flex-shrink-0 items-center gap-3">
            <button
              type="button"
              onClick={() => setDebugTaskId('')}
              title="Inspect agent reasoning traces. Use a task ID from any reply."
              className="group flex items-center gap-2 rounded-lg bg-[#7c3aed] px-4 py-2 text-[0.8125rem] font-semibold uppercase tracking-wide text-white shadow-md shadow-[#7c3aed]/20 transition-all hover:bg-[#6d28d9] hover:shadow-lg hover:shadow-[#7c3aed]/30 active:scale-[0.97]"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-80 transition-transform group-hover:scale-110">
                <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
              Agent Logic
            </button>
            {(() => {
              const modelReady = provider !== 'ollama' || modelPhase === 'ready' || modelPhase === 'skipped'
              const fullyActive = health === 'ok' && agentReady && modelReady

              const ollamaLoading = provider === 'ollama'
                && (modelPhase === 'downloading' || modelPhase === 'warming_up' || modelPhase === 'not_started')

              let pillBorder: string, pillBg: string, pillText: string
              let dotColor: string
              let label: string

              if (health === 'offline') {
                pillBorder = 'border-[#dc2626]/40'; pillBg = 'bg-[#dc2626]/10'; pillText = 'text-[#fca5a5]'
                dotColor = 'bg-[#f87171] shadow-[0_0_6px_#f87171]'
                label = 'Offline'
              } else if (agentReady === false) {
                pillBorder = 'border-[#dc2626]/40'; pillBg = 'bg-[#dc2626]/10'; pillText = 'text-[#fca5a5]'
                dotColor = 'bg-[#f87171] shadow-[0_0_6px_#f87171]'
                label = 'Agent Not Ready'
              } else if (modelPhase === 'error') {
                pillBorder = 'border-[#dc2626]/40'; pillBg = 'bg-[#dc2626]/10'; pillText = 'text-[#fca5a5]'
                dotColor = 'bg-[#f87171] shadow-[0_0_6px_#f87171]'
                label = 'Model Error'
              } else if (ollamaLoading) {
                pillBorder = 'border-[#6366f1]/40'; pillBg = 'bg-[#6366f1]/10'; pillText = 'text-[#a5b4fc]'
                dotColor = 'bg-[#818cf8] animate-pulse shadow-[0_0_6px_#818cf8]'
                label = modelPhase === 'downloading' ? 'Downloading · Ollama'
                  : modelPhase === 'warming_up' ? 'Warming Up · Ollama'
                  : 'Loading · Ollama'
              } else if (fullyActive) {
                pillBorder = 'border-[#059669]/40'; pillBg = 'bg-[#059669]/10'; pillText = 'text-[#86efac]'
                dotColor = 'bg-[#34d399] shadow-[0_0_6px_#34d399]'
                label = `Active · ${provider === 'ollama' ? 'Ollama' : 'OpenAI'}`
              } else if (health === 'degraded') {
                pillBorder = 'border-[#d97706]/40'; pillBg = 'bg-[#d97706]/10'; pillText = 'text-[#fcd34d]'
                dotColor = 'bg-[#fbbf24] shadow-[0_0_6px_#fbbf24]'
                label = 'Degraded'
              } else {
                pillBorder = 'border-[#3f3f46]'; pillBg = 'bg-[#1c1c1f]'; pillText = 'text-[#71717a]'
                dotColor = 'bg-[#71717a]'
                label = 'Checking…'
              }

              return (
                <span
                  className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${pillBorder} ${pillBg} ${pillText}`}
                  title={`${base} — status: ${health}, agent: ${agentReady ? 'ready' : 'not ready'}, model: ${modelPhase}${provider ? `, provider: ${provider}` : ''}`}
                >
                  <span className={`inline-block h-2 w-2 rounded-full ${dotColor}`} />
                  {label}
                </span>
              )
            })()}
          </div>
        </div>
      </header>

      <ModelStatusBanner provider={provider} onStatusChange={setModelPhase} />

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
