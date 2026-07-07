"""
SkillRanker — 两阶段检索引擎的第二阶段。

从 SkillRetriever 接收 Top-N 候选，并生成最终的 Top-K
列表，流程如下：
  1. **权限过滤** — 移除用户无权调用的 Skill。
  2. **重排序** — 计算综合分数，权重如下：
     - 0.5 × 语义相似度（来自第一阶段）
     - 0.2 × 使用频率（call_count 归一化）
     - 0.15 × 近期奖励（last_called_at 时间衰减）
     - 0.15 × 分类匹配（用户偏好分类）
  3. **动态 K 选择** — K 取决于查询复杂度：
     - 简单（< 20 字符，单一意图）→ K=5
     - 中等（20–80 字符或多条件）→ K=10
     - 复杂（> 80 字符或多步骤）→ K=20
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

from src.skills.models import Skill, SkillScore

if TYPE_CHECKING:
    from src.identity.models import UserContext
    from src.identity.permissions import PermissionEngine

logger = structlog.get_logger(__name__)


class SkillRanker:
    """第二阶段排序器：权限过滤 + 多信号重排序。"""

    def __init__(
        self,
        permission_engine: PermissionEngine | None = None,
        default_top_k: int = 5,
    ) -> None:
        self._permission_engine = permission_engine
        self._default_top_k = default_top_k

    # ---- 公开 API ----

    async def rank(
        self,
        candidates: list[SkillScore],
        user: UserContext,
        query: str,
        top_k: int | None = None,
    ) -> list[Skill]:
        """为 *user* 对 *candidates* 排序，返回 Top-K 的 Skill。

        Args:
            candidates: 来自 SkillRetriever 的第一阶段结果。
            user: 认证用户的上下文（角色、部门、覆盖设置）。
            query: 原始查询字符串（用于基于复杂度的 K 值计算）。
            top_k: 覆盖动态 K 值计算。

        Returns:
            按综合分数降序排列的 :class:`Skill` 对象列表。
        """
        # 1. 权限过滤
        filtered = await self.filter_by_permission(candidates, user)

        # 2. 重排序
        reranked = self.rerank(filtered, user, query)

        # 3. 动态 K
        k = top_k or self._compute_dynamic_k(query)
        top = reranked[:k]

        logger.debug(
            "SkillRanker ranked",
            candidates=len(candidates),
            filtered=len(filtered),
            top_k=k,
            user_id=user.user_id,
        )

        return [ts.skill for ts in top]

    # ---- 权限过滤 ----

    async def filter_by_permission(
        self,
        candidates: list[SkillScore],
        user: UserContext,
    ) -> list[SkillScore]:
        """移除 *user* 无权调用的 Skill。"""
        if not self._permission_engine:
            return candidates

        allowed: list[SkillScore] = []
        for candidate in candidates:
            if self._permission_engine.check_permission(user, candidate.skill):
                allowed.append(candidate)
            else:
                logger.debug(
                    "Skill filtered by permission",
                    skill_id=candidate.skill.skill_id,
                    user_id=user.user_id,
                )
        return allowed

    # ---- 重排序 ----

    def rerank(
        self,
        candidates: list[SkillScore],
        user: UserContext,
        query: str,
    ) -> list[SkillScore]:
        """计算综合分数并返回排序后的列表。"""
        if not candidates:
            return []

        # 找到最大 call_count 用于归一化
        max_calls = max(
            (c.skill.call_count for c in candidates), default=1
        ) or 1

        now = datetime.now(timezone.utc)
        user_categories = set(getattr(user, "allowed_categories", []) or [])

        for candidate in candidates:
            skill = candidate.skill

            # 使用频率（归一化 0-1）
            candidate.usage_frequency = skill.call_count / max_calls

            # 近期奖励（30 天指数衰减）
            if skill.last_called_at:
                delta = now - skill.last_called_at
                days = delta.total_seconds() / 86400.0
                candidate.recency_bonus = math.exp(-days / 30.0)
            else:
                candidate.recency_bonus = 0.0

            # 分类匹配（用户分类包含此 skill 分类时为 1.0）
            if user_categories and skill.category in user_categories:
                candidate.category_match = 1.0
            elif not user_categories:
                candidate.category_match = 0.5  # 中性
            else:
                candidate.category_match = 0.0

            # 应用优先级权重
            priority_weight = skill.priority if skill.priority else 1.0
            candidate.compute_composite()
            candidate.score *= priority_weight

        # 按综合分数降序排列
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    # ---- 动态 K ----

    @staticmethod
    def _compute_dynamic_k(query: str) -> int:
        """基于查询复杂度确定 K 值（轻量级规则引擎）。"""
        query_len = len(query)

        # 多步骤指示符
        multi_step_markers = ["并且", "然后", "接着", "之后", "以及", "同时"]
        has_multi_step = any(marker in query for marker in multi_step_markers)

        # 多条件指示符
        multi_condition_markers = ["和", "与", "及", "，", "、"]
        condition_count = sum(1 for m in multi_condition_markers if m in query)

        if query_len > 80 or has_multi_step:
            return 20
        elif query_len > 20 or condition_count >= 2:
            return 10
        else:
            return 5

    # ---- 辅助方法 ----

    def get_allowed_skills(self, user: UserContext) -> list[str]:
        """返回用户有权调用的 Skill ID 列表。"""
        if not self._permission_engine:
            return []
        return self._permission_engine.get_allowed_skills(user)
