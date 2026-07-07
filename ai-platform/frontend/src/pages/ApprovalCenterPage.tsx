/**
 * ApprovalCenterPage — HITL Approval Center admin page.
 *
 * Displays all approval requests (pending and resolved) with:
 * - Statistics summary (total, pending, approved, rejected, timeout)
 * - Filterable approval list
 * - Inline approve/reject actions
 * - Approval detail view
 *
 * Backend endpoints (from push.py route):
 * - GET  /api/v1/push/approvals           — list approvals
 * - GET  /api/v1/push/approvals/{id}       — get approval detail
 * - POST /api/v1/push/approvals/{id}/respond — respond to approval
 * - GET  /api/v1/push/approvals/stats      — approval statistics
 */

import { useCallback, useEffect, useState } from "react";
import { Layout } from "../components/Layout";
import { useApproval } from "../hooks/useApproval";
import {
  formatDateTime,
  formatRelativeTime,
  clsx,
} from "../utils/format";
import type { ApprovalStatus, ApprovalRecord } from "../store/approvalStore";

// ===== Status Display =====

/** Status badge label (Chinese). */
function getStatusLabel(status: ApprovalStatus): string {
  const labels: Record<ApprovalStatus, string> = {
    pending: "待审批",
    approved: "已同意",
    rejected: "已拒绝",
    timeout: "已超时",
    expired: "已过期",
  };
  return labels[status] ?? status;
}

/** Status badge CSS classes. */
function getStatusColor(status: ApprovalStatus): string {
  const colors: Record<ApprovalStatus, string> = {
    pending: "bg-yellow-100 text-yellow-700",
    approved: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-700",
    timeout: "bg-gray-100 text-gray-700",
    expired: "bg-gray-100 text-gray-700",
  };
  return colors[status] ?? "bg-gray-100 text-gray-700";
}

// ===== Component =====

/**
 * ApprovalCenterPage — admin page for managing HITL approvals.
 */
export function ApprovalCenterPage(): JSX.Element {
  const {
    approvals,
    pendingApprovals,
    resolvedApprovals,
    isLoading,
    error,
    fetchApprovals,
    respondApproval,
    clearError,
  } = useApproval(false);

  const [filterStatus, setFilterStatus] = useState<string>("");
  const [responding, setResponding] = useState<string | null>(null);
  const [comment, setComment] = useState<Record<string, string>>({});

  // ===== Filtered Approvals =====
  const displayApprovals = filterStatus
    ? approvals.filter((a) => a.status === filterStatus)
    : approvals;

  // ===== Stats =====
  const stats = {
    total: approvals.length,
    pending: pendingApprovals.length,
    approved: resolvedApprovals.filter((a) => a.status === "approved").length,
    rejected: resolvedApprovals.filter((a) => a.status === "rejected").length,
    timeout: resolvedApprovals.filter((a) => a.status === "timeout").length,
  };

  // ===== Handle Respond =====
  const handleRespond = useCallback(
    async (
      approvalId: string,
      decision: "approved" | "rejected",
    ): Promise<void> => {
      setResponding(approvalId);
      const userComment = comment[approvalId] ?? "";
      await respondApproval(approvalId, decision, userComment);
      setResponding(null);
      // Clear comment
      setComment((prev) => {
        const next = { ...prev };
        delete next[approvalId];
        return next;
      });
    },
    [comment, respondApproval],
  );

  return (
    <Layout
      title="审批中心"
      breadcrumbs={["管理后台", "审批中心"]}
    >
      {/* Stats Cards */}
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-5">
        <div className="rounded-lg bg-white p-4 shadow-sm">
          <p className="text-xs text-surface-dark/50">总审批数</p>
          <p className="mt-1 text-2xl font-bold text-surface-dark">
            {stats.total}
          </p>
        </div>
        <div className="rounded-lg bg-white p-4 shadow-sm">
          <p className="text-xs text-surface-dark/50">待审批</p>
          <p className="mt-1 text-2xl font-bold text-yellow-600">
            {stats.pending}
          </p>
        </div>
        <div className="rounded-lg bg-white p-4 shadow-sm">
          <p className="text-xs text-surface-dark/50">已同意</p>
          <p className="mt-1 text-2xl font-bold text-green-600">
            {stats.approved}
          </p>
        </div>
        <div className="rounded-lg bg-white p-4 shadow-sm">
          <p className="text-xs text-surface-dark/50">已拒绝</p>
          <p className="mt-1 text-2xl font-bold text-red-600">
            {stats.rejected}
          </p>
        </div>
        <div className="rounded-lg bg-white p-4 shadow-sm">
          <p className="text-xs text-surface-dark/50">已超时</p>
          <p className="mt-1 text-2xl font-bold text-gray-500">
            {stats.timeout}
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-4 flex items-center gap-4">
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="rounded-md border border-surface-light bg-white px-3 py-2 text-sm"
        >
          <option value="">全部状态</option>
          <option value="pending">待审批</option>
          <option value="approved">已同意</option>
          <option value="rejected">已拒绝</option>
          <option value="timeout">已超时</option>
        </select>
        <button
          type="button"
          onClick={() => fetchApprovals()}
          className="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          刷新
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="mb-4 flex items-center justify-between rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <span>{error}</span>
          <button
            type="button"
            onClick={clearError}
            className="text-xs text-red-600 hover:text-red-700"
          >
            关闭
          </button>
        </div>
      )}

      {/* Approvals Table */}
      <div className="overflow-hidden rounded-lg bg-white shadow-sm">
        <table className="min-w-full divide-y divide-surface-light">
          <thead className="bg-surface-muted/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                审批 ID
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                标题
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                Skill
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                状态
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                创建时间
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                解决时间
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                操作
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-light">
            {isLoading && displayApprovals.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-surface-dark/40">
                  加载中...
                </td>
              </tr>
            ) : displayApprovals.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-6 py-8 text-center text-sm text-surface-dark/40">
                  暂无审批记录
                </td>
              </tr>
            ) : (
              displayApprovals.map((approval: ApprovalRecord) => (
                <tr key={approval.approvalId} className="hover:bg-surface-muted/30">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-surface-dark">
                    {approval.approvalId.slice(0, 12)}...
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/70">
                    {approval.detail?.title || "—"}
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/70">
                    {approval.skillId || "—"}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={clsx(
                        "rounded-full px-2 py-0.5 text-xs font-medium",
                        getStatusColor(approval.status),
                      )}
                    >
                      {getStatusLabel(approval.status)}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/50">
                    {formatRelativeTime(approval.createdAt)}
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/50">
                    {approval.resolvedAt
                      ? formatDateTime(approval.resolvedAt)
                      : "—"}
                  </td>
                  <td className="px-6 py-4">
                    {approval.status === "pending" ? (
                      <div className="space-y-2">
                        {/* Comment input */}
                        <input
                          type="text"
                          value={comment[approval.approvalId] ?? ""}
                          onChange={(e) =>
                            setComment((prev) => ({
                              ...prev,
                              [approval.approvalId]: e.target.value,
                            }))
                          }
                          placeholder="备注（可选）"
                          className="w-full rounded border border-surface-light px-2 py-1 text-xs"
                        />
                        {/* Action buttons */}
                        <div className="flex gap-2">
                          <button
                            type="button"
                            onClick={() => handleRespond(approval.approvalId, "approved")}
                            disabled={responding === approval.approvalId}
                            className="rounded bg-green-600 px-3 py-1 text-xs font-medium text-white hover:bg-green-700 disabled:opacity-50"
                          >
                            同意
                          </button>
                          <button
                            type="button"
                            onClick={() => handleRespond(approval.approvalId, "rejected")}
                            disabled={responding === approval.approvalId}
                            className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
                          >
                            拒绝
                          </button>
                        </div>
                      </div>
                    ) : (
                      <span className="text-xs text-surface-dark/40">
                        {approval.comment || "—"}
                      </span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}

export default ApprovalCenterPage;
