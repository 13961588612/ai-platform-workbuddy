/**
 * ApprovalCard — HITL (Human-in-the-Loop) approval card component.
 *
 * Renders an interactive approval card when an agent requests human
 * approval before executing a sensitive operation. The card displays:
 * - Title and description of the requested action
 * - Skill ID that triggered the approval
 * - Approve / Reject buttons
 * - Optional comment field
 * - Status indicator (pending / approved / rejected / timeout)
 *
 * Aligns with the Gateway's BotEventMapper approval_card format
 * (button_interaction card) — the backend sends an approval.request
 * AgentEvent with a detail object containing title, description,
 * skillId, and approvalId.
 */

import { useCallback, useState } from "react";
import { useChatStore } from "../store/chatStore";
import { useApprovalStore } from "../store/approvalStore";
import { useChat } from "../hooks/useChat";
import { clsx } from "../utils/format";

// ===== Types =====

/** Props for the ApprovalCard component. */
interface ApprovalCardProps {
  /** Unique approval ID. */
  approvalId: string;
  /** Card title (from approval detail). */
  title: string;
  /** Card description (from approval detail). */
  description: string;
  /** Whether the approval is still pending. */
  isPending: boolean;
}

// ===== Component =====

/**
 * ApprovalCard — interactive approval request card.
 *
 * When an agent triggers an approval.request event, this card appears
 * inline in the message list. The user can approve or reject the
 * operation, optionally adding a comment.
 */
export function ApprovalCard({
  approvalId,
  title,
  description,
  isPending,
}: ApprovalCardProps): JSX.Element {
  const [comment, setComment] = useState("");
  const [showComment, setShowComment] = useState(false);
  const [responding, setResponding] = useState(false);

  const sessionId = useChatStore((state) => state.sessionId);
  const { respondApproval: respondViaStore } = useApprovalStore();
  const { respondToApproval: respondViaWs } = useChat(sessionId);

  // Handle approve
  const handleApprove = useCallback(async (): Promise<void> => {
    setResponding(true);
    // Send via WebSocket for real-time agent notification
    respondViaWs(approvalId, "approved", comment);
    // Also update via REST API for persistence
    await respondViaStore(approvalId, "approved", comment);
    setResponding(false);
  }, [approvalId, comment, respondViaWs, respondViaStore]);

  // Handle reject
  const handleReject = useCallback(async (): Promise<void> => {
    setResponding(true);
    respondViaWs(approvalId, "rejected", comment);
    await respondViaStore(approvalId, "rejected", comment);
    setResponding(false);
  }, [approvalId, comment, respondViaWs, respondViaStore]);

  // If not pending, show resolved status
  if (!isPending) {
    return (
      <div className="my-2 mx-auto max-w-[75%] rounded-lg border border-surface-light bg-surface-muted/30 p-3">
        <div className="flex items-center gap-2 text-sm text-surface-dark/50">
          <span className="text-base">✓</span>
          <span>审批已完成</span>
        </div>
      </div>
    );
  }

  return (
    <div className="my-2 mx-auto max-w-[75%] rounded-lg border-2 border-primary-200 bg-primary-50/50 p-4">
      {/* Header */}
      <div className="mb-3 flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary-600 text-xs text-white">
          !
        </span>
        <span className="text-sm font-semibold text-primary-700">
          需要审批
        </span>
      </div>

      {/* Title */}
      <h4 className="mb-1 text-sm font-medium text-surface-dark">
        {title || "操作审批请求"}
      </h4>

      {/* Description */}
      <p className="mb-3 text-xs text-surface-dark/60">
        {description || "Agent 需要您批准此操作才能继续执行。"}
      </p>

      {/* Approval ID */}
      <div className="mb-3 text-xs text-surface-dark/40">
        审批 ID: <code className="rounded bg-surface-muted px-1 py-0.5">{approvalId.slice(0, 12)}</code>
      </div>

      {/* Comment Toggle */}
      {!showComment && (
        <button
          type="button"
          onClick={() => setShowComment(true)}
          className="mb-3 text-xs text-primary-600 hover:text-primary-700 underline"
        >
          + 添加备注
        </button>
      )}

      {/* Comment Input */}
      {showComment && (
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="审批备注（可选）..."
          rows={2}
          className={clsx(
            "mb-3 w-full resize-none rounded-md border border-surface-light bg-white px-3 py-2 text-xs",
            "placeholder:text-surface-dark/30 focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400",
          )}
        />
      )}

      {/* Action Buttons */}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleApprove}
          disabled={responding}
          className={clsx(
            "flex-1 rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
            "bg-green-600 hover:bg-green-700",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {responding ? "处理中..." : "同意"}
        </button>
        <button
          type="button"
          onClick={handleReject}
          disabled={responding}
          className={clsx(
            "flex-1 rounded-md px-4 py-2 text-sm font-medium text-white transition-colors",
            "bg-red-600 hover:bg-red-700",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {responding ? "处理中..." : "拒绝"}
        </button>
      </div>

      {/* Timeout Notice */}
      <div className="mt-2 text-center text-xs text-surface-dark/30">
        5 分钟内未响应将自动超时
      </div>
    </div>
  );
}

export default ApprovalCard;
