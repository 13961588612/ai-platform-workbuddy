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

import { useEffect, useRef, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApprovalCard } from "./ApprovalCard";
import { markdownComponents } from "./markdownComponents";
import { useChatStore } from "../store/chatStore";
import { formatTime } from "../utils/format";
import { normalizeMarkdownTables } from "../utils/markdownNormalize";
import type { ChatMessage } from "../types/message";

/** Assistant avatar shown beside agent messages. */
function AssistantAvatar(): JSX.Element {
  return (
    <div
      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-100 text-lg ring-2 ring-white"
      aria-hidden
    >
      🤖
    </div>
  );
}

/** Shown while waiting for the first text delta from the agent. */
function ThinkingIndicator(): JSX.Element {
  return (
    <div className="flex items-center gap-1 text-sm text-surface-dark/55">
      <span>正在思考</span>
      <span className="inline-flex w-4 animate-pulse">…</span>
    </div>
  );
}

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

  const assistantContent = useMemo(
    () => normalizeMarkdownTables(message.content ?? ""),
    [message.content],
  );
  const isThinking =
    !isUser &&
    message.status === "streaming" &&
    assistantContent.trim().length === 0;

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
  if (isUser) {
    return (
      <div className="flex justify-end py-2">
        <div className="max-w-[75%] rounded-2xl bg-primary-600 px-4 py-2.5 text-sm text-white">
          <p className="whitespace-pre-wrap">{message.content}</p>
          <div className="mt-1 text-xs text-white/60">
            {formatTime(message.timestamp)}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-start gap-3 py-2">
      <AssistantAvatar />
      <div className="max-w-[75%] rounded-2xl bg-surface-muted px-4 py-2.5 text-sm text-surface-dark">
        {isThinking ? (
          <ThinkingIndicator />
        ) : (
          <div className="prose prose-sm max-w-none prose-p:my-1 prose-pre:my-2">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={markdownComponents}
            >
              {assistantContent}
            </ReactMarkdown>
          </div>
        )}

        {/* Timestamp */}
        {!isThinking && (
          <div className="mt-1 text-xs text-surface-dark/40">
            {formatTime(message.timestamp)}
          </div>
        )}

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
