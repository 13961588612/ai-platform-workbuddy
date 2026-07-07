/**
 * Chat Store (Zustand).
 *
 * Manages the chat conversation state including:
 * - Current session ID and selected agent
 * - Message history (ChatMessage[])
 * - Streaming state for real-time text assembly
 * - WebSocket connection state
 * - Pending approval requests (HITL)
 *
 * This store is consumed by the useChat hook and ChatPanel / MessageList
 * components.
 */

import { create } from "zustand";
import type { ChatMessage, MessageStatus } from "../types/message";
import type {
  ApprovalDetail,
  TokenUsage,
  WsConnectionState,
} from "../types/event";

// ===== Types =====

/** Chat state shape. */
interface ChatState {
  /** Current session ID. */
  sessionId: string | null;
  /** Currently selected agent ID. */
  agentId: string | null;
  /** All messages in the current session. */
  messages: ChatMessage[];
  /** WebSocket connection state. */
  wsState: WsConnectionState;
  /** Whether the agent is currently generating a response. */
  isGenerating: boolean;
  /** Accumulated token usage for the current session. */
  tokenUsage: TokenUsage;
  /** Pending approval requests (HITL) in the current session. */
  pendingApprovals: PendingApproval[];
  /** Error message (if any). */
  error: string | null;

  // Actions
  /** Set the current session ID. */
  setSessionId: (sessionId: string | null) => void;
  /** Set the selected agent ID. */
  setAgentId: (agentId: string | null) => void;
  /** Set the WebSocket connection state. */
  setWsState: (state: WsConnectionState) => void;
  /** Add a new message to the history. */
  addMessage: (message: ChatMessage) => void;
  /** Update an existing message by ID. */
  updateMessage: (id: string, updates: Partial<ChatMessage>) => void;
  /** Update a message's status. */
  updateMessageStatus: (id: string, status: MessageStatus) => void;
  /** Clear all messages. */
  clearMessages: () => void;
  /** Set the generating flag. */
  setGenerating: (generating: boolean) => void;
  /** Accumulate token usage. */
  addTokenUsage: (usage: TokenUsage) => void;
  /** Set the error message. */
  setError: (error: string | null) => void;
  /** Add a pending approval request. */
  addPendingApproval: (approval: PendingApproval) => void;
  /** Remove a pending approval by ID. */
  removePendingApproval: (approvalId: string) => void;
  /** Reset the chat state for a new session. */
  reset: () => void;
}

/** A pending approval request (HITL). */
export interface PendingApproval {
  approvalId: string;
  skillId: string;
  detail: ApprovalDetail;
  messageId: string;
  createdAt: number;
  status: "pending" | "approved" | "rejected" | "timeout";
}

// ===== Initial State =====

const INITIAL_TOKEN_USAGE: TokenUsage = {
  prompt: 0,
  completion: 0,
  total: 0,
};

// ===== Store =====

export const useChatStore = create<ChatState>((set) => ({
  sessionId: null,
  agentId: null,
  messages: [],
  wsState: "disconnected",
  isGenerating: false,
  tokenUsage: { ...INITIAL_TOKEN_USAGE },
  pendingApprovals: [],
  error: null,

  setSessionId: (sessionId) => {
    set({ sessionId });
  },

  setAgentId: (agentId) => {
    set({ agentId });
  },

  setWsState: (wsState) => {
    set({ wsState });
  },

  addMessage: (message) => {
    set((state) => ({
      messages: [...state.messages, message],
    }));
  },

  updateMessage: (id, updates) => {
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === id ? { ...msg, ...updates } : msg,
      ),
    }));
  },

  updateMessageStatus: (id, status) => {
    set((state) => ({
      messages: state.messages.map((msg) =>
        msg.id === id ? { ...msg, status } : msg,
      ),
    }));
  },

  clearMessages: () => {
    set({
      messages: [],
      pendingApprovals: [],
      tokenUsage: { ...INITIAL_TOKEN_USAGE },
      isGenerating: false,
    });
  },

  setGenerating: (isGenerating) => {
    set({ isGenerating });
  },

  addTokenUsage: (usage) => {
    set((state) => ({
      tokenUsage: {
        prompt: state.tokenUsage.prompt + usage.prompt,
        completion: state.tokenUsage.completion + usage.completion,
        total: state.tokenUsage.total + usage.total,
      },
    }));
  },

  setError: (error) => {
    set({ error });
  },

  addPendingApproval: (approval) => {
    set((state) => ({
      pendingApprovals: [...state.pendingApprovals, approval],
    }));
  },

  removePendingApproval: (approvalId) => {
    set((state) => ({
      pendingApprovals: state.pendingApprovals.filter(
        (a) => a.approvalId !== approvalId,
      ),
    }));
  },

  reset: () => {
    set({
      sessionId: null,
      agentId: null,
      messages: [],
      wsState: "disconnected",
      isGenerating: false,
      tokenUsage: { ...INITIAL_TOKEN_USAGE },
      pendingApprovals: [],
      error: null,
    });
  },
}));

export default useChatStore;
