/**
 * Approval Store (Zusand) — HITL (Human-in-the-Loop) approval state.
 *
 * Manages approval requests across all sessions, including:
 * - Pending approvals awaiting user decision
 * - Approval history (approved / rejected / timeout)
 * - Approval statistics
 *
 * Communicates with the backend's HITL module (backend/src/hitl/)
 * and the push API (backend/src/api/routes/push.py).
 *
 * Approval workflow:
 * 1. Agent triggers approval.request event → approval created (pending)
 * 2. User approves/rejects → POST /api/v1/push/approvals/{id}/respond
 * 3. Backend updates approval status → notifies agent to continue/abort
 * 4. Default timeout: HITL_APPROVAL_TIMEOUT_SECONDS (300s = 5min)
 */

import { create } from "zustand";
import type { ApprovalDetail } from "../types/event";
import { apiGet, apiPost } from "../utils/api";

// ===== Types =====

/** Approval status lifecycle. */
export type ApprovalStatus =
  | "pending"
  | "approved"
  | "rejected"
  | "timeout"
  | "expired";

/** A single approval request record. */
export interface ApprovalRecord {
  /** Unique approval ID. */
  approvalId: string;
  /** Session ID where the approval was triggered. */
  sessionId: string;
  /** Agent ID that triggered the approval. */
  agentId: string;
  /** Skill ID that requires approval. */
  skillId: string;
  /** Approval detail (title, description, etc.). */
  detail: ApprovalDetail;
  /** User ID who needs to approve. */
  userId: string;
  /** Approval status. */
  status: ApprovalStatus;
  /** ISO timestamp when the approval was created. */
  createdAt: string;
  /** ISO timestamp when the approval was resolved (null if pending). */
  resolvedAt: string | null;
  /** User comment when responding (if any). */
  comment: string | null;
  /** Timeout in seconds. */
  timeoutSeconds: number;
}

/** Approval statistics summary. */
export interface ApprovalStats {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
  timeout: number;
}

/** Approval state shape. */
interface ApprovalStoreState {
  /** All approval records (pending + resolved). */
  approvals: ApprovalRecord[];
  /** Whether approvals are being loaded. */
  isLoading: boolean;
  /** Error message (if any). */
  error: string | null;

  // Actions
  /** Fetch all approvals from the backend. */
  fetchApprovals: (status?: ApprovalStatus) => Promise<void>;
  /** Fetch approval statistics. */
  fetchStats: () => Promise<ApprovalStats>;
  /** Add a new approval (from WebSocket event). */
  addApproval: (record: ApprovalRecord) => void;
  /** Respond to an approval (approve/reject). */
  respondApproval: (
    approvalId: string,
    decision: "approved" | "rejected",
    comment?: string,
  ) => Promise<boolean>;
  /** Update an approval's status (from WebSocket event). */
  updateApprovalStatus: (
    approvalId: string,
    status: ApprovalStatus,
    comment?: string,
  ) => void;
  /** Remove an approval from the local state. */
  removeApproval: (approvalId: string) => void;
  /** Clear all approvals. */
  clearApprovals: () => void;
  /** Clear the error state. */
  clearError: () => void;
}

// ===== Store =====

export const useApprovalStore = create<ApprovalStoreState>((set, get) => ({
  approvals: [],
  isLoading: false,
  error: null,

  fetchApprovals: async (status?: ApprovalStatus) => {
    set({ isLoading: true, error: null });
    try {
      const query = status ? `?status=${status}` : "";
      const data = await apiGet<ApprovalRecord[]>(
        `/push/approvals${query}`,
      );
      // Convert snake_case fields to camelCase
      const records: ApprovalRecord[] = (data || []).map(
        (item: Record<string, unknown>) => {
          return {
            approvalId: (item.approval_id as string) ?? (item.approvalId as string) ?? "",
            sessionId: (item.session_id as string) ?? (item.sessionId as string) ?? "",
            agentId: (item.agent_id as string) ?? (item.agentId as string) ?? "",
            skillId: (item.skill_id as string) ?? (item.skillId as string) ?? "",
            detail: (item.detail as ApprovalDetail) ?? {
              title: "",
              description: "",
              skillId: "",
              approvalId: "",
            },
            userId: (item.user_id as string) ?? (item.userId as string) ?? "",
            status: (item.status as ApprovalStatus) ?? "pending",
            createdAt: (item.created_at as string) ?? (item.createdAt as string) ?? "",
            resolvedAt:
              (item.resolved_at as string | null) ??
              (item.resolvedAt as string | null) ??
              null,
            comment: (item.comment as string | null) ?? null,
            timeoutSeconds: (item.timeout_seconds as number) ?? 300,
          };
        },
      );
      set({ approvals: records, isLoading: false });
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "获取审批列表失败";
      set({ isLoading: false, error: message });
    }
  },

  fetchStats: async () => {
    try {
      const data = await apiGet<Record<string, number>>("/push/approvals/stats");
      return {
        total: data.total ?? 0,
        pending: data.pending ?? 0,
        approved: data.approved ?? 0,
        rejected: data.rejected ?? 0,
        timeout: data.timeout ?? 0,
      };
    } catch {
      // Return zeros on error — don't block UI
      return { total: 0, pending: 0, approved: 0, rejected: 0, timeout: 0 };
    }
  },

  addApproval: (record) => {
    set((state) => {
      // Avoid duplicates
      const exists = state.approvals.some(
        (a) => a.approvalId === record.approvalId,
      );
      if (exists) {
        return state;
      }
      return { approvals: [record, ...state.approvals] };
    });
  },

  respondApproval: async (
    approvalId: string,
    decision: "approved" | "rejected",
    comment?: string,
  ): Promise<boolean> => {
    set({ error: null });
    try {
      await apiPost(`/push/approvals/${approvalId}/respond`, {
        decision,
        comment: comment ?? "",
      });

      // Update local state
      get().updateApprovalStatus(approvalId, decision, comment);
      return true;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "审批响应失败";
      set({ error: message });
      return false;
    }
  },

  updateApprovalStatus: (approvalId, status, comment) => {
    set((state) => ({
      approvals: state.approvals.map((a) =>
        a.approvalId === approvalId
          ? {
              ...a,
              status,
              resolvedAt: new Date().toISOString(),
              comment: comment ?? null,
            }
          : a,
      ),
    }));
  },

  removeApproval: (approvalId) => {
    set((state) => ({
      approvals: state.approvals.filter(
        (a) => a.approvalId !== approvalId,
      ),
    }));
  },

  clearApprovals: () => {
    set({ approvals: [], error: null });
  },

  clearError: () => {
    set({ error: null });
  },
}));

export default useApprovalStore;
