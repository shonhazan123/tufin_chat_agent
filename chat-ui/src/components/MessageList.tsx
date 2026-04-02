import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../types'
import { MarkdownBlock } from './MarkdownBlock'
import { ThinkingIndicator } from './ThinkingIndicator'
import { TracePanel } from './TracePanel'

type Props = {
  messages: ChatMessage[]
  onDebug?: (taskId: string) => void
}

export function MessageList({ messages, onDebug }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-4 py-6 sm:px-6">
      {messages.length === 0 && (
        <p className="text-center text-sm text-[#71717a]">
          Start a conversation. Messages stay in this session only (demo mode).
        </p>
      )}
      {messages.map((m) =>
        m.role === 'user' ? (
          <div key={m.id} className="flex justify-end">
            <div className="max-w-[min(100%,36rem)] rounded-2xl rounded-br-md bg-[#27272a] px-4 py-3 text-[0.9375rem] leading-relaxed text-[#f4f4f5] shadow-sm">
              {m.content}
            </div>
          </div>
        ) : (
          <div key={m.id} className="flex justify-start">
            <div className="max-w-[min(100%,40rem)]">
              <div className="rounded-2xl rounded-bl-md border border-[#3f3f46] bg-[#18181b] px-4 py-3 shadow-sm">
                {m.status === 'pending' ? (
                  <ThinkingIndicator />
                ) : m.status === 'error' ? (
                  <MarkdownBlock content={m.content} />
                ) : (
                  <>
                    <MarkdownBlock content={m.content} />
                    <TracePanel
                      taskId={m.taskId}
                      latencyMs={m.latencyMs}
                      totalInputTokens={m.totalInputTokens}
                      totalOutputTokens={m.totalOutputTokens}
                      onDebug={onDebug}
                    />
                  </>
                )}
              </div>
            </div>
          </div>
        ),
      )}
      <div ref={bottomRef} />
    </div>
  )
}
