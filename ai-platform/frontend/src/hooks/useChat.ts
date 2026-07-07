/**
 * useChat — WebSocket chat hook.
 *
 * Manages the WebSocket lifecycle for real-time chat communication
 * with the Gateway. Handles:
 * - WebSocket connection / reconnection
 * - Sending inbound messages (chat, approval responses)
 * - Receiving and processing AgentEvent streams
 * - Assembling streaming text deltas into complete messages
 * - Forwarding approval.request events to the approvalStore
 *
 * WebSocket endpoint: /ws/chat (Gateway's H5 WebSocket route)
 * Message format aligns with gateway/src/server.ts and
 * gateway/src/channels/ChannelCapability.ts
 */

import { useCallback, useEffect, useRef } from "react";
import { useChatStore, type PendingApproval } from "../store/chatStore";
import { useApprovalStore } from "../store/approvalStore";
import { useAuthStore } from "../store/authStore";
import { apiPost } from "../utils/api";
import { adaptAgentEvent } from "../utils/cardAdapter";
import { getChatWsUrl } from "../utils/api";
import {
  normalizeCreateSessionResponse,
  type RawCreateSessionResponse,
} from "../utils/sessionAdapter";
import type { AgentEvent, RawAgentEvent } from "../types/event";
import type { ChatMessage, InboundMessage } from "../types/message";

// ===== Configuration =====

/** Maximum reconnection attempts before giving up. */
const MAX_RECONNECT_ATTEMPTS = 5;

/** Base delay for exponential backoff reconnection (ms). */
const RECONNECT_BASE_DELAY = 1000;

/** Heartbeat ping interval (ms). */
const HEARTBEAT_INTERVAL = 30000;

// ===== Hook Return Type =====

/** Return type of the useChat hook. */
interface UseChatReturn {
  /** Send a chat message. */
  sendMessage: (content: string) => void;
  /** Respond to an approval request. */
  respondToApproval: (
    approvalId: string,
    decision: "approved" | "rejected",
    comment?: string,
  ) => void;
  /** Create a new session. */
  createSession: (agentId: string) => Promise<void>;
  /** Close the current session. */
  closeSession: () => void;
  /** Manually reconnect the WebSocket. */
  reconnect: () => void;
}

// ===== Hook =====

/**
 * Chat WebSocket hook — manages real-time communication with the Gateway.
 *
 * Connects to the /ws/chat endpoint and processes AgentEvent streams.
 * Must be called within a component that has access to the authStore
 * (user must be authenticated).
 *
 * @param sessionId - The current session ID (null to skip connection).
 */
export function useChat(sessionId: string | null): UseChatReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );
  const streamingMessageIdRef = useRef<string | null>(null);

  const {
    sessionId: currentSessionId,
    agentId,
    setSessionId,
    setAgentId,
    setWsState,
    addMessage,
    updateMessage,
    updateMessageStatus,
    clearMessages,
    setGenerating,
    addTokenUsage,
    setError,
    addPendingApproval,
    removePendingApproval,
  } = useChatStore();

  const { addApproval, updateApprovalStatus } = useApprovalStore();
  const { user } = useAuthStore();

  // ===== Generate unique ID =====
  const generateId = useCallback((): string => {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
  }, []);

  // ===== Send Inbound Message =====
  const sendInbound = useCallback(
    (message: InboundMessage): boolean => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        setError("WebSocket 未连接，无法发送消息");
        return false;
      }
      ws.send(JSON.stringify(message));
      return true;
    },
    [setError],
  );

  /** 发送失败或异常时解除「生成中」并标记占位消息为错误。 */
  const abortGenerating = useCallback(
    (errorMessage?: string): void => {
      const streamingId = streamingMessageIdRef.current;
      if (streamingId) {
        updateMessageStatus(streamingId, "error");
        streamingMessageIdRef.current = null;
      }
      setGenerating(false);
      if (errorMessage) {
        setError(errorMessage);
      }
    },
    [updateMessageStatus, setGenerating, setError],
  );

  // ===== Handle Raw Event =====
  const handleRawEvent = useCallback(
    (rawEvent: RawAgentEvent): void => {
      const event: AgentEvent = adaptAgentEvent(rawEvent);

      switch (event.type) {
        case "text.delta": {
          // Accumulate text delta into the streaming message
          const streamingId = streamingMessageIdRef.current;
          if (streamingId) {
            const messages = useChatStore.getState().messages;
            const existing = messages.find((m) => m.id === streamingId);
            if (existing) {
              updateMessage(streamingId, {
                content: existing.content + (event.content ?? ""),
                status: "streaming",
              });
            }
          }
          break;
        }

        case "tool.call": {
          // Add a tool call message
          const toolMessageId = generateId();
          const toolMessage: ChatMessage = {
            id: toolMessageId,
            sessionId: sessionId ?? "",
            role: "tool",
            content: `调用工具: ${event.toolName ?? "unknown"}`,
            status: "delivered",
            timestamp: new Date().toISOString(),
            toolName: event.toolName,
            toolArgs: event.args ? JSON.stringify(event.args, null, 2) : undefined,
          };
          addMessage(toolMessage);
          break;
        }

        case "tool.result": {
          // Update the last tool message with the result
          const messages = useChatStore.getState().messages;
          const lastToolMessage = [...messages]
            .reverse()
            .find((m) => m.role === "tool" && m.toolName === event.toolName);
          if (lastToolMessage) {
            updateMessage(lastToolMessage.id, {
              toolResult: event.result
                ? JSON.stringify(event.result, null, 2)
                : undefined,
              content: `工具 ${event.toolName ?? "unknown"} 执行完成`,
            });
          }
          break;
        }

        case "ui.render": {
          // UI render events can be handled by specific components
          // For now, we add them as system messages
          const uiMessage: ChatMessage = {
            id: generateId(),
            sessionId: sessionId ?? "",
            role: "system",
            content: `[UI: ${event.component ?? "unknown"}]`,
            status: "delivered",
            timestamp: new Date().toISOString(),
          };
          addMessage(uiMessage);
          break;
        }

        case "approval.request": {
          // Forward to approval store and chat store
          if (event.detail) {
            const approvalId = event.detail.approvalId;
            const messageId = generateId();
            const approvalMessage: ChatMessage = {
              id: messageId,
              sessionId: sessionId ?? "",
              role: "assistant",
              content: event.detail.description || "需要审批操作",
              status: "delivered",
              timestamp: new Date().toISOString(),
              requiresApproval: true,
              approvalId,
            };
            addMessage(approvalMessage);

            const pendingApproval: PendingApproval = {
              approvalId,
              skillId: event.skillId ?? event.detail.skillId,
              detail: event.detail,
              messageId,
              createdAt: Date.now(),
              status: "pending",
            };
            addPendingApproval(pendingApproval);
            addApproval({
              approvalId,
              sessionId: sessionId ?? "",
              agentId: agentId ?? "",
              skillId: event.skillId ?? event.detail.skillId,
              detail: event.detail,
              userId: user?.userId ?? "",
              status: "pending",
              createdAt: new Date().toISOString(),
              resolvedAt: null,
              comment: null,
              timeoutSeconds: 300,
            });
          }
          break;
        }

        case "error": {
          setError(
            `错误 [${event.errorCode ?? "unknown"}]: ${event.message ?? "未知错误"}`,
          );
          // Finalize the streaming message with error status
          const streamingId = streamingMessageIdRef.current;
          if (streamingId) {
            updateMessageStatus(streamingId, "error");
            streamingMessageIdRef.current = null;
          }
          setGenerating(false);
          break;
        }

        case "done": {
          // Finalize the streaming message
          const streamingId = streamingMessageIdRef.current;
          if (streamingId) {
            updateMessageStatus(streamingId, "delivered");
            streamingMessageIdRef.current = null;
          }
          // Accumulate token usage
          if (event.tokenUsage) {
            addTokenUsage(event.tokenUsage);
          }
          setGenerating(false);
          break;
        }

        default: {
          // Unknown event type — ignore
          break;
        }
      }
    },
    [
      sessionId,
      agentId,
      user,
      generateId,
      addMessage,
      updateMessage,
      updateMessageStatus,
      addTokenUsage,
      setGenerating,
      setError,
      addPendingApproval,
      addApproval,
    ],
  );

  // ===== WebSocket Message Handler =====
  const handleWsMessage = useCallback(
    (data: string): void => {
      try {
        const parsed = JSON.parse(data) as {
          type?: string;
          data?: unknown;
          event?: RawAgentEvent;
          [key: string]: unknown;
        };

        // Handle different message envelope formats
        if (parsed.type === "event" && parsed.event) {
          handleRawEvent(parsed.event);
        } else if (parsed.type === "agent_event" && parsed.event) {
          handleRawEvent(parsed.event as RawAgentEvent);
        } else if (parsed.type && parsed.type.includes(".")) {
          // Direct event (no envelope)
          handleRawEvent(parsed as unknown as RawAgentEvent);
        } else if (parsed.data && typeof parsed.data === "object") {
          const dataObj = parsed.data as Record<string, unknown>;
          if (dataObj.type && typeof dataObj.type === "string") {
            handleRawEvent(dataObj as unknown as RawAgentEvent);
          }
        }
      } catch (err) {
        console.error("Failed to parse WebSocket message:", err);
      }
    },
    [handleRawEvent],
  );

  // ===== Connect WebSocket =====
  const connect = useCallback((): void => {
    if (!sessionId || !user) {
      return;
    }

    // Close existing connection
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    setWsState("connecting");
    const wsUrl = getChatWsUrl(sessionId, user.userId);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      setWsState("connected");
      reconnectAttemptsRef.current = 0;

      // Start heartbeat
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
      }
      heartbeatIntervalRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping", timestamp: new Date().toISOString() }));
        }
      }, HEARTBEAT_INTERVAL);
    };

    ws.onmessage = (event: MessageEvent) => {
      handleWsMessage(event.data as string);
    };

    ws.onerror = () => {
      setWsState("error");
      setError("WebSocket 连接错误");
    };

    ws.onclose = () => {
      setWsState("disconnected");
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = null;
      }

      // Attempt reconnection
      if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
        reconnectAttemptsRef.current++;
        const delay =
          RECONNECT_BASE_DELAY *
          Math.pow(2, reconnectAttemptsRef.current - 1);
        setWsState("reconnecting");
        setTimeout(() => {
          connect();
        }, delay);
      }
    };
  }, [sessionId, user, setWsState, setError, handleWsMessage]);

  // ===== Auto-connect when sessionId changes =====
  useEffect(() => {
    if (sessionId && user) {
      connect();
    }

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (heartbeatIntervalRef.current) {
        clearInterval(heartbeatIntervalRef.current);
        heartbeatIntervalRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, user]);

  // ===== Send Chat Message =====
  const sendMessage = useCallback(
    (content: string): void => {
      if (!content.trim()) {
        return;
      }

      // Add user message to history
      const userMessage: ChatMessage = {
        id: generateId(),
        sessionId: sessionId ?? "",
        role: "user",
        content,
        status: "delivered",
        timestamp: new Date().toISOString(),
      };
      addMessage(userMessage);

      // Prepare streaming assistant message placeholder
      const assistantMessageId = generateId();
      const assistantMessage: ChatMessage = {
        id: assistantMessageId,
        sessionId: sessionId ?? "",
        role: "assistant",
        content: "",
        status: "streaming",
        timestamp: new Date().toISOString(),
        agentId: agentId ?? undefined,
      };
      addMessage(assistantMessage);
      streamingMessageIdRef.current = assistantMessageId;
      setGenerating(true);

      // Send inbound message
      const inbound: InboundMessage = {
        type: "chat",
        sessionId: sessionId ?? "",
        userId: user?.userId ?? "",
        agentId: agentId ?? undefined,
        content,
        timestamp: new Date().toISOString(),
      };
      if (!sendInbound(inbound)) {
        abortGenerating("WebSocket 未连接，无法发送消息");
        return;
      }
    },
    [
      sessionId,
      agentId,
      user,
      generateId,
      addMessage,
      setGenerating,
      sendInbound,
      abortGenerating,
    ],
  );

  // ===== Respond to Approval =====
  const respondToApproval = useCallback(
    (
      approvalId: string,
      decision: "approved" | "rejected",
      comment?: string,
    ): void => {
      const inbound: InboundMessage = {
        type: "approval",
        sessionId: sessionId ?? "",
        userId: user?.userId ?? "",
        approvalResponse: {
          approvalId,
          decision,
          comment: comment ?? "",
        },
        timestamp: new Date().toISOString(),
      };
      sendInbound(inbound);
      removePendingApproval(approvalId);
    },
    [sessionId, user, sendInbound, removePendingApproval],
  );

  // ===== Create Session =====
  const createSession = useCallback(
    async (newAgentId: string): Promise<void> => {
      if (!user?.userId) {
        setError("用户未登录，无法创建会话");
        return;
      }

      streamingMessageIdRef.current = null;
      setGenerating(false);

      try {
        const raw = await apiPost<RawCreateSessionResponse>("/sessions", {
          agent_id: newAgentId,
          user_id: user.userId,
          channel: "web",
        });
        const data = normalizeCreateSessionResponse(raw);

        setAgentId(newAgentId);
        clearMessages();
        setSessionId(data.sessionId);
        setError(null);
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "创建会话失败，请稍后重试";
        setError(message);
      }
    },
    [user, setAgentId, setSessionId, clearMessages, setError, setGenerating],
  );

  // ===== Close Session =====
  const closeSession = useCallback((): void => {
    if (sessionId) {
      const inbound: InboundMessage = {
        type: "session.close",
        sessionId,
        userId: user?.userId ?? "",
        timestamp: new Date().toISOString(),
      };
      sendInbound(inbound);
    }

    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    clearMessages();
    setSessionId(null);
    setGenerating(false);
  }, [sessionId, user, sendInbound, clearMessages, setSessionId, setGenerating]);

  // ===== Manual Reconnect =====
  const reconnect = useCallback((): void => {
    reconnectAttemptsRef.current = 0;
    connect();
  }, [connect]);

  return {
    sendMessage,
    respondToApproval,
    createSession,
    closeSession,
    reconnect,
  };
}

export default useChat;
