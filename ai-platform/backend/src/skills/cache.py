"""
HotSkillCache — 基于 Redis 的 Skill 元数据和查询结果缓存。

三层缓存：
1. 查询结果缓存：``query_hash → Top-50 SkillScores``（TTL 300s）
2. 热门 Skill 元数据缓存：``skill:{id} → Skill JSON``（TTL 3600s）
3. Schema 缓存：``skill_schema:{id} → JSON Schema``（TTL 1800s）

热门 Skill 通过 Redis Sorted Set ``skill:freq`` 追踪
调用频率来识别；Top-50 会被预热到元数据缓存中。
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

import redis.asyncio as aioredis
import structlog

from src.config import get_settings

if TYPE_CHECKING:
    from src.skills.models import Skill, SkillScore

logger = structlog.get_logger(__name__)


class HotSkillCache:
    """Skills 子系统的多层 Redis 缓存。"""

    def __init__(self, redis_client: aioredis.Redis | None = None) -> None:
        self._settings = get_settings()
        self._redis: aioredis.Redis = redis_client or aioredis.from_url(
            self._settings.redis_url,
            max_connections=self._settings.REDIS_MAX_CONNECTIONS,
            decode_responses=True,
        )
        self._query_ttl = self._settings.SKILLS_CACHE_TTL
        self._meta_ttl = 3600
        self._schema_ttl = 1800
        self._freq_key = "skill:freq"
        self._warmup_threshold = 50

    # ---- 查询结果缓存 ----

    @staticmethod
    def _query_hash(query: str, categories: list[str] | None = None) -> str:
        raw = f"{query}:{','.join(categories or [])}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def get_query_result(
        self, query: str, categories: list[str] | None = None
    ) -> list[SkillScore] | None:
        """返回 *query* 的缓存 Top-N 结果，缓存未命中时返回 ``None``。"""
        key = f"skill:query:{self._query_hash(query, categories)}"
        raw = await self._redis.get(key)
        if raw is None:
            return None
        from src.skills.models import SkillScore

        data = json.loads(raw)
        return [SkillScore.model_validate(item) for item in data]

    async def set_query_result(
        self,
        query: str,
        results: list[SkillScore],
        categories: list[str] | None = None,
        ttl: int | None = None,
    ) -> None:
        key = f"skill:query:{self._query_hash(query, categories)}"
        payload = json.dumps(
            [r.model_dump(mode="json") for r in results], ensure_ascii=False
        )
        await self._redis.set(key, payload, ex=ttl or self._query_ttl)

    # ---- 热门 Skill 元数据缓存 ----

    async def get_skill(self, skill_id: str) -> Skill | None:
        """返回缓存的 Skill 元数据，缓存未命中时返回 ``None``。"""
        raw = await self._redis.get(f"skill:meta:{skill_id}")
        if raw is None:
            return None
        from src.skills.models import Skill

        return Skill.model_validate_json(raw)

    async def set_skill(self, skill: Skill, ttl: int | None = None) -> None:
        await self._redis.set(
            f"skill:meta:{skill.skill_id}",
            skill.model_dump_json(),
            ex=ttl or self._meta_ttl,
        )

    async def invalidate_skill(self, skill_id: str) -> None:
        """从所有缓存中移除某个 Skill。"""
        await self._redis.delete(f"skill:meta:{skill_id}")
        await self._redis.delete(f"skill_schema:{skill_id}")
        await self._redis.zrem(self._freq_key, skill_id)
        logger.debug("Skill cache invalidated", skill_id=skill_id)

    # ---- Schema 缓存 ----

    async def get_schema(self, skill_id: str) -> dict[str, Any] | None:
        raw = await self._redis.get(f"skill_schema:{skill_id}")
        if raw is None:
            return None
        return json.loads(raw)

    async def set_schema(
        self, skill_id: str, schema: dict[str, Any], ttl: int | None = None
    ) -> None:
        await self._redis.set(
            f"skill_schema:{skill_id}",
            json.dumps(schema, ensure_ascii=False),
            ex=ttl or self._schema_ttl,
        )

    # ---- 频率追踪与预热 ----

    async def record_call(self, skill_id: str) -> None:
        """递增 *skill_id* 的调用频率计数器。"""
        await self._redis.zincrby(self._freq_key, 1, skill_id)

    async def get_hot_skills(self, top_n: int = 50) -> list[str]:
        """返回调用最频繁的 *top_n* 个 Skill ID。"""
        # ZREVRANGE 返回最高分排在最前
        return await self._redis.zrevrange(self._freq_key, 0, top_n - 1)

    async def warmup(self, skills: list[Skill]) -> int:
        """将热门 Skill 的元数据预加载到缓存中。

        *skills* 应为与热门 Skill ID 对应的完整 Skill 对象。
        返回已预热的 Skill 数量。
        """
        count = 0
        for skill in skills:
            await self.set_skill(skill, ttl=self._meta_ttl)
            count += 1
        logger.info("Hot skill cache warmed up", count=count)
        return count

    async def close(self) -> None:
        """关闭 Redis 连接。"""
        await self._redis.close()
