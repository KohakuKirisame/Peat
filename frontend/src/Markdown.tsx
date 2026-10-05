import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useApp } from "./api";

export function Markdown({ content }: { content: string }) {
  const { t } = useApp();
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        components={{
          a: ({ href, children }) =>
            href ? (
              <a href={href} target="_blank" rel="noopener noreferrer">
                {children}
              </a>
            ) : (
              <span>{children}</span>
            ),
          table: ({ children }) => (
            <div
              className="markdown-table"
              tabIndex={0}
              aria-label={t("Research table", "研究表格")}
            >
              <table>{children}</table>
            </div>
          ),
          img: ({ alt }) => <span>{alt}</span>,
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
