import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'

const mdComponents: Components = {
  h1: ({ children }) => (
    <h1 className="mb-3 mt-4 text-xl font-medium text-[#fafafa] first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-2 mt-4 text-lg font-medium text-[#f4f4f5] first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-2 mt-3 text-base font-medium text-[#e4e4e7]">
      {children}
    </h3>
  ),
  p: ({ children }) => (
    <p className="mb-3 text-[0.9375rem] leading-relaxed text-[#d4d4d8] last:mb-0">
      {children}
    </p>
  ),
  ul: ({ children }) => (
    <ul className="mb-3 list-disc space-y-1 pl-5 text-[#d4d4d8] last:mb-0">
      {children}
    </ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-3 list-decimal space-y-1 pl-5 text-[#d4d4d8] last:mb-0">
      {children}
    </ol>
  ),
  li: ({ children }) => <li className="leading-relaxed">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-3 border-l-2 border-[#52525b] pl-4 text-[#a1a1aa]">
      {children}
    </blockquote>
  ),
  a: ({ href, children }) => (
    <a
      href={href}
      className="text-[#a78bfa] underline decoration-[#a78bfa]/40 underline-offset-2 hover:text-[#c4b5fd]"
      target="_blank"
      rel="noreferrer noopener"
    >
      {children}
    </a>
  ),
  strong: ({ children }) => (
    <strong className="font-semibold text-[#f4f4f5]">{children}</strong>
  ),
  code: ({ className, children }) => {
    const inline = !className
    if (inline) {
      return (
        <code className="rounded bg-[#27272a] px-1.5 py-0.5 font-mono text-[0.85em] text-[#e4e4e7]">
          {children}
        </code>
      )
    }
    return (
      <code className="font-mono text-[0.875rem] text-[#e4e4e7]">{children}</code>
    )
  },
  pre: ({ children }) => (
    <pre className="my-3 overflow-x-auto rounded-lg border border-[#3f3f46] bg-[#18181b] p-4">
      {children}
    </pre>
  ),
  hr: () => <hr className="my-6 border-[#3f3f46]" />,
}

type Props = {
  content: string
}

export function MarkdownBlock({ content }: Props) {
  return (
    <div className="min-w-0 break-words">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
