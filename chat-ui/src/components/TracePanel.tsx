type Props = {
  trace: unknown
}

export function TracePanel({ trace }: Props) {
  const text =
    typeof trace === 'string'
      ? trace
      : JSON.stringify(trace, null, 2)

  return (
    <details className="group mt-4 rounded-lg border border-[#3f3f46] bg-[#1c1c1f]">
      <summary className="cursor-pointer select-none px-3 py-2 text-sm text-[#a1a1aa] transition-colors hover:bg-[#27272a] hover:text-[#d4d4d8]">
        <span className="font-medium text-[#a78bfa]">Observability trace</span>
        <span className="ml-2 text-xs text-[#71717a]">(demo JSON)</span>
      </summary>
      <pre className="max-h-64 overflow-auto border-t border-[#3f3f46] p-3 text-xs leading-relaxed text-[#a1a1aa]">
        {text}
      </pre>
    </details>
  )
}
