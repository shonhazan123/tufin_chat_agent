import { useCallback, useState, type KeyboardEvent } from 'react'

type Props = {
  onSend: (text: string) => void
  disabled: boolean
}

export function Composer({ onSend, disabled }: Props) {
  const [value, setValue] = useState('')

  const submit = useCallback(() => {
    const t = value.trimEnd()
    if (!t || disabled) return
    onSend(value)
    setValue('')
  }, [value, disabled, onSend])

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="border-t border-[#3f3f46] bg-[#141414] p-4">
      <div className="mx-auto flex max-w-3xl gap-3">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Message…"
          disabled={disabled}
          rows={1}
          className="min-h-[52px] flex-1 resize-y rounded-xl border border-[#3f3f46] bg-[#1c1c1f] px-4 py-3 text-[0.9375rem] text-[#f4f4f5] placeholder:text-[#71717a] focus:border-[#52525b] focus:outline-none focus:ring-1 focus:ring-[#52525b] disabled:opacity-50"
        />
        <button
          type="button"
          onClick={submit}
          disabled={disabled || value.trim() === ''}
          className="h-[52px] shrink-0 self-end rounded-xl bg-[#3f3f46] px-5 text-sm font-medium text-[#fafafa] transition-colors hover:bg-[#52525b] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {disabled ? (
            <span className="inline-flex items-center gap-2">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-[#a1a1aa] border-t-transparent" />
              Wait
            </span>
          ) : (
            'Send'
          )}
        </button>
      </div>
      <p className="mx-auto mt-2 max-w-3xl text-center text-xs text-[#52525b]">
        Enter to send · Shift+Enter for new line
      </p>
    </div>
  )
}
