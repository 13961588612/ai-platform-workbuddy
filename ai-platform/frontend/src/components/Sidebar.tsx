/**
 * Sidebar — Admin dashboard sidebar navigation.
 *
 * Provides navigation links to admin sub-pages:
 * - /admin/agents    — Agent 管理
 * - /admin/skills    — Skill 管理
 * - /admin/monitor   — 系统监控
 * - /admin/approvals — 审批中心
 * - /admin/users     — 用户权限 (future)
 *
 * Also shows the current user info and logout button at the bottom.
 */

import { useCallback } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { clsx } from "../utils/format";

// ===== Navigation Items =====

/** Sidebar navigation item definition. */
interface NavItem {
  /** Route path. */
  path: string;
  /** Display label (Chinese). */
  label: string;
  /** Icon (emoji for simplicity). */
  icon: string;
}

/** Admin sidebar navigation items. */
const NAV_ITEMS: NavItem[] = [
  { path: "/admin/agents", label: "Agent 管理", icon: "🤖" },
  { path: "/admin/skills", label: "Skill 管理", icon: "⚡" },
  { path: "/admin/monitor", label: "系统监控", icon: "📊" },
  { path: "/admin/approvals", label: "审批中心", icon: "✅" },
  { path: "/admin/users", label: "用户权限", icon: "👤" },
];

// ===== Component =====

/**
 * Sidebar — admin dashboard navigation sidebar.
 *
 * Renders the navigation links and user info section.
 * Active link is highlighted with primary color.
 */
export function Sidebar(): JSX.Element {
  const navigate = useNavigate();
  const { user, logout } = useAuthStore();

  // Handle logout
  const handleLogout = useCallback((): void => {
    logout();
    navigate("/login");
  }, [logout, navigate]);

  return (
    <aside className="flex h-full w-64 flex-col bg-surface-dark text-white">
      {/* Logo / Title */}
      <div className="flex items-center gap-3 border-b border-white/10 px-6 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary-600 text-xl">
          🤖
        </div>
        <div>
          <h1 className="text-lg font-bold">AI 平台</h1>
          <p className="text-xs text-white/50">管理后台</p>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {NAV_ITEMS.map((item: NavItem) => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }: { isActive: boolean }) =>
              clsx(
                "flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary-600 text-white"
                  : "text-white/70 hover:bg-white/10 hover:text-white",
              )
            }
          >
            <span className="text-lg">{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}

        {/* Divider */}
        <div className="my-4 border-t border-white/10" />

        {/* Chat Link */}
        <NavLink
          to="/chat"
          className={({ isActive }: { isActive: boolean }) =>
            clsx(
              "flex items-center gap-3 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors",
              isActive
                ? "bg-primary-600 text-white"
                : "text-white/70 hover:bg-white/10 hover:text-white",
            )
          }
        >
          <span className="text-lg">💬</span>
          <span>返回聊天</span>
        </NavLink>
      </nav>

      {/* User Info & Logout */}
      <div className="border-t border-white/10 px-4 py-4">
        <div className="mb-3 flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-white/10 text-sm font-medium">
            {user?.username?.charAt(0).toUpperCase() ?? "U"}
          </div>
          <div className="flex-1 overflow-hidden">
            <p className="truncate text-sm font-medium">
              {user?.username ?? "未知用户"}
            </p>
            <p className="truncate text-xs text-white/50">
              {user?.department ?? "未分配部门"}
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleLogout}
          className="w-full rounded-md border border-white/20 px-3 py-1.5 text-xs font-medium text-white/70 transition-colors hover:bg-white/10 hover:text-white"
        >
          退出登录
        </button>
      </div>
    </aside>
  );
}

export default Sidebar;
