/**
 * useApproval — HITL (Human-in-the-Loop) approval hook.
 *
 * Wraps the approvalStore to provide a convenient interface for
 * approval-related operations:
 * - Fetching pending and historical approvals
 * - Responding to approval requests (approve/reject)
 * - Polling for approval status updates
 * - Computing approval statistics
 *
 * Backend endpoints (from push.py route):
 * - GET    /api/v1/push/approvals           — list approvals
 * - GET    /api/v1/push/approvals/{id}       — get approval detail
 * - POST   /api/v1/push/approvals/{id}/respond — respond to approval
 * - GET    /api/v1/push/approvals/stats      — approval statistics
 */

import { useCallback, useEffect, useMemo } from "react";
import {
  useApprovalStore,
  type ApprovalRecord,
  type ApprovalStats,
  type ApprovalStatus,
} from "../store/approvalStore";

// ===== Configuration =====

/** Polling interval for pending approvals (ms). */
const POLL_INTERVAL = 10000;

// ===== Hook Return Type =====

/** Return type of the useApproval hook. */
interface UseApprovalReturn {
  /** All approval records. */
  approvals: ApprovalRecord[];
  /** Pending approvals only. */
  pendingApprovals: ApprovalRecord[];
  /** Resolved approvals (approved/rejected/timeout). */
  resolvedApprovals: ApprovalRecord[];
  /** Whether approvals are being loaded. */
  isLoading: boolean;
  /** Error message (if any). */
  error: string | null;
  /** Fetch all approvals from the backend. */
  fetchApprovals: (status?: ApprovalStatus) => Promise<void>;
  /** Fetch approval statistics. */
  fetchStats: () => Promise<ApprovalStats>;
  /** Respond to an approval (approve/reject). */
  respondApproval: (
    approvalId: string,
    decision: "approved" | "rejected",
    comment?: string,
  ) => Promise<boolean>;
  /** Clear all approvals. */
  clearApprovals: () => void;
  /** Clear the error state. */
  clearError: () => void;
}

// ===== Hook =====

/**
 * Approval hook — provides HITL approval state and actions.
 *
 * Automatically polls for pending approvals at regular intervals
 * to detect timeouts and new approval requests.
 *
 * @param enablePolling - Whether to enable automatic polling (default: true).
 */
export function useApproval(enablePolling: boolean = true): UseApprovalReturn {
  const {
    approvals,
    isLoading,
    error,
    fetchApprovals,
    fetchStats,
    respondApproval,
    clearApprovals,
    clearError,
  } = useApprovalStore();

  // ===== Initial Load =====
  useEffect(() => {
    fetchApprovals();
  }, [fetchApprovals]);

  // ===== Polling =====
  useEffect(() => {
    if (!enablePolling) {
      return;
    }

    const interval = setInterval(() => {
      // Only poll if there are pending approvals
      const hasPending = useApprovalStore
        .getState()
        .approvals.some((a) => a.status === "pending");
      if (hasPending) {
        fetchApprovals();
      }
    }, POLL_INTERVAL);

    return () => clearInterval(interval);
  }, [enablePolling, fetchApprovals]);

  // ===== Derived Data =====
  const pendingApprovals = useMemo(
    () => approvals.filter((a) => a.status === "pending"),
    [approvals],
  );

  const resolvedApprovals = useMemo(
    () => approvals.filter((a) => a.status !== "pending"),
    [approvals],
  );

  // ===== Wrap respondApproval =====
  const handleRespond = useCallback(
    async (
      approvalId: string,
      decision: "approved" | "rejected",
      comment?: string,
    ): Promise<boolean> => {
      return respondApproval(approvalId, decision, comment);
    },
    [respondApproval],
  );

  return {
    approvals,
    pendingApprovals,
    resolvedApprovals,
    isLoading,
    error,
    fetchApprovals,
    fetchStats,
    respondApproval: handleRespond,
    clearApprovals,
    clearError,
  };
}

export default useApproval;
