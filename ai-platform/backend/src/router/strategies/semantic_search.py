"""SemanticSearchStrategy — 基于语义相似度进行路由。

使用 bge-small-zh-v1.5 对用户输入文本进行嵌入，并搜索
Qdrant agent_router_index 集合以找到最相似的 Agent。
需要 Top-1 相似度 > 0.75 才能匹配。
"""

from __future__ import annotations

from typing import Any

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import SearchParams

from src.config import get_settings
from src.router.models import AgentScore, RouteResult, SessionContext, UserRequest
from src.router.strategies.base import RoutingStrategy
from src.utils.logging import get_logger

logger = get_logger("router.semantic_search")

# 语义匹配的相似度阈值
SEMANTIC_MATCH_THRESHOLD: float = 0.75


class SemanticSearchStrategy(RoutingStrategy):
    """
    基于用户输入与 Agent 元数据之间的语义相似度进行路由。

    使用 bge-small-zh-v1.5 嵌入（768 维）和 Qdrant agent_router_index
    集合来找到最相似的 Agent。
    """

    def __init__(self) -> None:
        """从配置初始化 Qdrant 与 Embedding 服务连接参数。"""
        self._settings = get_settings()
        self._qdrant: QdrantClient | None = None
        self._embedding_url: str = self._settings.EMBEDDING_SERVICE_URL
        self._collection: str = self._settings.QDRANT_COLLECTION_AGENT_ROUTER
        self._top_k: int = self._settings.AGENT_ROUTER_SEMANTIC_TOP_K

    @property
    def name(self) -> str:
        """策略标识符：``semantic_retrieval``。"""
        return "semantic_retrieval"

    @property
    def priority(self) -> int:
        """策略优先级（3 = 关键词匹配之后）。"""
        return 3

    def _get_qdrant(self) -> QdrantClient:
        """获取或创建 Qdrant 客户端。"""
        if self._qdrant is None:
            self._qdrant = QdrantClient(
                url=self._settings.qdrant_url,
                api_key=self._settings.QDRANT_API_KEY or None,
            )
        return self._qdrant

    async def route(
        self,
        request: UserRequest,
        candidates: list[Any],
        session_ctx: SessionContext,
    ) -> RouteResult | None:
        """嵌入用户输入并搜索 Qdrant 以查找匹配的 Agent。"""
        try:
            scores = await self.embed_and_search(request.text, self._top_k)
        except Exception as exc:
            logger.error("Semantic search failed", error=str(exc))
            return None

        if not scores:
            return None

        top_score = scores[0]

        if top_score.score < SEMANTIC_MATCH_THRESHOLD:
            logger.info(
                "Semantic search below threshold",
                top_score=top_score.score,
                threshold=SEMANTIC_MATCH_THRESHOLD,
                agent_id=top_score.agent_id,
            )
            return None

        # 验证匹配的 Agent 是否在候选列表中
        matched = next(
            (c for c in candidates if c.agent_id == top_score.agent_id and c.routing.enabled),
            None,
        )
        if matched is None:
            return None

        logger.info(
            "Semantic search match",
            agent_id=top_score.agent_id,
            score=top_score.score,
        )

        return RouteResult(
            agent_id=top_score.agent_id,
            strategy_used=self.name,
            confidence=top_score.score,
            metadata={
                "reason": "semantic_match",
                "top_k_scores": [
                    {"agent_id": s.agent_id, "score": s.score} for s in scores[:3]
                ],
            },
        )

    def is_applicable(
        self,
        request: UserRequest,
        session_ctx: SessionContext,
    ) -> bool:
        """当存在有意义的输入文本时适用。"""
        return len(request.text.strip()) >= 2

    async def embed_and_search(self, text: str, top_k: int) -> list[AgentScore]:
        """
        嵌入输入文本并搜索 Qdrant 以查找相似的 Agent。

        Args:
            text: 要嵌入并搜索的用户输入文本。
            top_k: 要返回的 top 结果数量。

        Returns:
            按相似度降序排列的 AgentScore 对象列表。
        """
        # 第 1 步：通过本地嵌入服务生成嵌入向量
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._embedding_url}/embed",
                json={"texts": [text], "batch_size": 1},
            )
            response.raise_for_status()
            data = response.json()
            embedding: list[float] = data["embeddings"][0]

        # 第 2 步：搜索 Qdrant
        qdrant = self._get_qdrant()
        search_results = qdrant.search(
            collection_name=self._collection,
            query_vector=embedding,
            limit=top_k,
            search_params=SearchParams(hnsw_ef=128, exact=False),
            query_filter=None,
        )

        # 第 3 步：转换为 AgentScore 列表
        scores: list[AgentScore] = []
        for result in search_results:
            payload = result.payload or {}
            scores.append(
                AgentScore(
                    agent_id=payload.get("agent_id", ""),
                    score=result.score,
                    description=payload.get("description", ""),
                    tags=payload.get("tags", []),
                )
            )

        return scores
