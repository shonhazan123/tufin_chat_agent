type Props = {
  taskId?: string
  latencyMs?: number | null
  totalInputTokens?: number | null
  totalOutputTokens?: number | null
}

function fmtNum(n: number | null | undefined): string {
  if (n == null) return '—'
  return String(n)
}

export function TracePanel({
  taskId,
  latencyMs,
  totalInputTokens,
  totalOutputTokens,
}: Props) {
  return (
    <details className="group mt-4 rounded-lg border border-[#3f3f46] bg-[#1c1c1f]">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm text-[#a1a1aa] transition-colors hover:bg-[#27272a] hover:text-[#d4d4d8]">
        <span className="font-medium text-[#a78bfa]">Observability</span>
        <span className="ml-2 text-xs text-[#71717a]">(latency &amp; tokens)</span>
      </summary>
      <div className="space-y-1.5 border-t border-[#3f3f46] p-3 text-xs leading-relaxed text-[#a1a1aa]">
        {taskId != null && taskId !== '' && (
          <p>
            <span className="text-[#71717a]">Task ID</span>{' '}
            <code className="rounded bg-[#27272a] px-1.5 py-0.5 text-[#d4d4d8]">
              {taskId}
            </code>
          </p>
        )}
        <p>
          <span className="text-[#71717a]">Latency</span>{' '}
          {latencyMs != null ? `${latencyMs} ms` : '—'}
        </p>
        <p>
          <span className="text-[#71717a]">Tokens (in / out)</span>{' '}
          {fmtNum(totalInputTokens)} / {fmtNum(totalOutputTokens)}
        </p>
      </div>
    </details>
  )
}
