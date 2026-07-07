/**
 * Authentication Store (Zustand).
 *
 * Manages user authentication state including:
 * - Current user info (user_id, username, department, roles)
 * - Access/refresh tokens (persisted to localStorage via api.ts helpers)
 * - Login / logout / token refresh actions
 * - Authentication status flags
 *
 * Aligns with backend identity/models.py:
 * - TokenPayload: user_id, username, department, roles, channel, agent_id
 * - TokenSet: access_token, refresh_token, token_type, expires_in
 */

import { create } from "zustand";
import {
  apiPost,
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from "../utils/api";

// ===== Types =====

/** Current authenticated user info (decoded from JWT payload). */
export interface AuthUser {
  userId: string;
  username: string;
  department: string;
  roles: string[];
  channel: string;
  agentId: string | null;
}

/** Authentication state shape. */
interface AuthState {
  /** Current authenticated user (null if not logged in). */
  user: AuthUser | null;
  /** Whether the user is authenticated. */
  isAuthenticated: boolean;
  /** Whether an auth operation is in progress. */
  isLoading: boolean;
  /** Error message from the last auth operation. */
  error: string | null;

  // Actions
  /** Login with username/password. */
  login: (username: string, password: string) => Promise<boolean>;
  /** Login with Enterprise WeChat OAuth2 code. */
  loginWithWecom: (code: string, state?: string) => Promise<boolean>;
  /** Logout and clear all tokens. */
  logout: () => void;
  /** Initialize auth state from stored tokens (call on app start). */
  initialize: () => void;
  /** Clear the error state. */
  clearError: () => void;
}

// ===== JWT Decode Helper =====

/**
 * Decode a JWT payload without verification (frontend only).
 * The backend verifies the signature; here we just extract claims.
 */
function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const parts = token.split(".");
    if (parts.length !== 3) {
      return null;
    }
    const payload = parts[1];
    // Add padding for base64 decoding
    const padded = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = atob(padded);
    return JSON.parse(decoded) as Record<string, unknown>;
  } catch {
    return null;
  }
}

/**
 * Build an AuthUser from a decoded JWT payload.
 */
function buildAuthUser(payload: Record<string, unknown>): AuthUser {
  return {
    userId:
      (payload.userId as string) ??
      (payload.user_id as string) ??
      "",
    username: (payload.username as string) ?? "",
    department: (payload.department as string) ?? "",
    roles: (payload.roles as string[]) ?? [],
    channel: (payload.channel as string) ?? "wecom_h5",
    agentId: (payload.agent_id as string) ?? (payload.agentId as string) ?? null,
  };
}

// ===== Store =====

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: false,
  isLoading: false,
  error: null,

  login: async (username: string, password: string): Promise<boolean> => {
    set({ isLoading: true, error: null });
    try {
      const response = await apiPost<{
        access_token: string;
        refresh_token: string;
        token_type: string;
        expires_in: number;
        user?: {
          user_id: string;
          username: string;
          display_name?: string;
          department?: string;
          roles?: string[];
          channel?: string;
        };
      }>("/auth/login", { username, password });

      setAccessToken(response.access_token);
      setRefreshToken(response.refresh_token);

      const payload = decodeJwtPayload(response.access_token);
      const userFromToken = payload ? buildAuthUser(payload) : null;
      const userFromResponse = response.user
        ? {
            userId: response.user.user_id,
            username: response.user.username,
            department: response.user.department ?? "",
            roles: response.user.roles ?? [],
            channel: response.user.channel ?? "web",
            agentId: null as string | null,
          }
        : null;
      const user = userFromResponse ?? userFromToken;

      set({
        user,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      });
      return true;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "登录失败，请稍后重试";
      set({ isLoading: false, error: message, isAuthenticated: false });
      return false;
    }
  },

  loginWithWecom: async (code: string, state?: string): Promise<boolean> => {
    set({ isLoading: true, error: null });
    try {
      const response = await apiPost<{
        access_token: string;
        refresh_token: string;
        token_type: string;
        expires_in: number;
      }>("/auth/wecom/callback", { code, state: state ?? "" });

      setAccessToken(response.access_token);
      setRefreshToken(response.refresh_token);

      const payload = decodeJwtPayload(response.access_token);
      const user = payload ? buildAuthUser(payload) : null;

      set({
        user,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      });
      return true;
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "企业微信登录失败，请稍后重试";
      set({ isLoading: false, error: message, isAuthenticated: false });
      return false;
    }
  },

  logout: () => {
    clearTokens();
    set({ user: null, isAuthenticated: false, error: null });
  },

  initialize: () => {
    const token = getAccessToken();
    if (!token) {
      set({ user: null, isAuthenticated: false });
      return;
    }

    const payload = decodeJwtPayload(token);
    if (!payload) {
      clearTokens();
      set({ user: null, isAuthenticated: false });
      return;
    }

    // Check token expiration
    const exp = payload.exp as number | undefined;
    if (exp && Date.now() >= exp * 1000) {
      // Token expired — check if we have a refresh token
      const refreshToken = getRefreshToken();
      if (!refreshToken) {
        clearTokens();
        set({ user: null, isAuthenticated: false });
        return;
      }
      // Token refresh will be handled by the axios interceptor on next request
    }

    const user = buildAuthUser(payload);
    set({ user, isAuthenticated: true });
  },

  clearError: () => {
    set({ error: null });
  },
}));

export default useAuthStore;
