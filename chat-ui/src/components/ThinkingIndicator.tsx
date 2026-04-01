export function ThinkingIndicator() {
  return (
    <div
      className="flex items-center gap-1 py-1"
      aria-live="polite"
      aria-label="Assistant is thinking"
    >
      <span className="sr-only">Thinking</span>
      <span className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="h-2 w-2 animate-bounce rounded-full bg-[#52525b]"
            style={{ animationDelay: `${i * 160}ms`, animationDuration: '0.6s' }}
          />
        ))}
      </span>
      <span className="ml-2 text-sm text-[#a1a1aa]">Thinking…</span>
    </div>
  )
}
