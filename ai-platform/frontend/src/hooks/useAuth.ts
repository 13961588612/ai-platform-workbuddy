/**
 * useAuth — Authentication hook.
 *
 * Wraps the authStore to provide a convenient interface for components.
 * Handles:
 * - Checking authentication status on mount
 * - Login / logout operations
 * - Redirecting to login page when unauthenticated
 * - Providing current user info to consumers
 */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuthStore } from "../store/authStore";

// ===== Hook Return Type =====

/** Return type of the useAuth hook. */
interface UseAuthReturn {
  /** Current authenticated user (null if not logged in). */
  user: ReturnType<typeof useAuthStore.getState>["user"];
  /** Whether the user is authenticated. */
  isAuthenticated: boolean;
  /** Whether an auth operation is in progress. */
  isLoading: boolean;
  /** Error message from the last auth operation. */
  error: string | null;
  /** Login with username/password. */
  login: (username: string, password: string) => Promise<boolean>;
  /** Login with Enterprise WeChat OAuth2 code. */
  loginWithWecom: (code: string, state?: string) => Promise<boolean>;
  /** Logout and redirect to login. */
  logout: () => void;
  /** Clear the error state. */
  clearError: () => void;
}

// ===== Hook =====

/**
 * Authentication hook — provides auth state and actions.
 *
 * On mount, initializes the auth store from stored tokens.
 * Components should use this hook to access user info and
 * perform login/logout operations.
 */
export function useAuth(): UseAuthReturn {
  const navigate = useNavigate();
  const {
    user,
    isAuthenticated,
    isLoading,
    error,
    login: storeLogin,
    loginWithWecom: storeLoginWithWecom,
    logout: storeLogout,
    initialize,
    clearError,
  } = useAuthStore();

  const [initialized, setInitialized] = useState(false);

  // Initialize auth state from stored tokens on mount
  useEffect(() => {
    if (!initialized) {
      initialize();
      setInitialized(true);
    }
  }, [initialize, initialized]);

  // Login with username/password
  const login = useCallback(
    async (username: string, password: string): Promise<boolean> => {
      const success = await storeLogin(username, password);
      if (success) {
        navigate("/chat");
      }
      return success;
    },
    [storeLogin, navigate],
  );

  // Login with Enterprise WeChat OAuth2 code
  const loginWithWecom = useCallback(
    async (code: string, state?: string): Promise<boolean> => {
      const success = await storeLoginWithWecom(code, state);
      if (success) {
        navigate("/chat");
      }
      return success;
    },
    [storeLoginWithWecom, navigate],
  );

  // Logout and redirect
  const logout = useCallback(() => {
    storeLogout();
    navigate("/login");
  }, [storeLogout, navigate]);

  return {
    user,
    isAuthenticated,
    isLoading,
    error,
    login,
    loginWithWecom,
    logout,
    clearError,
  };
}

export default useAuth;
