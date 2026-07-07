"""
SkillRetriever — 两阶段检索引擎的第一阶段。

接收用户的自然语言查询，生成 embedding，
并在 Qdrant ``skills_index`` 集合中搜索 Top-N（默认 50）
语义最相似的 Skill。

流程：
  1. 检查 Redis 查询结果缓存 → 命中则返回。
  2. 通过 Embedding 服务生成查询向量。
  3. Qdrant 向量搜索（带 payload 过滤器：status=active，可选 category）。
  4. 将结果缓存到 Redis（TTL 300s）。
  5. 返回已填充 semantic_similarity 的 list[SkillScore]。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from src.skills.indexer import VectorIndexer
from src.skills.models import Skill, SkillScore

if TYPE_CHECKING:
    from src.skills.cache import HotSkillCache
    from src.skills.grouper import SkillGrouper
    from src.skills.registry import SkillRegistry

logger = structlog.get_logger(__name__)


class SkillRetriever:
    """第一阶段语义检索器：查询 → embedding → Qdrant Top-N。"""

    def __init__(
        self,
        indexer: VectorIndexer,
        cache: HotSkillCache | None = None,
        grouper: SkillGrouper | None = None,
        registry: SkillRegistry | None = None,
        top_n: int = 50,
    ) -> None:
        self._indexer = indexer
        self._cache = cache
        self._grouper = grouper
        self._registry = registry
        self._default_top_n = top_n

    async def retrieve(
        self,
        query: str,
        top_n: int | None = None,
        categories: list[str] | None = None,
        skip_cache: bool = False,
    ) -> list[SkillScore]:
        """通过语义搜索检索匹配 *query* 的 Top-N Skill。

        Args:
            query: 用户的自然语言请求。
            top_n: 最大结果数（默认 50）。
            categories: 可选的分类过滤器，用于 payload 预过滤。
            skip_cache: 如果为 True，跳过 Redis 查询缓存。

        Returns:
            按语义相似度降序排列的 :class:`SkillScore` 列表，
            其中 ``semantic_similarity`` 已填充，但其他
            子分数为零（由 SkillRanker 填充）。
        """
        n = top_n or self._default_top_n

        # 1. 缓存查找
        if self._cache and not skip_cache:
            cached = await self._cache.get_query_result(query, categories)
            if cached is not None:
                logger.debug("SkillRetriever cache hit", query=query[:80])
                return cached[:n]

        # 2. 生成查询 embedding
        try:
            query_vector = await self._indexer.generate_embedding(query)
        except Exception:
            logger.exception("Failed to generate query embedding", query=query[:80])
            return []

        # 3. 确定分类过滤器
        category_filter = categories
        if self._grouper and category_filter is None:
            category_filter = self._grouper.get_candidate_categories(None)

        # 4. Qdrant 搜索
        try:
            hits = await self._indexer.search(
                query_vector=query_vector,
                top_n=n,
                category_filter=category_filter,
            )
        except Exception:
            logger.exception("Qdrant search failed", query=query[:80])
            return []

        # 5. 转换为 SkillScore
        results: list[SkillScore] = []
        for hit in hits:
            skill_id = hit["skill_id"]
            score = hit["score"]
            skill = None
            if self._registry:
                skill = self._registry.get(skill_id)
            if skill is None:
                # 回退：从 payload 构建最小化 Skill
                payload = hit.get("payload", {})
                skill = Skill(
                    skill_id=skill_id,
                    name=payload.get("name", skill_id),
                    description="",
                    category=payload.get("category", "built_in"),
                    status=payload.get("status", "active"),
                )
            results.append(
                SkillScore(
                    skill=skill,
                    semantic_similarity=score,
                    score=score,
                )
            )

        # 6. 缓存结果
        if self._cache and not skip_cache and results:
            try:
                await self._cache.set_query_result(query, results, categories)
            except Exception:
                logger.exception("Failed to cache query results")

        logger.debug(
            "SkillRetriever retrieved",
            query=query[:80],
            count=len(results),
            top_score=results[0].score if results else 0.0,
        )
        return results

    async def retrieve_by_category(
        self,
        query: str,
        categories: list[str],
        top_n: int | None = None,
    ) -> list[SkillScore]:
        """在指定 *categories* 范围内检索的便捷包装方法。"""
        return await self.retrieve(query, top_n=top_n, categories=categories)

    async def get_cached(self, query: str) -> list[SkillScore] | None:
        """返回 *query* 的缓存结果，不执行搜索。"""
        if self._cache:
            return await self._cache.get_query_result(query)
        return None
