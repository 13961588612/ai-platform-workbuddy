/**
 * Router — Main route configuration for the application.
 *
 * Uses React Router v6 Routes API to define the complete route tree.
 * Includes an authentication guard wrapper that redirects unauthenticated
 * users to the login page.
 */

import { Routes, Route, Navigate } from "react-router-dom";
import { ROUTE_PATHS } from "./routeConfig";
import { getRouteDefinitions } from "./AppRoutes";
import { useAuthStore } from "../store/authStore";

// ===== Auth Guard =====

/**
 * Wrap a route element with an authentication check.
 * If the user is not authenticated, redirect to /login.
 */
function RequireAuth({ children }: { children: JSX.Element }): JSX.Element {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);

  if (!isAuthenticated) {
    return (
      <Navigate
        to={ROUTE_PATHS.LOGIN}
        replace
        state={{ from: window.location.pathname }}
      />
    );
  }

  return children;
}

// ===== Router Component =====

/**
 * Router — renders all application routes.
 *
 * Public routes (login, root redirect, fallback) are rendered directly.
 * Protected routes are wrapped in <RequireAuth> to enforce authentication.
 */
export function Router(): JSX.Element {
  const routes = getRouteDefinitions();

  return (
    <Routes>
      {routes.map((route) => {
        if (route.isPublic) {
          return (
            <Route
              key={route.path}
              path={route.path}
              element={route.element}
            />
          );
        }
        return (
          <Route
            key={route.path}
            path={route.path}
            element={<RequireAuth>{route.element}</RequireAuth>}
          />
        );
      })}
    </Routes>
  );
}

export default Router;
