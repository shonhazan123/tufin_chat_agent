type Props = {
  taskId?: string
  latencyMs?: number | null
  totalCachedTokens?: number | null
  totalInputTokens?: number | null
  totalOutputTokens?: number | null
  onDebug?: (taskId: string) => void
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return '—'
  return String(n)
}

export function TracePanel({
  taskId,
  latencyMs,
  totalCachedTokens,
  totalInputTokens,
  totalOutputTokens,
  onDebug,
}: Props) {
  return (
    <details className="group mt-4 rounded-lg border border-[#3f3f46] bg-[#1c1c1f]">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm text-[#a1a1aa] transition-colors hover:bg-[#27272a] hover:text-[#d4d4d8]">
        <span className="font-medium text-[#a78bfa]">Observability</span>
        <span className="ml-2 text-xs text-[#71717a]">(latency &amp; tokens)</span>
      </summary>
      <div className="space-y-1.5 border-t border-[#3f3f46] p-3 text-xs leading-relaxed text-[#a1a1aa]">
        {taskId != null && taskId !== '' && (
          <p className="flex items-center gap-2">
            <span className="text-[#71717a]">Task ID</span>{' '}
            <code className="rounded bg-[#27272a] px-1.5 py-0.5 text-[#d4d4d8]">
              {taskId}
            </code>
            {onDebug && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onDebug(taskId)
                }}
                title="Open full agent reasoning traces for this task"
                className="inline-flex items-center gap-1.5 rounded-md bg-[#7c3aed] px-2.5 py-1 text-[0.6875rem] font-semibold uppercase tracking-wide text-white shadow-sm shadow-[#7c3aed]/20 transition-all hover:bg-[#6d28d9] active:scale-[0.97]"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="opacity-80">
                  <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
                Agent Logic
              </button>
            )}
          </p>
        )}
        <p>
          <span className="text-[#71717a]">Latency</span>{' '}
          {latencyMs != null ? `${latencyMs} ms` : '—'}
        </p>
        <p>
          <span className="text-[#71717a]">Tokens (cached / in / out)</span>{' '}
          {fmtNum(totalCachedTokens)} / {fmtNum(totalInputTokens)} / {fmtNum(totalOutputTokens)}
        </p>
      </div>
    </details>
  )
}
