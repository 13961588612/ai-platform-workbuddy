/**
 * Card Adapter — converts backend snake_case events to frontend camelCase.
 *
 * The backend AgentEvent (src/runtime/events.py) uses snake_case field
 * names (tool_name, skill_id, error_code, token_usage). The frontend
 * AgentEvent type (types/event.ts) uses camelCase. This adapter bridges
 * the gap.
 *
 * Also handles the Gateway's BotEventMapper approval card format:
 * approval.request events contain a detail object with title, description,
 * skillId, approvalId fields.
 */

import type {
  AgentEvent,
  ApprovalDetail,
  RawAgentEvent,
  TokenUsage,
} from "../types/event";

// ===== Snake-case to camelCase conversion =====

/**
 * Convert a snake_case string to camelCase.
 * @example snakeToCamel("tool_name") → "toolName"
 */
function snakeToCamel(s: string): string {
  return s.replace(/_([a-z])/g, (_, letter: string) => letter.toUpperCase());
}

/**
 * Recursively convert all object keys from snake_case to camelCase.
 * Handles nested objects and arrays of objects.
 */
export function camelizeKeys<T = unknown>(obj: unknown): T {
  if (obj === null || obj === undefined) {
    return obj as T;
  }
  if (Array.isArray(obj)) {
    return obj.map((item) => camelizeKeys(item)) as unknown as T;
  }
  if (typeof obj === "object" && obj instanceof Object) {
    const result: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(obj)) {
      const camelKey = snakeToCamel(key);
      result[camelKey] = camelizeKeys(value);
    }
    return result as T;
  }
  return obj as T;
}

// ===== Raw Event → Agent Event =====

/**
 * Convert a RawAgentEvent (snake_case, from WebSocket) to an AgentEvent
 * (camelCase, frontend representation).
 *
 * Handles all event types:
 * - text.delta:       copies content
 * - tool.call:        copies toolName, args
 * - tool.result:      copies toolName, result
 * - ui.render:        copies component, props
 * - approval.request: copies skillId, detail (as ApprovalDetail)
 * - error:            copies errorCode, message
 * - done:             copies tokenUsage
 */
export function adaptAgentEvent(raw: RawAgentEvent): AgentEvent {
  const event: AgentEvent = { type: raw.type };

  // Common fields
  if (raw.content !== undefined) {
    event.content = raw.content;
  }

  // Tool-related fields
  if (raw.tool_name !== undefined) {
    event.toolName = raw.tool_name;
  }
  if (raw.args !== undefined) {
    event.args = raw.args;
  }
  if (raw.result !== undefined) {
    event.result = raw.result;
  }

  // UI render fields
  if (raw.component !== undefined) {
    event.component = raw.component;
  }
  if (raw.props !== undefined) {
    event.props = raw.props;
  }

  // Approval fields
  if (raw.skill_id !== undefined) {
    event.skillId = raw.skill_id;
  }
  if (raw.detail !== undefined) {
    event.detail = adaptApprovalDetail(raw.detail);
  }

  // Error fields
  if (raw.error_code !== undefined) {
    event.errorCode = raw.error_code;
  } else if ((raw as Record<string, unknown>).errorCode !== undefined) {
    event.errorCode = (raw as Record<string, unknown>).errorCode as string;
  }
  if (raw.message !== undefined) {
    event.message = raw.message;
  } else if ((raw as Record<string, unknown>).errorMessage !== undefined) {
    event.message = (raw as Record<string, unknown>).errorMessage as string;
  }

  // Token usage
  if (raw.token_usage !== undefined) {
    event.tokenUsage = {
      prompt: raw.token_usage.prompt,
      completion: raw.token_usage.completion,
      total: raw.token_usage.total,
    };
  }

  return event;
}

// ===== Approval Detail Adapter =====

/**
 * Convert a raw approval detail (snake_case dict from backend) to
 * the frontend ApprovalDetail interface.
 *
 * The Gateway's BotEventMapper maps approval.request to a
 * button_interaction card with the following fields:
 * - title:        Card title
 * - description:  Card description
 * - skill_id:     Skill that triggered the approval
 * - approval_id:  Unique approval request ID
 */
export function adaptApprovalDetail(
  raw: Record<string, unknown>,
): ApprovalDetail {
  const detail: ApprovalDetail = {
    title: (raw.title as string) ?? (raw["title"] as string) ?? "",
    description:
      (raw.description as string) ?? (raw["description"] as string) ?? "",
    skillId: (raw.skill_id as string) ?? (raw["skillId"] as string) ?? "",
    approvalId:
      (raw.approval_id as string) ?? (raw["approvalId"] as string) ?? "",
  };

  // Copy any additional fields
  for (const [key, value] of Object.entries(raw)) {
    const camelKey = snakeToCamel(key);
    if (!(camelKey in detail)) {
      (detail as Record<string, unknown>)[camelKey] = camelizeKeys(value);
    }
  }

  return detail;
}

// ===== Token Usage Adapter =====

/**
 * Convert a raw token usage object (snake_case from backend) to
 * the frontend TokenUsage interface.
 */
export function adaptTokenUsage(
  raw: { prompt: number; completion: number; total: number } | undefined,
): TokenUsage | undefined {
  if (!raw) {
    return undefined;
  }
  return {
    prompt: raw.prompt,
    completion: raw.completion,
    total: raw.total,
  };
}

// ===== Batch Event Adaptation =====

/**
 * Convert an array of raw events to frontend AgentEvent[].
 * Useful when processing a batch of buffered WebSocket messages.
 */
export function adaptAgentEvents(rawEvents: RawAgentEvent[]): AgentEvent[] {
  return rawEvents.map(adaptAgentEvent);
}
