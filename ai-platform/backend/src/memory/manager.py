"""
MemoryManager — Agent 记忆的中央编排器。

职责：
1. **静态记忆** — 委托给 :class:`StaticMemoryLoader` 处理基于文件的
   人格 + 事实，支持配置热重载时的缓存失效。
2. **动态记忆检索** — 两阶段 Qdrant 语义搜索：
   - 批次 1：用户级记忆（``session_id IS NULL``，跨渠道共享）
   - 批次 2：会话级记忆（按 ``session_id`` 严格隔离）
   结果合并并按 ``importance × similarity × recency`` 排序。
3. **动态记忆写回** — 同时持久化到 PostgreSQL（结构化数据）和 Qdrant
   （向量索引），使用共享的 bge-small-zh-v1.5 嵌入模型（768 维，与
   Skills 相同）。
4. **遗忘策略** — TTL 过期、容量强制执行、会话级升级（importance ≥ 0.8）
   和 importance 衰减（每月 ×0.95）。

所有 I/O 完全异步（async/await）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant_models
from sqlalchemy import delete, func, select

from src.config import get_settings
from src.db.session import db_session_context
from src.models.agent_memory import AgentMemory
from src.memory.models import (
    ExtractedMemory,
    MemoryEntry,
    MemorySearchResult,
    MemoryType,
)
from src.memory.static_loader import StaticMemoryLoader, get_static_memory_loader

logger = structlog.get_logger("memory.manager")

# 时效衰减：每 30 天 importance 乘以 0.95
_RECENCY_DECAY_PER_MONTH: float = 0.95
_RECENCY_MIN_FACTOR: float = 0.05
_DAYS_PER_MONTH: int = 30

# importance ≥ 此阈值的会话级记忆会升级为用户级
_PROMOTION_THRESHOLD: float = 0.8

# 提取记忆被持久化的最低 importance
_MIN_WRITE_IMPORTANCE: float = 0.3

# 会话关闭后，摘要类记忆保留此天数
_SESSION_SUMMARY_TTL_DAYS: int = 7


class MemoryManager:
    """
    管理静态和动态 Agent 记忆。

    用法::

        manager = get_memory_manager()
        await manager.ensure_collection()

        # 在 agent 运行前检索相关记忆
        results = await manager.retrieve_dynamic_memory(
            query="用户问年假",
            agent_name="hr-assistant",
            user_id="u123",
            session_id="web-abc",
        )

        # 运行后写回记忆
        await manager.write_dynamic_memory(
            agent_name="hr-assistant",
            user_id="u123",
            session_id="web-abc",
            memory_type=MemoryType.PREFERENCE,
            content="用户偏好中文回复",
            importance=0.7,
        )
    """

    def __init__(
        self,
        static_loader: StaticMemoryLoader | None = None,
        qdrant_client: AsyncQdrantClient | None = None,
    ) -> None:
        self._settings = get_settings()
        self._static_loader: StaticMemoryLoader = static_loader or get_static_memory_loader()
        self._qdrant: AsyncQdrantClient = qdrant_client or AsyncQdrantClient(
            url=self._settings.qdrant_url,
            api_key=self._settings.QDRANT_API_KEY or None,
        )
        self._embedding_url: str = self._settings.EMBEDDING_SERVICE_URL
        self._collection_name: str = self._settings.QDRANT_COLLECTION_AGENT_MEMORY
        self._vector_size: int = self._settings.EMBEDDING_DIMENSION
        self._collection_ready: bool = False

    # ==================================================================
    # 静态记忆
    # ==================================================================

    def load_static_memory(self, agent_name: str) -> str:
        """
        为 *agent_name* 加载并返回组装后的静态记忆文本。

        委托给 :class:`StaticMemoryLoader`。结果被缓存；当检测到配置
        热重载时调用 :meth:`invalidate_static_cache` 来失效缓存。
        """
        return self._static_loader.load(agent_name)

    def invalidate_static_cache(self, agent_name: str | None = None) -> None:
        """
        使静态记忆缓存失效。

        如果提供了 *agent_name*，只清除该 agent 的缓存。
        否则清除所有缓存。由 ConfigManager 热重载回调调用，以确保
        下一次加载获取到最新内容。
        """
        if agent_name is not None:
            self._static_loader.invalidate(agent_name)
        else:
            self._static_loader.invalidate_all()

    def check_static_reload(self, agent_name: str) -> bool:
        """检查 *agent_name* 的静态记忆文件是否发生了变更。"""
        return self._static_loader.check_and_reload(agent_name)

    # ==================================================================
    # Qdrant 集合管理
    # ==================================================================

    async def ensure_collection(self) -> None:
        """如果不存在则创建 Qdrant ``agent_memory_index`` 集合。"""
        if self._collection_ready:
            return
        try:
            collections = await self._qdrant.get_collections()
            names = [c.name for c in collections.collections]
            if self._collection_name not in names:
                await self._qdrant.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=qdrant_models.VectorParams(
                        size=self._vector_size,
                        distance=qdrant_models.Distance.COSINE,
                    ),
                    hnsw_config=qdrant_models.HnswConfigDiff(
                        m=16,
                        ef_construct=100,
                    ),
                    optimizers_config=qdrant_models.OptimizersConfigDiff(
                        indexing_threshold=0,
                    ),
                )
                # 创建 payload 索引以支持高效筛选
                for field in ("agent_name", "user_id", "session_id", "scope"):
                    await self._qdrant.create_payload_index(
                        collection_name=self._collection_name,
                        field_name=field,
                        field_schema=qdrant_models.PayloadSchemaType.KEYWORD,
                    )
                logger.info(
                    "Agent memory Qdrant collection created",
                    collection=self._collection_name,
                    vector_size=self._vector_size,
                )
            self._collection_ready = True
        except Exception:
            logger.exception(
                "Failed to ensure agent memory collection",
                collection=self._collection_name,
            )
            raise

    # ==================================================================
    # 嵌入
    # ==================================================================

    async def _generate_embedding(self, text: str) -> list[float]:
        """
        通过共享的 Embedding 服务为 *text* 生成嵌入向量。

        使用与 Skills 索引器相同的 bge-small-zh-v1.5 模型（768 维），
        确保所有向量集合之间的一致性。
        """
        url = f"{self._embedding_url}/embed"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"text": text})
            resp.raise_for_status()
            data = resp.json()
            return data.get("embedding", data.get("vector", []))

    # ==================================================================
    # 动态记忆 — 两阶段检索
    # ==================================================================

    async def retrieve_dynamic_memory(
        self,
        query: str,
        agent_name: str,
        user_id: str,
        session_id: str | None = None,
        top_k: int = 5,
    ) -> list[MemorySearchResult]:
        """
        为查询检索最相关的动态记忆。

        实现 v1.4.1 两阶段检索：

        - **批次 1（用户级）**：在 Qdrant 中搜索 ``agent_name + user_id``
          且 ``scope = "user"`` 的记录（session_id IS NULL → 跨渠道共享）。
        - **批次 2（会话级）**：在 Qdrant 中搜索 ``agent_name + user_id``
          且 ``scope = "session"``、``session_id = <当前会话>`` 的记录
          （严格隔离）。

        两个批次合并后按 ``importance × similarity × recency_factor``
        排序，返回 Top-K 条目。

        Args:
            query: 自然语言查询文本。
            agent_name: Agent 标识符。
            user_id: 用户标识符。
            session_id: 当前会话 ID（agent 级上下文时为 None）。
            top_k: 返回结果的最大数量。

        Returns:
            按综合分数降序排列的 :class:`MemorySearchResult` 列表。
        """
        await self.ensure_collection()

        if not query.strip():
            return []

        # 生成查询嵌入
        try:
            query_vector = await self._generate_embedding(query)
        except Exception:
            logger.exception(
                "Failed to generate query embedding for memory retrieval",
                agent_name=agent_name,
                query=query[:80],
            )
            return []

        # 批次 1：用户级记忆（session_id IS NULL，跨渠道）
        user_level_results = await self._qdrant_search(
            query_vector=query_vector,
            agent_name=agent_name,
            user_id=user_id,
            scope="user",
            session_id=None,
            limit=top_k,
        )

        # 批次 2：会话级记忆（严格隔离）
        session_level_results: list[dict[str, Any]] = []
        if session_id:
            session_level_results = await self._qdrant_search(
                query_vector=query_vector,
                agent_name=agent_name,
                user_id=user_id,
                scope="session",
                session_id=session_id,
                limit=top_k,
            )

        # 合并并计算综合分数
        merged: list[MemorySearchResult] = []
        now = datetime.now(timezone.utc)

        for hit in user_level_results + session_level_results:
            payload = hit.get("payload", {})
            similarity = hit.get("score", 0.0) or 0.0
            importance = float(payload.get("importance", 0.5))
            created_at_str = payload.get("created_at", "")
            recency_factor = self._compute_recency_factor(created_at_str, now)
            composite = importance * similarity * recency_factor

            entry = self._payload_to_entry(payload, hit.get("id", ""))
            merged.append(
                MemorySearchResult(
                    entry=entry,
                    similarity=similarity,
                    composite_score=composite,
                )
            )

        # 按综合分数降序排列，取 top_k
        merged.sort(key=lambda r: r.composite_score, reverse=True)
        result = merged[:top_k]

        logger.debug(
            "Dynamic memory retrieved",
            agent_name=agent_name,
            user_id=user_id,
            session_id=session_id,
            user_level_count=len(user_level_results),
            session_level_count=len(session_level_results),
            returned=len(result),
        )
        return result

    async def _qdrant_search(
        self,
        query_vector: list[float],
        agent_name: str,
        user_id: str,
        scope: str,
        session_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """
        在 agent_memory_index 集合中使用 payload 筛选进行搜索。

        构建匹配 agent_name + user_id + scope 的 Qdrant 筛选条件，
        scope 为 "session" 时再加上 session_id。
        """
        must_conditions: list[qdrant_models.FieldCondition] = [
            qdrant_models.FieldCondition(
                key="agent_name",
                match=qdrant_models.MatchValue(value=agent_name),
            ),
            qdrant_models.FieldCondition(
                key="user_id",
                match=qdrant_models.MatchValue(value=user_id),
            ),
            qdrant_models.FieldCondition(
                key="scope",
                match=qdrant_models.MatchValue(value=scope),
            ),
        ]
        if scope == "session" and session_id:
            must_conditions.append(
                qdrant_models.FieldCondition(
                    key="session_id",
                    match=qdrant_models.MatchValue(value=session_id),
                )
            )

        try:
            results = await self._qdrant.search(
                collection_name=self._collection_name,
                query_vector=query_vector,
                limit=limit,
                query_filter=qdrant_models.Filter(must=must_conditions),
                with_payload=True,
            )
        except Exception:
            logger.exception(
                "Qdrant search failed for agent memory",
                agent_name=agent_name,
                scope=scope,
            )
            return []

        return [
            {
                "id": str(hit.id),
                "score": hit.score or 0.0,
                "payload": hit.payload or {},
            }
            for hit in results
        ]

    # ==================================================================
    # 动态记忆 — 写回
    # ==================================================================

    async def write_dynamic_memory(
        self,
        agent_name: str,
        user_id: str,
        session_id: str | None,
        memory_type: MemoryType,
        content: str,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        ttl_days: int | None = None,
    ) -> MemoryEntry | None:
        """
        将动态记忆条目持久化到 PostgreSQL 和 Qdrant。

        嵌入通过共享的 bge-small-zh-v1.5 模型生成。
        写入前会强制执行每个用户的容量限制（``max_per_user``）——
        如果超出限制，得分最低的条目会被驱逐。

        Args:
            agent_name: Agent 标识符。
            user_id: 用户标识符。
            session_id: 会话 ID（用户级记忆时为 None）。
            memory_type: 记忆分类。
            content: 记忆内容文本。
            importance: Importance 评分 0.0–1.0。
            metadata: 额外元数据字典。
            ttl_days: TTL 天数；None 则使用配置默认值。

        Returns:
            创建的 :class:`MemoryEntry`，写入失败时返回 ``None``。
        """
        if not content.strip():
            return None

        await self.ensure_collection()

        # 钳制 importance
        importance = max(0.0, min(1.0, importance))

        # 确定 TTL
        effective_ttl = ttl_days if ttl_days is not None else self._settings.AGENT_MEMORY_TTL_DAYS
        expires_at: datetime | None = None
        if effective_ttl > 0:
            expires_at = datetime.now(timezone.utc) + timedelta(days=effective_ttl)

        meta = metadata or {}

        # 1. 插入 PostgreSQL
        memory_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        async with db_session_context() as session:
            record = AgentMemory(
                id=memory_id,
                agent_name=agent_name,
                session_id=session_id,
                user_id=user_id,
                memory_type=memory_type.value,
                content=content,
                importance=importance,
                metadata_=meta,
                expires_at=expires_at,
            )
            session.add(record)

        # 2. 生成嵌入并 upsert 到 Qdrant
        try:
            vector = await self._generate_embedding(content)
        except Exception:
            logger.exception(
                "Failed to generate embedding for memory write-back",
                agent_name=agent_name,
                memory_id=memory_id,
            )
            # PG 记录已提交；Qdrant 索引将由未来的重建索引任务重建。
            # 记录日志并继续。
            return MemoryEntry(
                id=memory_id,
                agent_name=agent_name,
                session_id=session_id,
                user_id=user_id,
                memory_type=memory_type,
                content=content,
                importance=importance,
                metadata=meta,
                expires_at=expires_at,
                created_at=now,
                updated_at=now,
            )

        scope = "user" if session_id is None else "session"
        point = qdrant_models.PointStruct(
            id=memory_id,
            vector=vector,
            payload={
                "memory_id": memory_id,
                "agent_name": agent_name,
                "user_id": user_id,
                "session_id": session_id,
                "scope": scope,
                "memory_type": memory_type.value,
                "content": content,
                "importance": importance,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
        )
        try:
            await self._qdrant.upsert(
                collection_name=self._collection_name,
                points=[point],
            )
        except Exception:
            logger.exception(
                "Failed to upsert memory into Qdrant",
                agent_name=agent_name,
                memory_id=memory_id,
            )

        # 3. 强制执行容量限制
        await self._enforce_capacity(agent_name, user_id)

        logger.debug(
            "Dynamic memory written",
            agent_name=agent_name,
            user_id=user_id,
            session_id=session_id,
            memory_id=memory_id,
            memory_type=memory_type.value,
            importance=importance,
        )

        return MemoryEntry(
            id=memory_id,
            agent_name=agent_name,
            session_id=session_id,
            user_id=user_id,
            memory_type=memory_type,
            content=content,
            importance=importance,
            metadata=meta,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

    async def write_extracted_memories(
        self,
        agent_name: str,
        user_id: str,
        session_id: str | None,
        extracted: list[ExtractedMemory],
    ) -> int:
        """
        批量写入 LLM 提取的记忆点。

        只有 ``importance > 0.3`` 的条目会被持久化（A19 策略）。

        返回实际写入的记忆数量。
        """
        written = 0
        for item in extracted:
            if item.importance <= _MIN_WRITE_IMPORTANCE:
                continue
            result = await self.write_dynamic_memory(
                agent_name=agent_name,
                user_id=user_id,
                session_id=session_id,
                memory_type=item.memory_type,
                content=item.content,
                importance=item.importance,
            )
            if result is not None:
                written += 1
        return written

    # ==================================================================
    # 动态记忆 — 删除
    # ==================================================================

    async def delete_memory(self, memory_id: str) -> None:
        """从 PostgreSQL 和 Qdrant 中删除单条记忆。"""
        # 从 Qdrant 删除
        try:
            await self._qdrant.delete(
                collection_name=self._collection_name,
                points_selector=qdrant_models.PointIdsList(points=[memory_id]),
            )
        except Exception:
            logger.exception("Failed to delete memory from Qdrant", memory_id=memory_id)

        # 从 PostgreSQL 删除
        async with db_session_context() as session:
            await session.execute(
                delete(AgentMemory).where(AgentMemory.id == memory_id)
            )

        logger.debug("Memory deleted", memory_id=memory_id)

    # ==================================================================
    # 遗忘策略
    # ==================================================================

    async def run_forget_cycle(self) -> dict[str, int]:
        """
        执行完整的遗忘策略周期。

        应周期性调用（例如通过 APScheduler 每小时一次）。

        步骤：
        1. 删除已过期的记忆（``expires_at < NOW()``）。
        2. 强制执行每个用户的容量限制（驱逐得分最低的）。
        3. 将高 importance 的会话记忆升级为用户级。
        4. 应用 importance 衰减（超过 30 天的记忆每月 ×0.95）。

        返回包含每个操作计数的摘要字典。
        """
        expired_count = await self._forget_expired()
        evicted_count = await self._enforce_capacity_all()
        promoted_count = await self._promote_session_memories()
        decayed_count = await self._apply_importance_decay()

        summary = {
            "expired_deleted": expired_count,
            "capacity_evicted": evicted_count,
            "session_promoted": promoted_count,
            "importance_decayed": decayed_count,
        }
        logger.info("Forget cycle completed", **summary)
        return summary

    async def _forget_expired(self) -> int:
        """从 PG 和 Qdrant 中删除 ``expires_at < NOW()`` 的记忆。"""
        now = datetime.now(timezone.utc)
        expired_ids: list[str] = []

        async with db_session_context() as session:
            stmt = select(AgentMemory.id).where(
                AgentMemory.expires_at.is_not(None),
                AgentMemory.expires_at < now,
            )
            result = await session.execute(stmt)
            expired_ids = [row[0] for row in result.all()]

        if not expired_ids:
            return 0

        # 从 Qdrant 删除
        try:
            await self._qdrant.delete(
                collection_name=self._collection_name,
                points_selector=qdrant_models.PointIdsList(points=expired_ids),
            )
        except Exception:
            logger.exception("Failed to delete expired memories from Qdrant")

        # 从 PostgreSQL 删除
        async with db_session_context() as session:
            await session.execute(
                delete(AgentMemory).where(AgentMemory.id.in_(expired_ids))
            )

        logger.debug("Expired memories deleted", count=len(expired_ids))
        return len(expired_ids)

    async def _enforce_capacity(self, agent_name: str, user_id: str) -> int:
        """
        对单个 agent + user 强制执行每个用户的容量限制。

        如果计数超过 ``max_per_user``，得分最低的条目（按
        ``importance × recency``）会被驱逐。

        返回被驱逐的记忆数量。
        """
        max_per_user = self._settings.AGENT_MEMORY_MAX_PER_USER

        async with db_session_context() as session:
            count_stmt = select(func.count(AgentMemory.id)).where(
                AgentMemory.agent_name == agent_name,
                AgentMemory.user_id == user_id,
            )
            result = await session.execute(count_stmt)
            total = result.scalar() or 0

            if total <= max_per_user:
                return 0

            # 计算驱逐分数并选择受害者
            excess = total - max_per_user
            now = datetime.now(timezone.utc)
            victim_stmt = (
                select(
                    AgentMemory.id,
                    AgentMemory.importance,
                    AgentMemory.created_at,
                )
                .where(
                    AgentMemory.agent_name == agent_name,
                    AgentMemory.user_id == user_id,
                )
                .order_by(AgentMemory.importance.asc(), AgentMemory.created_at.asc())
                .limit(excess)
            )
            victim_result = await session.execute(victim_stmt)
            victim_ids = [row[0] for row in victim_result.all()]

        if not victim_ids:
            return 0

        # 从 Qdrant 删除受害者
        try:
            await self._qdrant.delete(
                collection_name=self._collection_name,
                points_selector=qdrant_models.PointIdsList(points=victim_ids),
            )
        except Exception:
            logger.exception("Failed to evict memories from Qdrant")

        # 从 PostgreSQL 删除
        async with db_session_context() as session:
            await session.execute(
                delete(AgentMemory).where(AgentMemory.id.in_(victim_ids))
            )

        logger.debug(
            "Capacity enforcement evicted memories",
            agent_name=agent_name,
            user_id=user_id,
            evicted=len(victim_ids),
        )
        return len(victim_ids)

    async def _enforce_capacity_all(self) -> int:
        """对所有 agent + user 组合强制执行容量限制。"""
        total_evicted = 0
        async with db_session_context() as session:
            stmt = (
                select(
                    AgentMemory.agent_name,
                    AgentMemory.user_id,
                )
                .where(AgentMemory.user_id.is_not(None))
                .group_by(AgentMemory.agent_name, AgentMemory.user_id)
            )
            result = await session.execute(stmt)
            pairs = result.all()

        for agent_name, user_id in pairs:
            if user_id is None:
                continue
            total_evicted += await self._enforce_capacity(agent_name, user_id)
        return total_evicted

    async def _promote_session_memories(self) -> int:
        """
        将高 importance 的会话级记忆升级为用户级。

        ``importance >= 0.8`` 且 ``session_id`` 非空的记忆会将其
        ``session_id`` 清空（变为用户级，跨渠道共享）。
        """
        async with db_session_context() as session:
            # 查找可升级的记忆
            stmt = select(AgentMemory).where(
                AgentMemory.session_id.is_not(None),
                AgentMemory.importance >= _PROMOTION_THRESHOLD,
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            if not records:
                return 0

            promoted_ids: list[str] = []
            for record in records:
                record.session_id = None
                promoted_ids.append(record.id)

        # 更新 Qdrant payload：scope → "user"，session_id → null
        if promoted_ids:
            try:
                await self._qdrant.set_payload(
                    collection_name=self._collection_name,
                    payload={"scope": "user", "session_id": None},
                    points=promoted_ids,
                )
            except Exception:
                logger.exception(
                    "Failed to update Qdrant payloads for promotion",
                    count=len(promoted_ids),
                )

        logger.debug("Session memories promoted to user-level", count=len(promoted_ids))
        return len(promoted_ids)

    async def _apply_importance_decay(self) -> int:
        """
        对超过 30 天的记忆应用 importance 衰减。

        每个月，importance 乘以 0.95。我们在 metadata 中跟踪上次
        衰减日期，以避免在同一月内重复衰减。
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=_DAYS_PER_MONTH)
        decay_key = "last_decay_at"
        decayed_count = 0

        async with db_session_context() as session:
            stmt = select(AgentMemory).where(
                AgentMemory.created_at < cutoff,
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            for record in records:
                meta = record.metadata_ or {}
                last_decay_str = meta.get(decay_key)
                if last_decay_str:
                    try:
                        last_decay = datetime.fromisoformat(last_decay_str)
                        if last_decay > cutoff:
                            # 本月已衰减
                            continue
                    except (ValueError, TypeError):
                        pass  # 损坏的日期 — 继续衰减

                # 应用衰减
                record.importance = max(0.01, record.importance * _RECENCY_DECAY_PER_MONTH)
                meta[decay_key] = now.isoformat()
                record.metadata_ = meta
                decayed_count += 1

        logger.debug("Importance decay applied", count=decayed_count)
        return decayed_count

    async def cleanup_session(self, session_id: str) -> int:
        """
        清理已关闭会话的记忆。

        摘要类记忆保留 7 天（设置 TTL），然后由遗忘周期过期。
        非摘要的会话记忆立即删除。

        返回立即删除的记忆数量。
        """
        now = datetime.now(timezone.utc)
        summary_ttl = now + timedelta(days=_SESSION_SUMMARY_TTL_DAYS)
        deleted_ids: list[str] = []

        async with db_session_context() as session:
            stmt = select(AgentMemory).where(
                AgentMemory.session_id == session_id,
            )
            result = await session.execute(stmt)
            records = result.scalars().all()

            for record in records:
                if record.memory_type == MemoryType.SUMMARY.value:
                    # 摘要保留 7 天 TTL
                    record.expires_at = summary_ttl
                else:
                    # 标记为立即删除
                    deleted_ids.append(record.id)

        # 删除非摘要的会话记忆
        if deleted_ids:
            try:
                await self._qdrant.delete(
                    collection_name=self._collection_name,
                    points_selector=qdrant_models.PointIdsList(points=deleted_ids),
                )
            except Exception:
                logger.exception(
                    "Failed to delete session memories from Qdrant",
                    session_id=session_id,
                )
            async with db_session_context() as session:
                await session.execute(
                    delete(AgentMemory).where(AgentMemory.id.in_(deleted_ids))
                )

        logger.debug(
            "Session memory cleanup completed",
            session_id=session_id,
            deleted=len(deleted_ids),
        )
        return len(deleted_ids)

    # ==================================================================
    # 评分辅助函数
    # ==================================================================

    @staticmethod
    def _compute_recency_factor(created_at_str: str, now: datetime) -> float:
        """
        根据记忆年龄计算时效衰减因子。

        因子 = 0.95 ^ (age_months)，限制最低为 0.05。
        今天创建的记忆因子为 1.0；12 个月前的记忆 ≈ 0.54。
        """
        if not created_at_str:
            return 1.0
        try:
            created = datetime.fromisoformat(created_at_str)
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return 1.0

        age_days = (now - created).total_seconds() / 86400.0
        if age_days <= 0:
            return 1.0
        age_months = age_days / _DAYS_PER_MONTH
        factor = _RECENCY_DECAY_PER_MONTH ** age_months
        return max(_RECENCY_MIN_FACTOR, factor)

    @staticmethod
    def _payload_to_entry(payload: dict[str, Any], point_id: str) -> MemoryEntry:
        """将 Qdrant payload 字典转换为 :class:`MemoryEntry`。"""
        memory_id = payload.get("memory_id", point_id)
        memory_type_str = payload.get("memory_type", "context")
        try:
            memory_type = MemoryType(memory_type_str)
        except ValueError:
            memory_type = MemoryType.CONTEXT

        session_id = payload.get("session_id")
        expires_at_str = payload.get("expires_at")
        expires_at: datetime | None = None
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str)
            except (ValueError, TypeError):
                expires_at = None

        created_at_str = payload.get("created_at", "")
        created_at = datetime.now(timezone.utc)
        if created_at_str:
            try:
                created_at = datetime.fromisoformat(created_at_str)
            except (ValueError, TypeError):
                pass

        return MemoryEntry(
            id=str(memory_id),
            agent_name=payload.get("agent_name", ""),
            session_id=session_id,
            user_id=payload.get("user_id"),
            memory_type=memory_type,
            content=payload.get("content", ""),
            importance=float(payload.get("importance", 0.5)),
            metadata={},
            expires_at=expires_at,
            created_at=created_at,
            updated_at=created_at,
        )

    # ==================================================================
    # 生命周期
    # ==================================================================

    async def close(self) -> None:
        """关闭 Qdrant 客户端连接。"""
        await self._qdrant.close()


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """返回单例 MemoryManager 实例。"""
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
