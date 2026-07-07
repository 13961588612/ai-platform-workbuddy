/**
 * AgentEvent type definitions for the frontend.
 *
 * Mirrors backend's src/runtime/events.py — AgentEventType, AgentEvent,
 * TokenUsage — and the Gateway's ChannelCapability.ts AgentEvent interface.
 *
 * Backend uses snake_case (tool_name, skill_id), frontend uses camelCase.
 * The cardAdapter.ts utility handles the conversion.
 */

// ===== Agent Event Types =====

/** Enumeration of all AgentEvent types (matches backend AgentEventType). */
export type AgentEventType =
  | "text.delta"
  | "tool.call"
  | "tool.result"
  | "ui.render"
  | "approval.request"
  | "error"
  | "done";

// ===== Token Usage =====

/** Token usage for a single LLM call. */
export interface TokenUsage {
  prompt: number;
  completion: number;
  total: number;
}

// ===== Approval Detail =====

/**
 * Detail payload for an approval.request event.
 *
 * Aligns with gateway/src/router/BotEventMapper.ts ApprovalDetail interface.
 */
export interface ApprovalDetail {
  title: string;
  description: string;
  skillId: string;
  approvalId: string;
  /** Additional context fields. */
  [key: string]: unknown;
}

// ===== Agent Event =====

/**
 * Unified event in the Agent streaming protocol (frontend representation).
 *
 * Each event has a `type` field and optional fields populated based on type:
 * - text.delta:       content
 * - tool.call:        toolName, args
 * - tool.result:      toolName, result
 * - ui.render:        component, props
 * - approval.request: skillId, detail
 * - error:            errorCode, message
 * - done:             tokenUsage
 */
export interface AgentEvent {
  type: AgentEventType;
  content?: string;
  toolName?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  component?: string;
  props?: Record<string, unknown>;
  skillId?: string;
  detail?: ApprovalDetail;
  errorCode?: string;
  message?: string;
  tokenUsage?: TokenUsage;
}

// ===== Raw Event (from WebSocket, snake_case) =====

/**
 * Raw event as received from the WebSocket (backend/Gateway format).
 * Uses snake_case field names. The cardAdapter converts this to AgentEvent.
 */
export interface RawAgentEvent {
  type: AgentEventType;
  content?: string;
  tool_name?: string;
  args?: Record<string, unknown>;
  result?: Record<string, unknown>;
  component?: string;
  props?: Record<string, unknown>;
  skill_id?: string;
  detail?: Record<string, unknown>;
  error_code?: string;
  message?: string;
  token_usage?: {
    prompt: number;
    completion: number;
    total: number;
  };
}

// ===== WebSocket Connection State =====

/** WebSocket connection status. */
export type WsConnectionState =
  | "disconnected"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "error";

// ===== WebSocket Message Envelope =====

/** Envelope for messages received over WebSocket. */
export interface WsMessage {
  /** Message type. */
  type: string;
  /** Message payload. */
  data: unknown;
  /** Server timestamp. */
  timestamp?: string;
}
