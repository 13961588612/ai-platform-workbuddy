/**
 * AppRoutes — Route component definitions.
 *
 * Defines the React Router route tree using the route configuration
 * constants. Each route maps a path to a lazy-loaded page component.
 *
 * Route structure:
 * - /login              → LoginPage (public)
 * - /chat               → ChatPage (protected)
 * - /admin/agents       → AgentManagePage (protected) [T06]
 * - /admin/skills       → SkillManagePage (protected)
 * - /admin/monitor      → MonitorPage (protected)
 * - /admin/approvals    → ApprovalCenterPage (protected)
 * - /admin/users        → UserPermissionPage (protected) [T06]
 * - /                   → redirect to /chat
 * - *                   → redirect to /chat
 */

import React, { lazy, Suspense } from "react";
import { Navigate } from "react-router-dom";
import { ROUTE_PATHS } from "./routeConfig";

// ===== Lazy-loaded Pages =====

const LoginPage = lazy(() => import("../pages/LoginPage"));
const ChatPage = lazy(() => import("../pages/ChatPage"));
const SkillManagePage = lazy(() => import("../pages/SkillManagePage"));
const MonitorPage = lazy(() => import("../pages/MonitorPage"));
const ApprovalCenterPage = lazy(() => import("../pages/ApprovalCenterPage"));

// ===== Loading Fallback =====

/** Loading spinner shown while lazy-loaded pages are being fetched. */
function PageLoading(): JSX.Element {
  return (
    <div className="flex h-screen items-center justify-center bg-surface-muted">
      <div className="text-center">
        <div className="mx-auto mb-4 h-8 w-8 animate-spin rounded-full border-4 border-primary-200 border-t-primary-600" />
        <p className="text-sm text-surface-dark/50">页面加载中...</p>
      </div>
    </div>
  );
}

// ===== Route Element Wrappers =====

/** Wrap a page component with Suspense for lazy loading. */
function withSuspense(
  Component: React.LazyExoticComponent<React.ComponentType>,
): JSX.Element {
  return (
    <Suspense fallback={<PageLoading />}>
      <Component />
    </Suspense>
  );
}

// ===== Route Definitions =====

/**
 * Build the route elements array for use in a <Routes> component.
 *
 * Returns an array of React elements suitable for nesting inside
 * <Routes> from react-router-dom.
 */
export function buildRouteElements(): React.ReactNode {
  return (
    <>
      {/* Public routes */}
      <React.Fragment key={ROUTE_PATHS.LOGIN}>
        {null /* Handled in AppRoutes */}
      </React.Fragment>

      {/* Protected routes — Chat */}
      <React.Fragment key={ROUTE_PATHS.CHAT}>
        {null /* Handled in AppRoutes */}
      </React.Fragment>
    </>
  );
}

// ===== Route Config Array =====

/** Route definition for programmatic use. */
export interface RouteDef {
  path: string;
  element: JSX.Element;
  isPublic: boolean;
}

/**
 * Get all route definitions as an array.
 * Used by AppRoutes to render <Route> elements.
 */
export function getRouteDefinitions(): RouteDef[] {
  return [
    {
      path: ROUTE_PATHS.LOGIN,
      element: withSuspense(LoginPage),
      isPublic: true,
    },
    {
      path: ROUTE_PATHS.CHAT,
      element: withSuspense(ChatPage),
      isPublic: false,
    },
    {
      path: ROUTE_PATHS.ADMIN_SKILLS,
      element: withSuspense(SkillManagePage),
      isPublic: false,
    },
    {
      path: ROUTE_PATHS.ADMIN_MONITOR,
      element: withSuspense(MonitorPage),
      isPublic: false,
    },
    {
      path: ROUTE_PATHS.ADMIN_APPROVALS,
      element: withSuspense(ApprovalCenterPage),
      isPublic: false,
    },
    // Admin agents and users pages are implemented by T06 teammate
    // For now, redirect to skills management
    {
      path: ROUTE_PATHS.ADMIN_AGENTS,
      element: <Navigate to={ROUTE_PATHS.ADMIN_SKILLS} replace />,
      isPublic: false,
    },
    {
      path: ROUTE_PATHS.ADMIN_USERS,
      element: <Navigate to={ROUTE_PATHS.ADMIN_SKILLS} replace />,
      isPublic: false,
    },
    {
      path: ROUTE_PATHS.ADMIN,
      element: <Navigate to={ROUTE_PATHS.ADMIN_AGENTS} replace />,
      isPublic: false,
    },
    {
      path: ROUTE_PATHS.ROOT,
      element: <Navigate to={ROUTE_PATHS.CHAT} replace />,
      isPublic: true,
    },
    {
      path: ROUTE_PATHS.FALLBACK,
      element: <Navigate to={ROUTE_PATHS.CHAT} replace />,
      isPublic: true,
    },
  ];
}

export default getRouteDefinitions;
