import { useEffect, useRef, useState } from 'react'
import { apiBase } from '../lib/api'

export type ModelPhase =
  | 'not_started'
  | 'downloading'
  | 'warming_up'
  | 'ready'
  | 'error'
  | 'skipped'

interface StatusPayload {
  status: ModelPhase
  detail: string
}

const POLL_MS = 3_000
const READY_DISMISS_MS = 4_000

const PHASE_CONFIG: Record<
  ModelPhase,
  { bg: string; border: string; text: string; dot: string; label: string; pulse: boolean }
> = {
  not_started: {
    bg: 'bg-[#3f3f46]/10',
    border: 'border-[#3f3f46]/40',
    text: 'text-[#a1a1aa]',
    dot: 'bg-[#71717a]',
    label: 'Initializing…',
    pulse: false,
  },
  downloading: {
    bg: 'bg-[#6366f1]/10',
    border: 'border-[#6366f1]/40',
    text: 'text-[#a5b4fc]',
    dot: 'bg-[#818cf8] shadow-[0_0_10px_#818cf8]',
    label: 'Downloading model…',
    pulse: true,
  },
  warming_up: {
    bg: 'bg-[#d97706]/10',
    border: 'border-[#d97706]/40',
    text: 'text-[#fcd34d]',
    dot: 'bg-[#fbbf24] shadow-[0_0_10px_#fbbf24]',
    label: 'Warming up model…',
    pulse: true,
  },
  ready: {
    bg: 'bg-[#059669]/10',
    border: 'border-[#059669]/40',
    text: 'text-[#86efac]',
    dot: 'bg-[#34d399] shadow-[0_0_10px_#34d399]',
    label: 'Model ready',
    pulse: false,
  },
  error: {
    bg: 'bg-[#dc2626]/10',
    border: 'border-[#dc2626]/40',
    text: 'text-[#fca5a5]',
    dot: 'bg-[#f87171] shadow-[0_0_10px_#f87171]',
    label: 'Model failed to load',
    pulse: false,
  },
  skipped: {
    bg: '',
    border: '',
    text: '',
    dot: '',
    label: '',
    pulse: false,
  },
}

interface Props {
  provider: string | null
  onStatusChange?: (phase: ModelPhase) => void
}

export function ModelStatusBanner({ provider, onStatusChange }: Props) {
  const [phase, setPhase] = useState<ModelPhase>('not_started')
  const [detail, setDetail] = useState('')
  const [visible, setVisible] = useState(true)
  const timerRef = useRef<ReturnType<typeof setInterval>>(null)
  const dismissRef = useRef<ReturnType<typeof setTimeout>>(null)

  useEffect(() => {
    if (provider !== 'ollama') {
      setVisible(false)
      onStatusChange?.('skipped')
      return
    }

    setVisible(true)
    const base = apiBase()

    const poll = async () => {
      try {
        const res = await fetch(`${base}/api/v1/health/model`)
        if (!res.ok) return
        const data = (await res.json()) as StatusPayload
        setPhase(data.status)
        setDetail(data.detail)
        onStatusChange?.(data.status)

        if (data.status === 'ready') {
          if (timerRef.current) clearInterval(timerRef.current)
          timerRef.current = null
          dismissRef.current = setTimeout(() => setVisible(false), READY_DISMISS_MS)
        }
        if (data.status === 'skipped') {
          if (timerRef.current) clearInterval(timerRef.current)
          timerRef.current = null
          setVisible(false)
        }
      } catch { /* API not up yet — keep polling */ }
    }

    void poll()
    timerRef.current = setInterval(poll, POLL_MS)

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      if (dismissRef.current) clearTimeout(dismissRef.current)
    }
  }, [provider, onStatusChange])

  if (!visible || phase === 'skipped') return null

  const cfg = PHASE_CONFIG[phase]

  return (
    <div
      className={`
        shrink-0 border-b px-4 py-3.5 transition-all duration-500
        ${cfg.border} ${cfg.bg}
      `}
    >
      <div className={`mx-auto flex max-w-3xl items-center justify-center gap-3 text-sm font-medium ${cfg.text}`}>
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${cfg.dot} ${cfg.pulse ? 'animate-pulse' : ''}`}
        />

        {cfg.pulse && <Spinner className={cfg.text} />}

        <span>{cfg.label}</span>

        {detail && phase !== 'ready' && (
          <span className="opacity-50">— {detail}</span>
        )}
      </div>
    </div>
  )
}

function Spinner({ className }: { className: string }) {
  return (
    <svg
      className={`h-4 w-4 animate-spin ${className}`}
      viewBox="0 0 24 24"
      fill="none"
    >
      <circle
        className="opacity-25"
        cx="12" cy="12" r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  )
}
