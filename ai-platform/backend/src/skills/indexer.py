"""
VectorIndexer — 构建和维护 Skills 的 Qdrant 向量索引。

使用本地 Embedding 服务（bge-small-zh-v1.5）生成 512 维
向量，并将其 upsert 到 ``skills_index`` Qdrant 集合中。
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import httpx
import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models as qdrant_models

from src.config import get_settings

if TYPE_CHECKING:
    from qdrant_client.http.models import PointStruct

    from src.skills.models import Skill

logger = structlog.get_logger(__name__)


class VectorIndexer:
    """管理 Skills 的 Qdrant 向量索引。"""

    def __init__(
        self,
        qdrant_client: AsyncQdrantClient | None = None,
        embedding_url: str | None = None,
    ) -> None:
        """初始化 Qdrant 向量索引器。

        Args:
            qdrant_client: 可选的 Qdrant 异步客户端。
            embedding_url: 可选的 Embedding 服务根 URL。
        """
        self._settings = get_settings()
        self._qdrant: AsyncQdrantClient = qdrant_client or AsyncQdrantClient(
            url=self._settings.qdrant_url,
            api_key=self._settings.QDRANT_API_KEY or None,
        )
        self._embedding_url = embedding_url or self._settings.EMBEDDING_SERVICE_URL
        self._collection_name = self._settings.QDRANT_COLLECTION_SKILLS
        self._vector_size = self._settings.EMBEDDING_DIMENSION
        self._collection_ready = False

    async def ensure_collection(self) -> None:
        """如果 Qdrant 集合不存在则创建。"""
        if self._collection_ready:
            return
        try:
            collections: Any = await self._qdrant.get_collections()
            names: list[Any] = [c.name for c in collections.collections]
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
                logger.info(
                    "Qdrant collection created",
                    collection=self._collection_name,
                    vector_size=self._vector_size,
                )
            self._collection_ready = True
        except Exception:
            logger.exception(
                "Failed to ensure Qdrant collection",
                collection=self._collection_name,
            )
            raise

    async def generate_embedding(self, text: str) -> list[float]:
        """调用本地 Embedding 服务为 *text* 生成向量。"""
        url: str = f"{self._embedding_url}/embed"
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp: Any = await client.post(url, json={"text": text})
            resp.raise_for_status()
            data: Any = resp.json()
            return data.get("embedding", data.get("vector", []))

    async def index_skill(self, skill: Skill) -> None:
        """为 *skill* 生成 embedding 并 upsert 到 Qdrant。"""
        await self.ensure_collection()
        text: str = skill.index_text()
        try:
            vector: list[float] = await self.generate_embedding(text)
        except Exception:
            logger.exception(
                "Failed to generate embedding for skill",
                skill_id=skill.skill_id,
            )
            return

        skill.embedding = vector

        point: PointStruct = qdrant_models.PointStruct(
            id=skill.skill_id,
            vector=vector,
            payload={
                "skill_id": skill.skill_id,
                "name": skill.name,
                "category": skill.category,
                "status": (
                    skill.status.value
                    if hasattr(skill.status, "value")
                    else str(skill.status)
                ),
                "version": skill.version,
                "tags": skill.tags,
                "source": (
                    skill.source.value
                    if hasattr(skill.source, "value")
                    else str(skill.source)
                ),
            },
        )
        await self._qdrant.upsert(
            collection_name=self._collection_name,
            points=[point],
        )
        logger.debug("Skill indexed", skill_id=skill.skill_id, category=skill.category)

    async def reindex_all(self, skills: list[Skill]) -> int:
        """为所有 *skills* 重新生成 embedding 并重建索引。

        返回成功建立索引的 Skill 数量。
        """
        await self.ensure_collection()
        count: int = 0
        for skill in skills:
            try:
                await self.index_skill(skill)
                count += 1
            except Exception:
                logger.exception(
                    "Failed to reindex skill", skill_id=skill.skill_id
                )
        logger.info("Reindex complete", indexed=count, total=len(skills))
        return count

    async def update_payload(self, skill_id: str, payload: dict) -> None:
        """仅更新 payload 元数据，不重新生成向量。"""
        await self.ensure_collection()
        await self._qdrant.set_payload(
            collection_name=self._collection_name,
            payload=payload,
            points=[skill_id],
        )

    async def delete_index(self, skill_id: str) -> None:
        """从 Qdrant 索引中移除某个 Skill 的向量。"""
        await self.ensure_collection()
        try:
            await self._qdrant.delete(
                collection_name=self._collection_name,
                points_selector=qdrant_models.PointIdsList(
                    points=[skill_id],
                ),
            )
            logger.info("Skill index deleted", skill_id=skill_id)
        except Exception:
            logger.exception("Failed to delete skill index", skill_id=skill_id)

    async def search(
        self,
        query_vector: list[float],
        top_n: int = 50,
        category_filter: list[str] | None = None,
    ) -> list[dict]:
        """在 Qdrant 索引中搜索 *query_vector* 的最近邻。

        返回包含 ``skill_id``、``score`` 和 ``payload`` 的字典列表。
        """
        await self.ensure_collection()

        must_conditions: list[qdrant_models.FieldCondition] = [
            qdrant_models.FieldCondition(
                key="status",
                match=qdrant_models.MatchValue(value="active"),
            ),
        ]
        if category_filter:
            must_conditions.append(
                qdrant_models.FieldCondition(
                    key="category",
                    match=qdrant_models.MatchAny(any=category_filter),
                )
            )

        results: list[dict] = await self._qdrant.search(
            collection_name=self._collection_name,
            query_vector=query_vector,
            limit=top_n,
            query_filter=qdrant_models.Filter(must=must_conditions),
            with_payload=True,
        )

        return [
            {
                "skill_id": hit.payload.get("skill_id", hit.id),
                "score": hit.score,
                "payload": hit.payload,
            }
            for hit in results
        ]

    async def close(self) -> None:
        """关闭 Qdrant 客户端连接。"""
        await self._qdrant.close()
