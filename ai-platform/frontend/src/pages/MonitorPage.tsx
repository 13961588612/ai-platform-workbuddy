/**
 * MonitorPage — System monitoring dashboard.
 *
 * Displays real-time system health and performance metrics:
 * - System health overview (PostgreSQL, Redis, Qdrant)
 * - Routing decision logs and statistics
 * - LLM Gateway status (primary/fallback provider, failover)
 * - Token usage summary and quota info
 * - Outbound proxy status
 *
 * Backend endpoints (from admin.py route):
 * - GET /api/v1/admin/health              — system health
 * - GET /api/v1/admin/route-stats         — routing statistics
 * - GET /api/v1/admin/llm/status          — LLM gateway status
 * - GET /api/v1/admin/llm/token-usage     — token usage summary
 * - GET /api/v1/admin/proxy/status        — proxy status
 * - GET /api/v1/admin/configs             — agent configs overview
 */

import { useCallback, useEffect, useState } from "react";
import { Layout } from "../components/Layout";
import { apiGet } from "../utils/api";
import {
  formatNumber,
  formatTokenCount,
  formatPercent,
  formatDateTime,
  clsx,
} from "../utils/format";

// ===== Types =====

/** System health check result. */
interface HealthData {
  status: string;
  checks: Record<string, string>;
}

/** Routing statistics. */
interface RouteStats {
  total_requests: number;
  successful_routes: number;
  failed_routes: number;
  by_agent?: Record<string, number>;
  by_channel?: Record<string, number>;
}

/** LLM Gateway status. */
interface LlmStatus {
  primary_provider: string;
  fallback_provider: string;
  current_provider: string;
  failover_active: boolean;
  total_requests: number;
  error_count: number;
}

/** Token usage summary. */
interface TokenUsageSummary {
  total_prompt: number;
  total_completion: number;
  total_tokens: number;
  by_user?: Record<string, number>;
  by_model?: Record<string, number>;
}

/** Proxy status. */
interface ProxyStatus {
  enabled: boolean;
  total_nodes: number;
  healthy_nodes: number;
  nodes?: Array<{ host: string; port: number; healthy: boolean }>;
}

/** Agent config summary. */
interface ConfigSummary {
  agent_id: string;
  display_name: string;
  state: string;
  is_active: boolean;
}

// ===== Component =====

/**
 * MonitorPage — system monitoring dashboard.
 *
 * Auto-refreshes metrics every 30 seconds.
 */
export function MonitorPage(): JSX.Element {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [routeStats, setRouteStats] = useState<RouteStats | null>(null);
  const [llmStatus, setLlmStatus] = useState<LlmStatus | null>(null);
  const [tokenUsage, setTokenUsage] = useState<TokenUsageSummary | null>(null);
  const [proxyStatus, setProxyStatus] = useState<ProxyStatus | null>(null);
  const [configs, setConfigs] = useState<ConfigSummary[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string>("");
  const [error, setError] = useState<string | null>(null);

  // ===== Fetch All Metrics =====
  const fetchAll = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setError(null);

    const results = await Promise.allSettled([
      apiGet<HealthData>("/admin/health"),
      apiGet<RouteStats>("/admin/route-stats"),
      apiGet<LlmStatus>("/admin/llm/status"),
      apiGet<TokenUsageSummary>("/admin/llm/token-usage"),
      apiGet<ProxyStatus>("/admin/proxy/status"),
      apiGet<ConfigSummary[]>("/admin/configs"),
    ]);

    if (results[0].status === "fulfilled") setHealth(results[0].value);
    if (results[1].status === "fulfilled") setRouteStats(results[1].value);
    if (results[2].status === "fulfilled") setLlmStatus(results[2].value);
    if (results[3].status === "fulfilled") setTokenUsage(results[3].value);
    if (results[4].status === "fulfilled") setProxyStatus(results[4].value);
    if (results[5].status === "fulfilled") setConfigs(results[5].value || []);

    // Check for errors
    const failed = results.find((r) => r.status === "rejected");
    if (failed && failed.status === "rejected") {
      setError(
        failed.reason instanceof Error
          ? failed.reason.message
          : "部分指标获取失败",
      );
    }

    setLastUpdated(new Date().toISOString());
    setIsLoading(false);
  }, []);

  // ===== Auto-refresh =====
  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  return (
    <Layout
      title="系统监控"
      breadcrumbs={["管理后台", "系统监控"]}
    >
      {/* Error Banner */}
      {error && (
        <div className="mb-4 rounded-md border border-yellow-200 bg-yellow-50 px-4 py-3 text-sm text-yellow-700">
          ⚠ {error}
        </div>
      )}

      {/* Last Updated + Refresh */}
      <div className="mb-4 flex items-center justify-between">
        <p className="text-xs text-surface-dark/40">
          最后更新: {formatDateTime(lastUpdated)}
        </p>
        <button
          type="button"
          onClick={fetchAll}
          disabled={isLoading}
          className="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
        >
          {isLoading ? "刷新中..." : "刷新"}
        </button>
      </div>

      {/* Health Cards */}
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        {/* System Health */}
        <div className="rounded-lg bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-surface-dark/70">
            系统健康状态
          </h3>
          <div className="space-y-2">
            {health?.checks &&
              Object.entries(health.checks).map(([name, status]) => (
                <div key={name} className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60 capitalize">
                    {name}
                  </span>
                  <span
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      status === "ok"
                        ? "bg-green-100 text-green-700"
                        : "bg-red-100 text-red-700",
                    )}
                  >
                    {status === "ok" ? "正常" : "异常"}
                  </span>
                </div>
              ))}
            {!health?.checks && (
              <p className="text-sm text-surface-dark/40">加载中...</p>
            )}
          </div>
        </div>

        {/* LLM Gateway */}
        <div className="rounded-lg bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-surface-dark/70">
            LLM 网关状态
          </h3>
          <div className="space-y-2">
            {llmStatus ? (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">当前供应商</span>
                  <span className="text-sm font-medium text-surface-dark">
                    {llmStatus.current_provider ?? llmStatus.primary_provider}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">主供应商</span>
                  <span className="text-sm text-surface-dark">
                    {llmStatus.primary_provider}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">备用供应商</span>
                  <span className="text-sm text-surface-dark">
                    {llmStatus.fallback_provider}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">故障转移</span>
                  <span
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      llmStatus.failover_active
                        ? "bg-yellow-100 text-yellow-700"
                        : "bg-green-100 text-green-700",
                    )}
                  >
                    {llmStatus.failover_active ? "已激活" : "正常"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">总请求数</span>
                  <span className="text-sm text-surface-dark">
                    {formatNumber(llmStatus.total_requests)}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">错误数</span>
                  <span className="text-sm text-red-600">
                    {formatNumber(llmStatus.error_count)}
                  </span>
                </div>
              </>
            ) : (
              <p className="text-sm text-surface-dark/40">加载中...</p>
            )}
          </div>
        </div>

        {/* Proxy Status */}
        <div className="rounded-lg bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-surface-dark/70">
            出口代理状态
          </h3>
          <div className="space-y-2">
            {proxyStatus ? (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">代理状态</span>
                  <span
                    className={clsx(
                      "rounded-full px-2 py-0.5 text-xs font-medium",
                      proxyStatus.enabled
                        ? "bg-green-100 text-green-700"
                        : "bg-gray-100 text-gray-700",
                    )}
                  >
                    {proxyStatus.enabled ? "已启用" : "已禁用"}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-surface-dark/60">健康节点</span>
                  <span className="text-sm text-surface-dark">
                    {proxyStatus.healthy_nodes} / {proxyStatus.total_nodes}
                  </span>
                </div>
                {proxyStatus.nodes && proxyStatus.nodes.length > 0 && (
                  <div className="mt-2 space-y-1">
                    {proxyStatus.nodes.map((node, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between text-xs"
                      >
                        <span className="text-surface-dark/50">
                          {node.host}:{node.port}
                        </span>
                        <span
                          className={clsx(
                            "h-2 w-2 rounded-full",
                            node.healthy ? "bg-green-500" : "bg-red-500",
                          )}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <p className="text-sm text-surface-dark/40">加载中...</p>
            )}
          </div>
        </div>
      </div>

      {/* Token Usage & Route Stats */}
      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        {/* Token Usage */}
        <div className="rounded-lg bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-surface-dark/70">
            Token 用量统计
          </h3>
          {tokenUsage ? (
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-surface-dark/50">Prompt</p>
                <p className="text-lg font-bold text-surface-dark">
                  {formatTokenCount(tokenUsage.total_prompt)}
                </p>
              </div>
              <div>
                <p className="text-xs text-surface-dark/50">Completion</p>
                <p className="text-lg font-bold text-surface-dark">
                  {formatTokenCount(tokenUsage.total_completion)}
                </p>
              </div>
              <div>
                <p className="text-xs text-surface-dark/50">总计</p>
                <p className="text-lg font-bold text-primary-600">
                  {formatTokenCount(tokenUsage.total_tokens)}
                </p>
              </div>
            </div>
          ) : (
            <p className="text-sm text-surface-dark/40">加载中...</p>
          )}
        </div>

        {/* Route Stats */}
        <div className="rounded-lg bg-white p-5 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-surface-dark/70">
            路由统计
          </h3>
          {routeStats ? (
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="text-xs text-surface-dark/50">总请求数</p>
                <p className="text-lg font-bold text-surface-dark">
                  {formatNumber(routeStats.total_requests)}
                </p>
              </div>
              <div>
                <p className="text-xs text-surface-dark/50">成功路由</p>
                <p className="text-lg font-bold text-green-600">
                  {formatNumber(routeStats.successful_routes)}
                </p>
              </div>
              <div>
                <p className="text-xs text-surface-dark/50">失败路由</p>
                <p className="text-lg font-bold text-red-600">
                  {formatNumber(routeStats.failed_routes)}
                </p>
              </div>
              {routeStats.total_requests > 0 && (
                <div className="col-span-3">
                  <div className="mb-1 flex items-center justify-between text-xs">
                    <span className="text-surface-dark/50">成功率</span>
                    <span className="font-medium text-surface-dark">
                      {formatPercent(
                        (routeStats.successful_routes /
                          routeStats.total_requests) *
                          100,
                      )}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-surface-muted">
                    <div
                      className="h-full rounded-full bg-green-500"
                      style={{
                        width: `${(routeStats.successful_routes / routeStats.total_requests) * 100}%`,
                      }}
                    />
                  </div>
                </div>
              )}
            </div>
          ) : (
            <p className="text-sm text-surface-dark/40">加载中...</p>
          )}
        </div>
      </div>

      {/* Agent Configs Table */}
      <div className="overflow-hidden rounded-lg bg-white shadow-sm">
        <div className="border-b border-surface-light px-6 py-3">
          <h3 className="text-sm font-semibold text-surface-dark/70">
            Agent 配置概览
          </h3>
        </div>
        <table className="min-w-full divide-y divide-surface-light">
          <thead className="bg-surface-muted/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                Agent ID
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                显示名称
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                状态
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                活跃
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-light">
            {configs.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-6 py-8 text-center text-sm text-surface-dark/40">
                  暂无 Agent 配置
                </td>
              </tr>
            ) : (
              configs.map((config: ConfigSummary) => {
                const agentId = config.agent_id ?? config["agent_id"];
                const displayName = config.display_name ?? config["display_name"];
                const state = config.state ?? config["state"];
                const isActive = config.is_active ?? config["is_active"];
                return (
                  <tr key={agentId} className="hover:bg-surface-muted/30">
                    <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-surface-dark">
                      {agentId}
                    </td>
                    <td className="px-6 py-4 text-sm text-surface-dark/70">
                      {displayName}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={clsx(
                          "rounded-full px-2 py-0.5 text-xs font-medium",
                          state === "running"
                            ? "bg-green-100 text-green-700"
                            : "bg-gray-100 text-gray-700",
                        )}
                      >
                        {state ?? "unknown"}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={clsx(
                          "h-2 w-2 rounded-full inline-block",
                          isActive ? "bg-green-500" : "bg-gray-400",
                        )}
                      />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </Layout>
  );
}

export default MonitorPage;
