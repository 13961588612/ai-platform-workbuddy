/**
 * LoginPage — User login page.
 *
 * Provides:
 * - Username / password login form
 * - Enterprise WeChat (企业微信) OAuth2 login button
 * - Error display
 * - Redirect to chat on success
 *
 * Backend endpoints:
 * - POST /api/v1/auth/login         — password login
 * - POST /api/v1/auth/wecom/callback — WeChat OAuth2 callback
 */

import React, { useCallback, useState, useEffect } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuthStore } from "../store/authStore";
import { clsx } from "../utils/format";

// ===== Component =====

/**
 * LoginPage — authentication entry point.
 *
 * Supports both password-based login and Enterprise WeChat OAuth2 login.
 * On successful login, redirects to the originally requested page or /chat.
 */
export function LoginPage(): JSX.Element {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, loginWithWecom, isLoading, error, clearError } =
    useAuthStore();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  // Get redirect target from location state
  const fromPath: string =
    (location.state as { from?: string })?.from ?? "/chat";

  // ===== Handle Password Login =====
  const handleLogin = useCallback(
    async (e: React.FormEvent): Promise<void> => {
      e.preventDefault();
      if (!username.trim() || !password.trim()) {
        return;
      }
      const success = await login(username, password);
      if (success) {
        navigate(fromPath, { replace: true });
      }
    },
    [username, password, login, navigate, fromPath],
  );

  // ===== Handle WeChat Login =====
  const handleWecomLogin = useCallback((): void => {
    // Redirect to WeChat OAuth2 authorization URL
    // The callback will be handled by the /auth/wecom/callback endpoint
    const corpId =
      (import.meta as unknown as { env: Record<string, string> }).env
        ?.VITE_WECOM_CORP_ID ?? "";
    const redirectUri = encodeURIComponent(
      `${window.location.origin}/auth/wecom/callback`,
    );
    const state = `ai-platform-${Date.now()}`;
    const oauthUrl = `https://open.weixin.qq.com/connect/oauth2/authorize?appid=${corpId}&redirect_uri=${redirectUri}&response_type=code&scope=snsapi_base&state=${state}#wechat_redirect`;
    window.location.href = oauthUrl;
  }, []);

  // ===== Handle WeChat OAuth2 callback (if code is in URL) =====
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get("code");
    const state = params.get("state");
    if (code) {
      loginWithWecom(code, state ?? "").then((success: boolean) => {
        if (success) {
          navigate(fromPath, { replace: true });
        }
      });
    }
  }, [loginWithWecom, navigate, fromPath]);

  // ===== Clear error on input change =====
  useEffect(() => {
    if (error) {
      clearError();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username, password]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-primary-50 to-surface-muted">
      <div className="w-full max-w-md">
        {/* Logo */}
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-primary-600 text-3xl shadow-lg">
            🤖
          </div>
          <h1 className="text-2xl font-bold text-surface-dark">AI 智能平台</h1>
          <p className="mt-1 text-sm text-surface-dark/50">
            企业内部 AI 助手与管理平台
          </p>
        </div>

        {/* Login Card */}
        <div className="rounded-2xl bg-white p-8 shadow-xl">
          {/* Error Message */}
          {error && (
            <div className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {/* Login Form */}
          <form onSubmit={handleLogin} className="space-y-4">
            <div>
              <label
                htmlFor="username"
                className="mb-1 block text-sm font-medium text-surface-dark/70"
              >
                用户名
              </label>
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                autoComplete="username"
                className={clsx(
                  "w-full rounded-lg border border-surface-light bg-surface-muted/50 px-4 py-2.5 text-sm",
                  "placeholder:text-surface-dark/30",
                  "focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400",
                )}
                disabled={isLoading}
              />
            </div>

            <div>
              <label
                htmlFor="password"
                className="mb-1 block text-sm font-medium text-surface-dark/70"
              >
                密码
              </label>
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                autoComplete="current-password"
                className={clsx(
                  "w-full rounded-lg border border-surface-light bg-surface-muted/50 px-4 py-2.5 text-sm",
                  "placeholder:text-surface-dark/30",
                  "focus:outline-none focus:border-primary-400 focus:ring-1 focus:ring-primary-400",
                )}
                disabled={isLoading}
              />
            </div>

            <button
              type="submit"
              disabled={isLoading || !username.trim() || !password.trim()}
              className={clsx(
                "w-full rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-medium text-white",
                "hover:bg-primary-700 transition-colors",
                "disabled:cursor-not-allowed disabled:opacity-50",
              )}
            >
              {isLoading ? "登录中..." : "登录"}
            </button>
          </form>

          {/* Divider */}
          <div className="my-6 flex items-center">
            <div className="flex-1 border-t border-surface-light" />
            <span className="px-4 text-xs text-surface-dark/40">或</span>
            <div className="flex-1 border-t border-surface-light" />
          </div>

          {/* WeChat Login */}
          <button
            type="button"
            onClick={handleWecomLogin}
            disabled={isLoading}
            className={clsx(
              "flex w-full items-center justify-center gap-2 rounded-lg border border-green-300 bg-green-50 px-4 py-2.5 text-sm font-medium text-green-700",
              "hover:bg-green-100 transition-colors",
              "disabled:cursor-not-allowed disabled:opacity-50",
            )}
          >
            <svg
              className="h-5 w-5"
              viewBox="0 0 24 24"
              fill="currentColor"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path d="M8.691 2.188C3.891 2.188 0 5.476 0 9.53c0 2.212 1.17 4.203 3.002 5.55a.59.59 0 0 1 .213.665l-.39 1.48c-.019.07-.048.141-.048.213 0 .163.13.295.29.295a.328.328 0 0 0 .167-.054l1.903-1.114a.864.864 0 0 1 .717-.098 10.16 10.16 0 0 0 2.837.403c.276 0 .543-.027.81-.05-.857-2.578.157-4.972 1.744-6.426 1.634-1.5 4.476-2.067 6.695-1.31-.39-3.646-4.057-6.496-8.65-6.496zM5.785 5.991c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178A1.17 1.17 0 0 1 4.623 7.17c0-.651.52-1.18 1.162-1.18zm5.813 0c.642 0 1.162.529 1.162 1.18a1.17 1.17 0 0 1-1.162 1.178 1.17 1.17 0 0 1-1.162-1.178c0-.651.52-1.18 1.162-1.18zm5.34 4.398c-3.84 0-6.96 2.59-6.96 5.785 0 3.196 3.12 5.786 6.96 5.786.81 0 1.589-.12 2.318-.336a.722.722 0 0 1 .598.082l1.584.926a.272.272 0 0 0 .14.047c.134 0 .24-.111.24-.247 0-.06-.023-.12-.038-.177l-.327-1.233a.49.49 0 0 1 .178-.554C24.028 19.086 25 17.438 25 15.626c0-3.15-3.12-5.74-6.96-5.74zm-2.828 3.126c.534 0 .968.44.968.983a.976.976 0 0 1-.968.983.976.976 0 0 1-.968-.983c0-.544.434-.983.968-.983zm5.106 0c.534 0 .968.44.968.983a.976.976 0 0 1-.968.983.976.976 0 0 1-.968-.983c0-.544.434-.983.968-.983z" />
            </svg>
            企业微信登录
          </button>
        </div>

        {/* Footer */}
        <p className="mt-6 text-center text-xs text-surface-dark/30">
          © 2024 AI 智能平台 · 仅供内部使用
        </p>
      </div>
    </div>
  );
}

export default LoginPage;
