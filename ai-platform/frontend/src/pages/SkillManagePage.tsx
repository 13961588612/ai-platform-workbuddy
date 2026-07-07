/**
 * SkillManagePage — Skill management admin page.
 *
 * Provides a table-based interface for managing Skills:
 * - List all skills with pagination
 * - Filter by category and status
 * - Create / edit / delete skills
 * - Enable / disable skills
 * - View skill statistics
 *
 * Backend endpoints (from skill.py route):
 * - GET    /api/v1/skills            — list skills
 * - GET    /api/v1/skills/{id}       — get skill detail
 * - POST   /api/v1/skills            — create skill
 * - PUT    /api/v1/skills/{id}       — update skill
 * - DELETE /api/v1/skills/{id}       — delete skill
 * - POST   /api/v1/skills/{id}/enable   — enable skill
 * - POST   /api/v1/skills/{id}/disable  — disable skill
 * - GET    /api/v1/skills/stats      — skill statistics
 */

import { useCallback, useEffect, useState } from "react";
import { Layout } from "../components/Layout";
import { apiGet, apiPost, apiDelete } from "../utils/api";
import {
  getSkillStatusLabel,
  getSkillStatusColor,
  getCategoryLabel,
  formatRelativeTime,
  clsx,
} from "../utils/format";
import type { Skill, SkillListResponse, SkillStats } from "../types/skill";
import type { SkillStatus, SkillCategory } from "../types/skill";

// ===== Component =====

/**
 * SkillManagePage — admin page for managing Skills.
 */
export function SkillManagePage(): JSX.Element {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [stats, setStats] = useState<SkillStats | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>("");
  const [filterStatus, setFilterStatus] = useState<string>("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  // ===== Fetch Skills =====
  const fetchSkills = useCallback(async (): Promise<void> => {
    setIsLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: "20",
      });
      if (filterCategory) params.set("category", filterCategory);
      if (filterStatus) params.set("status", filterStatus);

      const data = await apiGet<SkillListResponse>(`/skills?${params.toString()}`);
      setSkills(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "获取 Skill 列表失败";
      setError(message);
    } finally {
      setIsLoading(false);
    }
  }, [page, filterCategory, filterStatus]);

  // ===== Fetch Stats =====
  const fetchStats = useCallback(async (): Promise<void> => {
    try {
      const data = await apiGet<Record<string, number>>("/skills/stats");
      setStats({
        total: data.total ?? 0,
        active: data.active ?? 0,
        inactive: data.inactive ?? 0,
        byCategory: (data.by_category as Record<string, number>) ??
          (data.byCategory as Record<string, number>) ??
          {},
        bySource: (data.by_source as Record<string, number>) ??
          (data.bySource as Record<string, number>) ??
          {},
      });
    } catch {
      // Non-critical — don't show error
    }
  }, []);

  // ===== Load on mount and when filters change =====
  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  // ===== Handle Enable / Disable =====
  const handleToggleStatus = useCallback(
    async (skillId: string, currentStatus: SkillStatus): Promise<void> => {
      try {
        if (currentStatus === "active") {
          await apiPost(`/skills/${skillId}/disable`);
        } else {
          await apiPost(`/skills/${skillId}/enable`);
        }
        fetchSkills();
        fetchStats();
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "操作失败";
        setError(message);
      }
    },
    [fetchSkills, fetchStats],
  );

  // ===== Handle Delete =====
  const handleDelete = useCallback(
    async (skillId: string): Promise<void> => {
      if (!confirm(`确认删除 Skill "${skillId}" 吗？`)) {
        return;
      }
      try {
        await apiDelete(`/skills/${skillId}`);
        fetchSkills();
        fetchStats();
      } catch (err) {
        const message =
          err instanceof Error ? err.message : "删除失败";
        setError(message);
      }
    },
    [fetchSkills, fetchStats],
  );

  // ===== Categories for filter =====
  const categories: SkillCategory[] = [
    "finance",
    "retail",
    "department_store",
    "hr",
    "property",
    "crm",
    "valuecard",
    "built_in",
  ];

  return (
    <Layout
      title="Skill 管理"
      breadcrumbs={["管理后台", "Skill 管理"]}
    >
      {/* Stats Cards */}
      {stats && (
        <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg bg-white p-4 shadow-sm">
            <p className="text-sm text-surface-dark/50">总 Skill 数</p>
            <p className="mt-1 text-2xl font-bold text-surface-dark">
              {stats.total}
            </p>
          </div>
          <div className="rounded-lg bg-white p-4 shadow-sm">
            <p className="text-sm text-surface-dark/50">已启用</p>
            <p className="mt-1 text-2xl font-bold text-green-600">
              {stats.active}
            </p>
          </div>
          <div className="rounded-lg bg-white p-4 shadow-sm">
            <p className="text-sm text-surface-dark/50">已停用</p>
            <p className="mt-1 text-2xl font-bold text-gray-500">
              {stats.inactive}
            </p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex items-center gap-4">
        <select
          value={filterCategory}
          onChange={(e) => {
            setFilterCategory(e.target.value);
            setPage(1);
          }}
          className="rounded-md border border-surface-light bg-white px-3 py-2 text-sm"
        >
          <option value="">全部分类</option>
          {categories.map((cat) => (
            <option key={cat} value={cat}>
              {getCategoryLabel(cat)}
            </option>
          ))}
        </select>
        <select
          value={filterStatus}
          onChange={(e) => {
            setFilterStatus(e.target.value);
            setPage(1);
          }}
          className="rounded-md border border-surface-light bg-white px-3 py-2 text-sm"
        >
          <option value="">全部状态</option>
          <option value="active">启用</option>
          <option value="inactive">停用</option>
          <option value="deprecated">已废弃</option>
        </select>
        <button
          type="button"
          onClick={fetchSkills}
          className="rounded-md bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          刷新
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* Skills Table */}
      <div className="overflow-hidden rounded-lg bg-white shadow-sm">
        <table className="min-w-full divide-y divide-surface-light">
          <thead className="bg-surface-muted/50">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                Skill ID
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                名称
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                分类
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                状态
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                来源
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                调用次数
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                最后调用
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase text-surface-dark/50">
                操作
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-surface-light">
            {isLoading ? (
              <tr>
                <td colSpan={8} className="px-6 py-8 text-center text-sm text-surface-dark/40">
                  加载中...
                </td>
              </tr>
            ) : skills.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-6 py-8 text-center text-sm text-surface-dark/40">
                  暂无 Skill 数据
                </td>
              </tr>
            ) : (
              skills.map((skill: Skill) => (
                <tr key={skill.skillId} className="hover:bg-surface-muted/30">
                  <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-surface-dark">
                    {skill.skillId}
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/70">
                    {skill.name}
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/70">
                    {getCategoryLabel(skill.category)}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={clsx(
                        "rounded-full px-2 py-0.5 text-xs font-medium",
                        getSkillStatusColor(skill.status),
                      )}
                    >
                      {getSkillStatusLabel(skill.status)}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/70">
                    {skill.source}
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/70">
                    {skill.callCount}
                  </td>
                  <td className="px-6 py-4 text-sm text-surface-dark/50">
                    {formatRelativeTime(skill.lastCalledAt)}
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleToggleStatus(skill.skillId, skill.status)}
                        className="text-xs text-primary-600 hover:text-primary-700"
                      >
                        {skill.status === "active" ? "停用" : "启用"}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(skill.skillId)}
                        className="text-xs text-red-600 hover:text-red-700"
                      >
                        删除
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {total > 20 && (
        <div className="mt-4 flex items-center justify-between">
          <p className="text-sm text-surface-dark/50">
            共 {total} 条记录，第 {page} 页
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
              className="rounded-md border border-surface-light px-3 py-1.5 text-sm disabled:opacity-50"
            >
              上一页
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => p + 1)}
              disabled={page * 20 >= total}
              className="rounded-md border border-surface-light px-3 py-1.5 text-sm disabled:opacity-50"
            >
              下一页
            </button>
          </div>
        </div>
      )}
    </Layout>
  );
}

export default SkillManagePage;
