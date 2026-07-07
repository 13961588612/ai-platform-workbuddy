/**
 * Layout — Admin dashboard layout wrapper.
 *
 * Provides the overall page structure for admin pages:
 * - Left sidebar (navigation)
 * - Top header (page title, breadcrumb)
 * - Main content area (children)
 *
 * Includes an authentication guard — redirects to /login if not
 * authenticated.
 */

import React, { useEffect } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { useAuthStore } from "../store/authStore";

// ===== Types =====

/** Props for the Layout component. */
interface LayoutProps {
  /** Page title displayed in the header. */
  title: string;
  /** Optional breadcrumb items. */
  breadcrumbs?: string[];
  /** Page content. */
  children: React.ReactNode;
}

// ===== Component =====

/**
 * Layout — admin dashboard page wrapper with sidebar and header.
 *
 * Renders the Sidebar component and a content area with a header.
 * Redirects to /login if the user is not authenticated.
 */
export function Layout({
  title,
  breadcrumbs,
  children,
}: LayoutProps): JSX.Element {
  const location = useLocation();
  const { isAuthenticated, initialize } = useAuthStore();

  // Initialize auth state on mount
  useEffect(() => {
    initialize();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auth guard
  if (!isAuthenticated) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname }}
      />
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-surface-muted">
      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <header className="border-b border-surface-light/50 bg-white px-8 py-4">
          <h1 className="text-xl font-bold text-surface-dark">{title}</h1>
          {breadcrumbs && breadcrumbs.length > 0 && (
            <nav className="mt-1">
              <ol className="flex items-center gap-2 text-xs text-surface-dark/40">
                {breadcrumbs.map((crumb: string, index: number) => (
                  <li key={index} className="flex items-center gap-2">
                    {index > 0 && <span>/</span>}
                    <span>{crumb}</span>
                  </li>
                ))}
              </ol>
            </nav>
          )}
        </header>

        {/* Content Area */}
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </div>
    </div>
  );
}

export default Layout;
