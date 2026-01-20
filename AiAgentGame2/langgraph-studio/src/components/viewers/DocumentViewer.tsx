import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

interface DocumentViewerProps {
  content: string
  title?: string
  className?: string
}

export function DocumentViewer({
  content,
  title,
  className
}: DocumentViewerProps): JSX.Element {
  return (
    <div className={cn('document-viewer', className)}>
      {title && (
        <div className="text-nier-h2 font-medium mb-4 pb-2 border-b border-nier-border-light">
          {title}
        </div>
      )}
      <div className="prose prose-nier max-w-none">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h1: ({ children }) => (
              <h1 className="text-nier-h1 font-medium tracking-nier-wide mb-4 mt-6">
                {children}
              </h1>
            ),
            h2: ({ children }) => (
              <h2 className="text-nier-h2 font-medium tracking-nier mb-3 mt-5 border-b border-nier-border-light pb-2">
                {children}
              </h2>
            ),
            h3: ({ children }) => (
              <h3 className="text-nier-body font-medium tracking-nier mb-2 mt-4">
                {children}
              </h3>
            ),
            p: ({ children }) => (
              <p className="text-nier-body text-nier-text-main leading-relaxed mb-3">
                {children}
              </p>
            ),
            ul: ({ children }) => (
              <ul className="list-none space-y-1 mb-4 pl-4">
                {children}
              </ul>
            ),
            ol: ({ children }) => (
              <ol className="list-decimal list-inside space-y-1 mb-4 pl-4">
                {children}
              </ol>
            ),
            li: ({ children }) => (
              <li className="text-nier-body text-nier-text-main flex gap-2">
                <span className="text-nier-text-light">•</span>
                <span>{children}</span>
              </li>
            ),
            code: ({ className, children }) => {
              const isInline = !className
              if (isInline) {
                return (
                  <code className="bg-nier-bg-main px-1.5 py-0.5 text-nier-small font-mono">
                    {children}
                  </code>
                )
              }
              return (
                <code className="block bg-nier-bg-main p-4 text-nier-small font-mono overflow-x-auto">
                  {children}
                </code>
              )
            },
            pre: ({ children }) => (
              <pre className="bg-nier-bg-main border border-nier-border-light p-4 mb-4 overflow-x-auto">
                {children}
              </pre>
            ),
            blockquote: ({ children }) => (
              <blockquote className="border-l-4 border-nier-accent-blue pl-4 py-2 mb-4 text-nier-text-light italic">
                {children}
              </blockquote>
            ),
            table: ({ children }) => (
              <div className="overflow-x-auto mb-4">
                <table className="w-full border-collapse">
                  {children}
                </table>
              </div>
            ),
            thead: ({ children }) => (
              <thead className="bg-nier-bg-header text-nier-text-header">
                {children}
              </thead>
            ),
            th: ({ children }) => (
              <th className="px-4 py-2 text-left text-nier-small tracking-nier border border-nier-border-dark">
                {children}
              </th>
            ),
            td: ({ children }) => (
              <td className="px-4 py-2 text-nier-small border border-nier-border-light">
                {children}
              </td>
            ),
            a: ({ href, children }) => (
              <a
                href={href}
                className="text-nier-accent-blue hover:underline"
                target="_blank"
                rel="noopener noreferrer"
              >
                {children}
              </a>
            ),
            hr: () => (
              <hr className="border-t border-nier-border-dark my-6" />
            ),
            strong: ({ children }) => (
              <strong className="font-medium text-nier-text-main">
                {children}
              </strong>
            ),
            em: ({ children }) => (
              <em className="italic text-nier-text-light">
                {children}
              </em>
            )
          }}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  )
}
