/**
 * Route configuration constants.
 *
 * Centralizes all route paths to avoid hardcoding strings throughout
 * the application. Used by router.tsx, AppRoutes.tsx, and any
 * components that need to navigate programmatically.
 */

/** Route path constants. */
export const ROUTE_PATHS = {
  /** Login page. */
  LOGIN: "/login",
  /** Main chat interface. */
  CHAT: "/chat",
  /** Admin dashboard root (redirects to agents). */
  ADMIN: "/admin",
  /** Admin — Agent management. */
  ADMIN_AGENTS: "/admin/agents",
  /** Admin — Skill management. */
  ADMIN_SKILLS: "/admin/skills",
  /** Admin — System monitoring. */
  ADMIN_MONITOR: "/admin/monitor",
  /** Admin — Approval center. */
  ADMIN_APPROVALS: "/admin/approvals",
  /** Admin — User permission management. */
  ADMIN_USERS: "/admin/users",
  /** Root path (redirects to /chat). */
  ROOT: "/",
  /** Fallback for unknown routes. */
  FALLBACK: "*",
} as const;

/** Admin navigation items for sidebar. */
export const ADMIN_NAV_ITEMS = [
  { path: ROUTE_PATHS.ADMIN_AGENTS, label: "Agent 管理", icon: "🤖" },
  { path: ROUTE_PATHS.ADMIN_SKILLS, label: "Skill 管理", icon: "⚡" },
  { path: ROUTE_PATHS.ADMIN_MONITOR, label: "系统监控", icon: "📊" },
  { path: ROUTE_PATHS.ADMIN_APPROVALS, label: "审批中心", icon: "✅" },
  { path: ROUTE_PATHS.ADMIN_USERS, label: "用户权限", icon: "👤" },
] as const;

/** Type for route path values. */
export type RoutePath = (typeof ROUTE_PATHS)[keyof typeof ROUTE_PATHS];
