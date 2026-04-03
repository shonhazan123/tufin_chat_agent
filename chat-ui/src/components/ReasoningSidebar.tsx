import { useCallback, useEffect, useRef, useState } from 'react'
import type { TaskDebugData } from '../types'
import { ReasoningStepCard } from './ReasoningStepCard'

type Props = {
  taskId: string | null
  apiBase: string
  onClose: () => void
}

const STATUS_BADGE: Record<string, { bg: string; text: string }> = {
  completed: { bg: 'bg-[#059669]/20', text: 'text-[#86efac]' },
  cached:    { bg: 'bg-[#2563eb]/20', text: 'text-[#93c5fd]' },
  failed:    { bg: 'bg-[#dc2626]/20', text: 'text-[#fca5a5]' },
  running:   { bg: 'bg-[#d97706]/20', text: 'text-[#fcd34d]' },
  pending:   { bg: 'bg-[#71717a]/20', text: 'text-[#d4d4d8]' },
}

function fmt(n: number | null | undefined): string {
  return n != null ? String(n) : '—'
}

export function ReasoningSidebar({ taskId: initialTaskId, apiBase, onClose }: Props) {
  const [inputId, setInputId] = useState(initialTaskId ?? '')
  const [data, setData] = useState<TaskDebugData | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const fetchDebug = useCallback(
    async (id: string) => {
      const trimmed = id.trim()
      if (!trimmed) return
      setLoading(true)
      setError(null)
      setData(null)
      try {
        const key = import.meta.env.VITE_API_KEY
        const headers: Record<string, string> = {}
        if (typeof key === 'string' && key.length > 0) {
          headers['X-API-Key'] = key
        }
        const res = await fetch(`${apiBase}/api/v1/tasks/${trimmed}/debug`, { headers })
        if (!res.ok) {
          const body = await res.json().catch(() => null)
          throw new Error(
            (body as { detail?: string })?.detail ?? `HTTP ${res.status}`,
          )
        }
        setData((await res.json()) as TaskDebugData)
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e))
      } finally {
        setLoading(false)
      }
    },
    [apiBase],
  )

  useEffect(() => {
    if (initialTaskId) {
      setInputId(initialTaskId)
      void fetchDebug(initialTaskId)
    }
  }, [initialTaskId, fetchDebug])

  const badge = data ? STATUS_BADGE[data.status] ?? STATUS_BADGE.pending : null

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/40 backdrop-blur-sm transition-opacity"
        onClick={onClose}
      />

      {/* Panel */}
      <div
        ref={panelRef}
        className="fixed inset-y-0 right-0 z-50 flex w-full max-w-lg flex-col border-l border-[#3f3f46] bg-[#141414] shadow-2xl transition-transform duration-300 sm:max-w-xl"
      >
        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-[#3f3f46] px-4 py-3">
          <h2 className="text-sm font-semibold tracking-tight text-[#fafafa]">
            Agent Reasoning
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[#71717a] transition-colors hover:bg-[#27272a] hover:text-[#fafafa]"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M18 6 6 18" />
              <path d="m6 6 12 12" />
            </svg>
          </button>
        </div>

        {/* Task ID input */}
        <div className="shrink-0 border-b border-[#3f3f46] px-4 py-3">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              void fetchDebug(inputId)
            }}
            className="flex gap-2"
          >
            <input
              type="text"
              value={inputId}
              onChange={(e) => setInputId(e.target.value)}
              placeholder="Paste a task ID..."
              className="min-w-0 flex-1 rounded-md border border-[#3f3f46] bg-[#1c1c1f] px-3 py-1.5 text-sm text-[#fafafa] placeholder-[#71717a] outline-none transition-colors focus:border-[#a78bfa]"
            />
            <button
              type="submit"
              disabled={loading || inputId.trim() === ''}
              className="rounded-md bg-[#7c3aed] px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-[#6d28d9] disabled:opacity-40"
            >
              {loading ? 'Loading...' : 'Lookup'}
            </button>
          </form>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 py-4">
          {error && (
            <div className="rounded-lg border border-[#dc2626]/40 bg-[#dc2626]/10 px-3 py-2 text-sm text-[#fca5a5]">
              {error}
            </div>
          )}

          {loading && !data && (
            <div className="flex flex-1 items-center justify-center">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-[#3f3f46] border-t-[#a78bfa]" />
            </div>
          )}

          {!data && !loading && !error && (
            <p className="text-center text-sm leading-relaxed text-[#71717a]">
              Enter a task ID above to view the agent&apos;s reasoning flow. Copy the ID from
              an assistant message&apos;s Observability block—same ID is used on the server for traces
              and debugging (observability).
            </p>
          )}

          {data && (
            <>
              {/* Task summary header */}
              <div className="mb-4 space-y-2 rounded-lg border border-[#3f3f46] bg-[#1c1c1f] p-3">
                <div className="flex items-start justify-between gap-2">
                  <p className="text-sm font-medium text-[#e4e4e7]">{data.task_text}</p>
                  {badge && (
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wider ${badge.bg} ${badge.text}`}>
                      {data.status}
                    </span>
                  )}
                </div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#a1a1aa]">
                  <span>
                    <span className="text-[#71717a]">Latency</span>{' '}
                    {data.latency_ms != null ? `${data.latency_ms} ms` : '—'}
                  </span>
                  <span>
                    <span className="text-[#71717a]">Tokens</span>{' '}
                    {fmt(data.total_cached_tokens)} cached / {fmt(data.total_input_tokens)} in / {fmt(data.total_output_tokens)} out
                  </span>
                  <span>
                    <span className="text-[#71717a]">Created</span>{' '}
                    {new Date(data.created_at).toLocaleString()}
                  </span>
                  {data.completed_at && (
                    <span>
                      <span className="text-[#71717a]">Completed</span>{' '}
                      {new Date(data.completed_at).toLocaleString()}
                    </span>
                  )}
                </div>
                {data.error_message && (
                  <p className="mt-1 text-xs text-[#fca5a5]">{data.error_message}</p>
                )}
              </div>

              {/* Reasoning tree */}
              <div className="space-y-2">
                {data.reasoning_tree.map((step) => (
                  <ReasoningStepCard key={step.id} step={step} />
                ))}
              </div>

              {/* Token usage footer */}
              {(data.total_cached_tokens != null || data.total_input_tokens != null || data.total_output_tokens != null) && (
                <div className="mt-4 rounded-lg border border-[#3f3f46] bg-[#1c1c1f] p-3">
                  <p className="mb-1.5 text-[0.625rem] font-semibold uppercase tracking-wider text-[#71717a]">
                    Total Token Usage
                  </p>
                  <TokenBar
                    cached={data.total_cached_tokens ?? 0}
                    input={data.total_input_tokens ?? 0}
                    output={data.total_output_tokens ?? 0}
                  />
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  )
}

function TokenBar({ cached, input, output }: { cached: number; input: number; output: number }) {
  const total = cached + input + output
  if (total === 0) return <p className="text-xs text-[#71717a]">No token data</p>
  const cachedPct = Math.round((cached / total) * 100)
  const inPct = Math.round((input / total) * 100)
  const outPct = 100 - cachedPct - inPct
  return (
    <div>
      <div className="flex h-2.5 overflow-hidden rounded-full bg-[#27272a]">
        <div className="bg-[#fbbf24] transition-all" style={{ width: `${cachedPct}%` }} />
        <div className="bg-[#86efac] transition-all" style={{ width: `${inPct}%` }} />
        <div className="bg-[#93c5fd] transition-all" style={{ width: `${outPct}%` }} />
      </div>
      <div className="mt-1 flex justify-between text-[0.6875rem] text-[#a1a1aa]">
        <span>
          <span className="inline-block h-2 w-2 rounded-full bg-[#fbbf24]" /> Cached: {cached}
        </span>
        <span>
          <span className="inline-block h-2 w-2 rounded-full bg-[#86efac]" /> Input: {input}
        </span>
        <span>
          <span className="inline-block h-2 w-2 rounded-full bg-[#93c5fd]" /> Output: {output}
        </span>
      </div>
    </div>
  )
}
