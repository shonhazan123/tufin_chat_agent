import { useState } from 'react'
import type { ReasoningStep } from '../types'

type Props = {
  step: ReasoningStep
  depth?: number
}

const NODE_COLORS: Record<string, { dot: string; border: string; bg: string }> = {
  planner:   { dot: 'bg-[#a78bfa]', border: 'border-[#7c3aed]', bg: 'bg-[#7c3aed]/10' },
  tool:      { dot: 'bg-[#34d399]', border: 'border-[#059669]', bg: 'bg-[#059669]/10' },
  responder: { dot: 'bg-[#60a5fa]', border: 'border-[#2563eb]', bg: 'bg-[#2563eb]/10' },
  error:     { dot: 'bg-[#f87171]', border: 'border-[#dc2626]', bg: 'bg-[#dc2626]/10' },
}

const NODE_ICONS: Record<string, string> = {
  planner: '🧠',
  tool: '🔧',
  responder: '💬',
  error: '⚠️',
}

const SECTION_RE = /^\[(.+?)\]$/

function SectionBlock({ text }: { text: string }) {
  const lines = text.split('\n')
  const elements: { key: string; heading: string | null; body: string }[] = []
  let current: { heading: string | null; lines: string[] } = { heading: null, lines: [] }

  for (const line of lines) {
    const m = SECTION_RE.exec(line)
    if (m) {
      if (current.lines.length > 0 || current.heading) {
        elements.push({ key: current.heading ?? `_${elements.length}`, heading: current.heading, body: current.lines.join('\n') })
      }
      current = { heading: m[1], lines: [] }
    } else {
      current.lines.push(line)
    }
  }
  if (current.lines.length > 0 || current.heading) {
    elements.push({ key: current.heading ?? `_${elements.length}`, heading: current.heading, body: current.lines.join('\n') })
  }

  if (elements.length <= 1 && !elements[0]?.heading) {
    return (
      <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded bg-[#0f0f10] p-2.5 font-mono text-[0.75rem] leading-relaxed text-[#d4d4d8]">
        {text}
      </pre>
    )
  }

  return (
    <div className="space-y-1.5">
      {elements.map((el) => (
        <div key={el.key}>
          {el.heading && (
            <span className="mb-0.5 inline-block rounded bg-[#27272a] px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wider text-[#a78bfa]">
              {el.heading}
            </span>
          )}
          <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap rounded bg-[#0f0f10] p-2.5 font-mono text-[0.75rem] leading-relaxed text-[#d4d4d8]">
            {el.body.replace(/^\n/, '')}
          </pre>
        </div>
      ))}
    </div>
  )
}

function TokenBadge({ tokens }: { tokens: { input: number | null; output: number | null } }) {
  return (
    <span className="ml-2 inline-flex items-center gap-1.5 rounded-full bg-[#27272a] px-2 py-0.5 text-[0.6875rem] text-[#a1a1aa]">
      <span className="text-[#86efac]">↓{tokens.input ?? '—'}</span>
      <span className="text-[#71717a]">/</span>
      <span className="text-[#93c5fd]">↑{tokens.output ?? '—'}</span>
    </span>
  )
}

export function ReasoningStepCard({ step, depth = 0 }: Props) {
  const [expanded, setExpanded] = useState(false)
  const hasDetail = step.input_summary || step.output_summary
  const hasChildren = step.children && step.children.length > 0
  const effectiveType = step.status === 'error' ? 'error' : step.node_type
  const colors = NODE_COLORS[effectiveType] || NODE_COLORS.tool
  const icon = NODE_ICONS[step.node_type] || '•'

  return (
    <div className={depth > 0 ? 'ml-5 border-l-2 border-[#3f3f46] pl-4' : ''}>
      <div className={`group rounded-lg border ${colors.border} ${colors.bg} transition-colors`}>
        {/* Header row */}
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm"
          disabled={!hasDetail && !hasChildren}
        >
          <span className="text-base leading-none">{icon}</span>
          <span className={`h-2 w-2 shrink-0 rounded-full ${colors.dot}`} />
          <span className="font-medium text-[#e4e4e7]">{step.label}</span>

          {step.status === 'error' && (
            <span className="rounded bg-[#dc2626]/20 px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase tracking-wider text-[#fca5a5]">
              error
            </span>
          )}

          {step.tokens && <TokenBadge tokens={step.tokens} />}

          {(hasDetail || hasChildren) && (
            <span className={`ml-auto text-xs text-[#71717a] transition-transform ${expanded ? 'rotate-90' : ''}`}>
              ▶
            </span>
          )}
        </button>

        {/* Expanded detail */}
        {expanded && (
          <div className="space-y-3 border-t border-[#3f3f46]/50 px-3 py-2.5 text-xs text-[#a1a1aa]">
            {step.input_summary && (
              <div>
                <span className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-wider text-[#71717a]">
                  Input
                </span>
                <SectionBlock text={step.input_summary} />
              </div>
            )}
            {step.output_summary && (
              <div>
                <span className="mb-1 block text-[0.6875rem] font-semibold uppercase tracking-wider text-[#71717a]">
                  Output
                </span>
                <SectionBlock text={step.output_summary} />
              </div>
            )}
            {step.tokens && (
              <div className="flex gap-4 pt-1 text-[0.6875rem]">
                <span>
                  <span className="text-[#71717a]">In:</span>{' '}
                  <span className="text-[#86efac]">{step.tokens.input ?? '—'}</span>
                </span>
                <span>
                  <span className="text-[#71717a]">Out:</span>{' '}
                  <span className="text-[#93c5fd]">{step.tokens.output ?? '—'}</span>
                </span>
                {step.duration_ms != null && (
                  <span>
                    <span className="text-[#71717a]">Time:</span>{' '}
                    <span className="text-[#fbbf24]">{step.duration_ms} ms</span>
                  </span>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Render children (tools inside a wave) */}
      {expanded && hasChildren && (
        <div className="mt-1.5 space-y-1.5">
          {step.children!.map((child) => (
            <ReasoningStepCard key={child.id} step={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  )
}
