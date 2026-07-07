/**
 * MessageList — Renders the chat message history.
 *
 * Displays messages from the chatStore, handling different message roles:
 * - user: Right-aligned blue bubbles
 * - assistant: Left-aligned white bubbles with markdown rendering
 * - tool: Collapsible tool call/result display
 * - system: Centered gray notification
 *
 * Auto-scrolls to bottom on new messages. Includes the ApprovalCard
 * component for messages that require approval.
 */

import React, { useEffect, useRef, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { ApprovalCard } from "./ApprovalCard";
import { useChatStore } from "../store/chatStore";
import { formatTime, clsx } from "../utils/format";
import type { ChatMessage } from "../types/message";

// ===== Message Bubble =====

/** Props for the MessageBubble component. */
interface MessageBubbleProps {
  message: ChatMessage;
  currentUserId: string;
}

/** Render a single message bubble based on its role. */
function MessageBubble({ message, currentUserId: _currentUserId }: MessageBubbleProps): JSX.Element {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isTool = message.role === "tool";

  // System messages — centered notification
  if (isSystem) {
    return (
      <div className="flex justify-center py-2">
        <span className="rounded-full bg-surface-muted px-4 py-1 text-xs text-surface-dark/50">
          {message.content}
        </span>
      </div>
    );
  }

  // Tool messages — collapsible
  if (isTool) {
    return (
      <div className="flex justify-start py-1">
        <div className="max-w-[80%] rounded-lg border border-surface-light bg-surface-muted/30 p-3 text-sm">
          <div className="mb-1 font-medium text-surface-dark/70">
            {message.toolName ?? "工具调用"}
          </div>
          {message.toolArgs && (
            <details className="mb-1">
              <summary className="cursor-pointer text-xs text-surface-dark/50">
                参数
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-gray-900 p-2 text-xs text-gray-100">
                {message.toolArgs}
              </pre>
            </details>
          )}
          {message.toolResult && (
            <details>
              <summary className="cursor-pointer text-xs text-surface-dark/50">
                结果
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-gray-900 p-2 text-xs text-gray-100">
                {message.toolResult}
              </pre>
            </details>
          )}
        </div>
      </div>
    );
  }

  // User / Assistant messages
  return (
    <div className={clsx("flex py-2", isUser ? "justify-end" : "justify-start")}>
      <div
        className={clsx(
          "max-w-[75%] rounded-2xl px-4 py-2.5 text-sm",
          isUser
            ? "bg-primary-600 text-white"
            : "bg-surface-muted text-surface-dark",
        )}
      >
        {/* Content (markdown for assistant) */}
        {isUser ? (
          <p className="whitespace-pre-wrap">{message.content}</p>
        ) : (
          <div className="prose prose-sm max-w-none prose-p:my-1 prose-pre:my-2">
            <ReactMarkdown
              components={{
                code({ node: _node, className, children, ...props }: {
                  node?: unknown;
                  className?: string;
                  children?: React.ReactNode;
                  [key: string]: unknown;
                }) {
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
              }}
            >
              {message.content || (message.status === "streaming" ? "▋" : "")}
            </ReactMarkdown>
          </div>
        )}

        {/* Timestamp */}
        <div
          className={clsx(
            "mt-1 text-xs",
            isUser ? "text-white/60" : "text-surface-dark/40",
          )}
        >
          {formatTime(message.timestamp)}
        </div>

        {/* Error indicator */}
        {message.status === "error" && message.error && (
          <div className="mt-1 text-xs text-red-400">
            错误: {message.error}
          </div>
        )}
      </div>
    </div>
  );
}

// ===== Component =====

/** Props for the MessageList component. */
interface MessageListProps {
  messages: ChatMessage[];
  currentUserId: string;
}

/**
 * MessageList — renders the full chat message history with auto-scroll.
 */
export function MessageList({ messages, currentUserId }: MessageListProps): JSX.Element {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pendingApprovals = useChatStore((state) => state.pendingApprovals);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    const scrollContainer = scrollRef.current;
    if (scrollContainer) {
      scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }
  }, [messages]);

  // Build a map of approval IDs to pending approval status
  const pendingApprovalIds = useMemo(
    () => new Set(pendingApprovals.map((a) => a.approvalId)),
    [pendingApprovals],
  );

  // Empty state
  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <div className="mb-4 text-6xl">🤖</div>
          <h3 className="text-lg font-medium text-surface-dark/70">
            AI 智能助手
          </h3>
          <p className="mt-2 text-sm text-surface-dark/40">
            选择一个 Agent，开始对话吧
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={scrollRef}
      className="h-full overflow-y-auto px-6 py-4"
    >
      {messages.map((message) => (
        <div key={message.id}>
          <MessageBubble message={message} currentUserId={currentUserId} />
          {/* Show approval card for messages that require approval */}
          {message.requiresApproval && message.approvalId && (
            <ApprovalCard
              approvalId={message.approvalId}
              title={message.content}
              description="此操作需要您的审批"
              isPending={pendingApprovalIds.has(message.approvalId)}
            />
          )}
        </div>
      ))}
    </div>
  );
}

export default MessageList;
