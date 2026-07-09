/**
 * Shared ReactMarkdown component overrides (tables, code blocks).
 */
import type { Components } from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";

export const markdownComponents: Components = {
  table({ children }: { children?: React.ReactNode }) {
    return (
      <div className="my-2 overflow-x-auto">
        <table className="min-w-full border-collapse text-sm">{children}</table>
      </div>
    );
  },
  thead({ children }: { children?: React.ReactNode }) {
    return <thead className="bg-gray-100/80">{children}</thead>;
  },
  th({ children }: { children?: React.ReactNode }) {
    return (
      <th className="border border-gray-200 px-3 py-1.5 text-left font-medium text-surface-dark">
        {children}
      </th>
    );
  },
  td({ children }: { children?: React.ReactNode }) {
    return (
      <td className="border border-gray-200 px-3 py-1.5 text-surface-dark/90">
        {children}
      </td>
    );
  },
  tr({ children }: { children?: React.ReactNode }) {
    return <tr className="even:bg-white/60">{children}</tr>;
  },
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className ?? "");
    const isInline = !className;
    if (isInline) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    }
    return (
      <SyntaxHighlighter
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        style={oneDark as any}
        language={match?.[1] ?? "text"}
        PreTag="div"
      >
        {String(children).replace(/\n$/, "")}
      </SyntaxHighlighter>
    );
  },
};
