/**
 * Message-related type definitions for the frontend.
 *
 * Aligns with the Gateway's InboundMessage (gateway/src/types) and
 * the backend's session message model. All fields use camelCase
 * per frontend convention.
 */

// ===== Message Role =====

/** Role of a message sender. */
export type MessageRole = "user" | "assistant" | "system" | "tool";

// ===== Message Status =====

/** Delivery / processing status of a chat message. */
export type MessageStatus =
  | "pending"
  | "sending"
  | "streaming"
  | "delivered"
  | "error";

// ===== Chat Message =====

/** A single chat message in a conversation. */
export interface ChatMessage {
  /** Unique message ID (UUID). */
  id: string;
  /** Session/conversation ID. */
  sessionId: string;
  /** Sender role. */
  role: MessageRole;
  /** Message text content. */
  content: string;
  /** Message status. */
  status: MessageStatus;
  /** ISO 8601 timestamp. */
  timestamp: string;
  /** Agent ID that produced this message (for assistant role). */
  agentId?: string;
  /** Tool name if this is a tool message. */
  toolName?: string;
  /** Tool call arguments (JSON string). */
  toolArgs?: string;
  /** Tool result (JSON string). */
  toolResult?: string;
  /** Whether this message requires approval. */
  requiresApproval?: boolean;
  /** Approval ID if this message is part of a HITL flow. */
  approvalId?: string;
  /** Error message if status is "error". */
  error?: string;
  /** Token usage for this message (if available). */
  tokenUsage?: TokenUsageSummary;
}

// ===== Token Usage Summary =====

/** Token usage summary for a message or session. */
export interface TokenUsageSummary {
  prompt: number;
  completion: number;
  total: number;
}

// ===== Inbound Message (WebSocket) =====

/**
 * Inbound message sent from the frontend to the Gateway via WebSocket.
 *
 * Aligns with gateway/src/types InboundMessage — the Gateway
 * forwards this to the Agent Core for processing.
 */
export interface InboundMessage {
  /** Message type identifier. */
  type: "chat" | "approval" | "ping" | "session.create" | "session.close";
  /** Session/conversation ID. */
  sessionId: string;
  /** User ID (from JWT). */
  userId: string;
  /** Agent ID to route to. */
  agentId?: string;
  /** Message text content (for chat type). */
  content?: string;
  /** Approval response (for approval type). */
  approvalResponse?: {
    approvalId: string;
    decision: "approved" | "rejected";
    comment?: string;
  };
  /** Client timestamp for ordering. */
  timestamp: string;
}

// ===== Session Info =====

/** Session/conversation summary. */
export interface SessionInfo {
  sessionId: string;
  userId: string;
  agentId: string;
  title: string;
  messageCount: number;
  createdAt: string;
  updatedAt: string;
  lastMessagePreview: string;
}

// ===== Unified API Response =====

/**
 * Unified API response format.
 * All backend APIs return: { code, data, message, traceId }
 */
export interface ApiResponse<T = unknown> {
  /** 0 = success, non-zero = error. */
  code: number;
  /** Response payload (null on error). */
  data: T | null;
  /** Human-readable message. */
  message: string;
  /** Request trace ID for correlation. */
  traceId: string;
}
