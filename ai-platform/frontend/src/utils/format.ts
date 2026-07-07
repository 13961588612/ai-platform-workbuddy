/**
 * Formatting utility functions for the frontend.
 *
 * Provides helpers for date/time formatting, number formatting,
 * text truncation, and status label/color mapping.
 * Uses dayjs for consistent date handling.
 */

import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import "dayjs/locale/zh-cn";
import clsx from "clsx";
import type { AgentState } from "../types/agent";
import type { SkillStatus } from "../types/skill";

// Initialize dayjs plugins and locale
dayjs.extend(relativeTime);
dayjs.locale("zh-cn");

// ===== Date / Time Formatting =====

/**
 * Format an ISO date string to a readable date-time string.
 * @example formatDateTime("2024-01-15T10:30:00Z") → "2024-01-15 10:30:00"
 */
export function formatDateTime(
  isoString: string | null | undefined,
): string {
  if (!isoString) {
    return "—";
  }
  return dayjs(isoString).format("YYYY-MM-DD HH:mm:ss");
}

/**
 * Format an ISO date string to a short date string.
 * @example formatDate("2024-01-15T10:30:00Z") → "2024-01-15"
 */
export function formatDate(isoString: string | null | undefined): string {
  if (!isoString) {
    return "—";
  }
  return dayjs(isoString).format("YYYY-MM-DD");
}

/**
 * Format an ISO date string to a relative time string (Chinese).
 * @example formatRelativeTime("2024-01-15T10:30:00Z") → "3小时前"
 */
export function formatRelativeTime(
  isoString: string | null | undefined,
): string {
  if (!isoString) {
    return "—";
  }
  return dayjs(isoString).fromNow();
}

/**
 * Format a timestamp to time only.
 * @example formatTime("2024-01-15T10:30:00Z") → "10:30"
 */
export function formatTime(isoString: string | null | undefined): string {
  if (!isoString) {
    return "—";
  }
  return dayjs(isoString).format("HH:mm");
}

// ===== Number Formatting =====

/**
 * Format a number with thousands separators.
 * @example formatNumber(1234567) → "1,234,567"
 */
export function formatNumber(value: number | undefined | null): string {
  if (value === undefined || value === null) {
    return "—";
  }
  return value.toLocaleString("en-US");
}

/**
 * Format a token count with compact notation for large numbers.
 * @example formatTokenCount(1500) → "1.5k"
 * @example formatTokenCount(1500000) → "1.5M"
 */
export function formatTokenCount(value: number | undefined | null): string {
  if (value === undefined || value === null) {
    return "—";
  }
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(1)}k`;
  }
  return String(value);
}

/**
 * Format a percentage value.
 * @example formatPercent(85.5) → "85.5%"
 */
export function formatPercent(value: number | undefined | null): string {
  if (value === undefined || value === null) {
    return "—";
  }
  return `${value.toFixed(1)}%`;
}

// ===== Text Formatting =====

/**
 * Truncate text to a maximum length, appending an ellipsis if truncated.
 * @example truncateText("Hello World", 5) → "Hello…"
 */
export function truncateText(
  text: string | undefined | null,
  maxLength: number = 50,
): string {
  if (!text) {
    return "";
  }
  if (text.length <= maxLength) {
    return text;
  }
  return text.slice(0, maxLength) + "…";
}

// ===== Status Labels & Colors =====

/** Agent state display labels (Chinese). */
const AGENT_STATE_LABELS: Record<AgentState, string> = {
  created: "已创建",
  starting: "启动中",
  running: "运行中",
  paused: "已暂停",
  stopping: "停止中",
  stopped: "已停止",
  error: "异常",
};

/** Agent state badge color classes (Tailwind). */
const AGENT_STATE_COLORS: Record<AgentState, string> = {
  created: "bg-gray-100 text-gray-700",
  starting: "bg-blue-100 text-blue-700",
  running: "bg-green-100 text-green-700",
  paused: "bg-yellow-100 text-yellow-700",
  stopping: "bg-orange-100 text-orange-700",
  stopped: "bg-gray-100 text-gray-700",
  error: "bg-red-100 text-red-700",
};

/**
 * Get the display label for an Agent state.
 */
export function getAgentStateLabel(state: AgentState): string {
  return AGENT_STATE_LABELS[state] ?? state;
}

/**
 * Get the badge CSS classes for an Agent state.
 */
export function getAgentStateColor(state: AgentState): string {
  return AGENT_STATE_COLORS[state] ?? "bg-gray-100 text-gray-700";
}

/** Skill status display labels (Chinese). */
const SKILL_STATUS_LABELS: Record<SkillStatus, string> = {
  active: "启用",
  inactive: "停用",
  deprecated: "已废弃",
};

/** Skill status badge color classes (Tailwind). */
const SKILL_STATUS_COLORS: Record<SkillStatus, string> = {
  active: "bg-green-100 text-green-700",
  inactive: "bg-gray-100 text-gray-700",
  deprecated: "bg-red-100 text-red-700",
};

/**
 * Get the display label for a Skill status.
 */
export function getSkillStatusLabel(status: SkillStatus): string {
  return SKILL_STATUS_LABELS[status] ?? status;
}

/**
 * Get the badge CSS classes for a Skill status.
 */
export function getSkillStatusColor(status: SkillStatus): string {
  return SKILL_STATUS_COLORS[status] ?? "bg-gray-100 text-gray-700";
}

// ===== Category Labels =====

/** Skill category display labels (Chinese). */
const CATEGORY_LABELS: Record<string, string> = {
  finance: "财务",
  retail: "零售",
  department_store: "百货",
  hr: "人力资源",
  property: "物业",
  crm: "CRM",
  valuecard: "储值卡",
  built_in: "内置",
};

/**
 * Get the display label for a Skill category.
 */
export function getCategoryLabel(category: string): string {
  return CATEGORY_LABELS[category] ?? category;
}

// ===== Class Name Helper =====

/**
 * Merge class names using clsx for conditional styling.
 * Re-exported for convenience.
 */
export { clsx };
