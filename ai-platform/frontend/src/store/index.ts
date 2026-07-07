/**
 * Re-export all Zustand stores from a single entry point.
 *
 * Usage: import { useAuthStore, useChatStore, useApprovalStore } from "@/store";
 */

export { default as useAuthStore } from "./authStore";
export type { AuthUser } from "./authStore";

export { default as useChatStore } from "./chatStore";
export type { PendingApproval } from "./chatStore";

export { default as useApprovalStore } from "./approvalStore";
export type {
  ApprovalRecord,
  ApprovalStatus,
  ApprovalStats,
} from "./approvalStore";
