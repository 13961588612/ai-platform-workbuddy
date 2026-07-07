/**
 * ChatPanel — Main chat input and conversation interface.
 *
 * Provides:
 * - Message input area with auto-resize textarea
 * - Send button with loading state
 * - Agent selector dropdown
 * - Session management (new session, close session)
 * - WebSocket connection status indicator
 *
 * Uses the useChat hook for WebSocket communication.
 */

import React, { useCallback, useRef, useState, useEffect } from "react";
import { useChatStore } from "../store/chatStore";
import { useAuthStore } from "../store/authStore";
import { useChat } from "../hooks/useChat";
import { MessageList } from "./MessageList";
import { AgentSelector } from "./AgentSelector";
import { clsx } from "../utils/format";
import type { WsConnectionState } from "../types/event";

// ===== Connection Status Indicator =====

/** WebSocket connection status badge. */
function ConnectionStatus({ state }: { state: WsConnectionState }): JSX.Element {
  const colors: Record<WsConnectionState, string> = {
    connected: "bg-green-500",
    connecting: "bg-yellow-500",
    reconnecting: "bg-yellow-500",
    disconnected: "bg-gray-400",
    error: "bg-red-500",
  };
  const labels: Record<WsConnectionState, string> = {
    connected: "已连接",
    connecting: "连接中",
    reconnecting: "重连中",
    disconnected: "未连接",
    error: "连接错误",
  };
  return (
    <div className="flex items-center gap-2">
      <span
        className={clsx(
          "inline-block h-2 w-2 rounded-full",
          colors[state],
        )}
      />
      <span className="text-xs text-surface-dark/60">{labels[state]}</span>
    </div>
  );
}

// ===== Component =====

/**
 * ChatPanel — the main chat interface component.
 *
 * Renders the message list, input area, agent selector, and
 * connection status. Manages local input state and delegates
 * WebSocket communication to the useChat hook.
 */
export function ChatPanel(): JSX.Element {
  const [input, setInput] = useState("");
  const [isCreatingSession, setIsCreatingSession] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const { user } = useAuthStore();
  const {
    sessionId,
    agentId,
    messages,
    wsState,
    isGenerating,
    tokenUsage,
    error,
    setError,
  } = useChatStore();

  const { sendMessage, createSession, closeSession } = useChat(sessionId);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = "auto";
      textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
    }
  }, [input]);

  // Handle send
  const handleSend = useCallback((): void => {
    if (!input.trim() || isGenerating) {
      return;
    }
    sendMessage(input);
    setInput("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [input, isGenerating, sendMessage]);

  // Handle Enter key (Shift+Enter for newline)
  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  // Handle new session
  const handleNewSession = useCallback(async (): Promise<void> => {
    if (!agentId) {
      return;
    }
    setIsCreatingSession(true);
    try {
      await createSession(agentId);
    } finally {
      setIsCreatingSession(false);
    }
  }, [agentId, createSession]);

  // Handle agent change — 切换 Agent 时创建新会话
  const handleAgentChange = useCallback(
    (newAgentId: string): void => {
      if (newAgentId === agentId && sessionId) {
        return;
      }
      void createSession(newAgentId);
    },
    [agentId, sessionId, createSession],
  );

  return (
    <div className="flex h-full flex-col bg-white">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-surface-light/50 px-6 py-3">
        <div className="flex items-center gap-4">
          <AgentSelector value={agentId} onChange={handleAgentChange} />
          <ConnectionStatus state={wsState} />
        </div>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => {
              void handleNewSession();
            }}
            className="rounded-md bg-primary-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-primary-700 transition-colors"
            disabled={!agentId || isCreatingSession}
          >
            {isCreatingSession ? "创建中..." : "新建对话"}
          </button>
          {sessionId && (
            <button
              type="button"
              onClick={closeSession}
              className="rounded-md border border-surface-light px-4 py-1.5 text-sm font-medium text-surface-dark/70 hover:bg-surface-muted transition-colors"
            >
              关闭对话
            </button>
          )}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="flex items-center justify-between border-b border-red-200 bg-red-50 px-6 py-2 text-sm text-red-700">
          <span>{error}</span>
          <button
            type="button"
            className="ml-4 shrink-0 text-xs underline"
            onClick={() => setError(null)}
          >
            关闭
          </button>
        </div>
      )}

      {/* Message List */}
      <div className="flex-1 overflow-hidden">
        <MessageList messages={messages} currentUserId={user?.userId ?? ""} />
      </div>

      {/* Token Usage Footer */}
      {tokenUsage.total > 0 && (
        <div className="border-t border-surface-light/50 px-6 py-1.5 text-xs text-surface-dark/40">
          Token: {tokenUsage.prompt} + {tokenUsage.completion} ={" "}
          {tokenUsage.total}
        </div>
      )}

      {/* Input Area */}
      <div className="border-t border-surface-light/50 p-4">
        <div className="flex items-end gap-3">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={agentId ? "输入消息，按 Enter 发送..." : "请先选择一个 Agent"}
            disabled={!agentId || isGenerating}
            rows={1}
            className={clsx(
              "flex-1 resize-none rounded-lg border border-surface-light bg-surface-muted/50 px-4 py-3 text-sm",
              "placeholder:text-surface-dark/30 focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
            style={{ maxHeight: "200px" }}
          />
          <button
            type="button"
            onClick={handleSend}
            disabled={!input.trim() || isGenerating || !agentId}
            className={clsx(
              "rounded-lg px-6 py-3 text-sm font-medium text-white transition-colors",
              "bg-primary-600 hover:bg-primary-700",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            {isGenerating ? "生成中..." : "发送"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default ChatPanel;
