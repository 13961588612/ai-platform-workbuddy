/**
 * Axios HTTP client instance and API helper functions.
 *
 * Provides a pre-configured axios instance with:
 * - Base URL from environment variable (defaults to /api/v1)
 * - JWT Authorization header injection via request interceptor
 * - Automatic token refresh on 401 responses
 * - Unified ApiResponse<T> unwrapping
 * - Trace ID propagation
 */

import axios, {
  AxiosError,
  AxiosInstance,
  AxiosRequestConfig,
  AxiosResponse,
  InternalAxiosRequestConfig,
} from "axios";
import type { ApiResponse } from "../types/message";

// ===== Configuration =====

const API_BASE_URL: string =
  (import.meta as unknown as { env: Record<string, string> }).env
    ?.VITE_API_BASE_URL ?? "/api/v1";

const TOKEN_STORAGE_KEY = "ai_platform_access_token";
const REFRESH_TOKEN_STORAGE_KEY = "ai_platform_refresh_token";

// ===== Token Storage Helpers =====

/** Retrieve the access token from localStorage. */
export function getAccessToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

/** Store the access token in localStorage. */
export function setAccessToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

/** Retrieve the refresh token from localStorage. */
export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_STORAGE_KEY);
}

/** Store the refresh token in localStorage. */
export function setRefreshToken(token: string): void {
  localStorage.setItem(REFRESH_TOKEN_STORAGE_KEY, token);
}

/** Clear all stored tokens. */
export function clearTokens(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  localStorage.removeItem(REFRESH_TOKEN_STORAGE_KEY);
}

// ===== Axios Instance =====

/** Pre-configured axios instance with auth interceptors. */
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    "Content-Type": "application/json",
  },
});

// ===== Request Interceptor: Inject JWT =====

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig): InternalAxiosRequestConfig => {
    const token = getAccessToken();
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    // Generate trace ID for request correlation
    const traceId = `fe-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    if (config.headers) {
      config.headers["X-Trace-Id"] = traceId;
    }
    return config;
  },
  (error: AxiosError): Promise<AxiosError> => {
    return Promise.reject(error);
  },
);

// ===== Response Interceptor: Unwrap ApiResponse + Handle 401 =====

let isRefreshing = false;
let refreshPromise: Promise<string | null> | null = null;

/** Attempt to refresh the access token using the refresh token. */
async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    clearTokens();
    return null;
  }
  try {
    const response = await axios.post<ApiResponse<{ access_token: string }>>(
      `${API_BASE_URL}/auth/refresh`,
      { refresh_token: refreshToken },
      { timeout: 10000 },
    );
    if (response.data.code === 0 && response.data.data?.access_token) {
      const newToken = response.data.data.access_token;
      setAccessToken(newToken);
      return newToken;
    }
  } catch {
    // Refresh failed — clear tokens and redirect to login
    clearTokens();
  }
  return null;
}

apiClient.interceptors.response.use(
  (response: AxiosResponse): AxiosResponse => {
    return response;
  },
  async (error: AxiosError<ApiResponse>): Promise<unknown> => {
    const originalRequest = error.config as InternalAxiosRequestConfig & {
      _retry?: boolean;
    };

    // Handle 401 — attempt token refresh
    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !originalRequest.url?.includes("/auth/")
    ) {
      originalRequest._retry = true;

      if (!isRefreshing) {
        isRefreshing = true;
        refreshPromise = refreshAccessToken().finally(() => {
          isRefreshing = false;
        });
      }

      const newToken = await refreshPromise;
      if (newToken) {
        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${newToken}`;
        }
        return apiClient(originalRequest);
      }

      // Refresh failed — redirect to login
      clearTokens();
      window.location.href = "/login";
      return Promise.reject(error);
    }

    return Promise.reject(error);
  },
);

// ===== API Helper Functions =====

/**
 * Perform a GET request and unwrap the ApiResponse data.
 * @throws Error with message from ApiResponse if code !== 0.
 */
export async function apiGet<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.get<ApiResponse<T>>(url, config);
  if (response.data.code !== 0) {
    throw new ApiError(
      response.data.message || "API request failed",
      response.data.code,
      response.data.traceId,
    );
  }
  return response.data.data as T;
}

/**
 * Perform a POST request and unwrap the ApiResponse data.
 * @throws Error with message from ApiResponse if code !== 0.
 */
export async function apiPost<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.post<ApiResponse<T>>(url, data, config);
  if (response.data.code !== 0) {
    throw new ApiError(
      response.data.message || "API request failed",
      response.data.code,
      response.data.traceId,
    );
  }
  return response.data.data as T;
}

/**
 * Perform a PUT request and unwrap the ApiResponse data.
 * @throws Error with message from ApiResponse if code !== 0.
 */
export async function apiPut<T>(
  url: string,
  data?: unknown,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.put<ApiResponse<T>>(url, data, config);
  if (response.data.code !== 0) {
    throw new ApiError(
      response.data.message || "API request failed",
      response.data.code,
      response.data.traceId,
    );
  }
  return response.data.data as T;
}

/**
 * Perform a DELETE request and unwrap the ApiResponse data.
 * @throws Error with message from ApiResponse if code !== 0.
 */
export async function apiDelete<T>(
  url: string,
  config?: AxiosRequestConfig,
): Promise<T> {
  const response = await apiClient.delete<ApiResponse<T>>(url, config);
  if (response.data.code !== 0) {
    throw new ApiError(
      response.data.message || "API request failed",
      response.data.code,
      response.data.traceId,
    );
  }
  return response.data.data as T;
}

// ===== Custom API Error =====

/** Error thrown when an API response has a non-zero code. */
export class ApiError extends Error {
  /** Error code from the API response. */
  readonly code: number;
  /** Trace ID for correlation. */
  readonly traceId: string;

  constructor(message: string, code: number, traceId: string = "") {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.traceId = traceId;
  }
}

// ===== WebSocket URL Helper =====

/** Build the WebSocket URL for the chat endpoint. */
export function getChatWsUrl(sessionId: string, userId: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  const token = getAccessToken();
  const params = new URLSearchParams({
    sessionId,
    userId,
  });
  if (token) {
    params.set("token", token);
  }
  return `${protocol}//${host}/ws/chat?${params.toString()}`;
}

export { apiClient };
export default apiClient;
