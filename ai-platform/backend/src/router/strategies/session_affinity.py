"""SessionAffinityStrategy — 基于会话→Agent 绑定进行路由。

如果会话在 Redis 中已有 Agent 绑定，则复用相同的 Agent。
这确保了会话内的对话连续性。
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from src.config import get_settings
from src.router.models import RouteResult, SessionContext, UserRequest
from src.router.strategies.base import RoutingStrategy
from src.utils.logging import get_logger

logger = get_logger("router.session_affinity")


class SessionAffinityStrategy(RoutingStrategy):
    """
    将会话路由到之前绑定的 Agent。

    检查 Redis 键 `session:{sessionId}:agent_binding` 是否存在绑定。
    如果找到且该 Agent 仍然启用，则路由到它。
    """

    def __init__(self) -> None:
        """初始化会话亲和策略（Redis 连接懒创建）。"""
        self._redis: aioredis.Redis | None = None
        self._settings = get_settings()

    @property
    def name(self) -> str:
        """策略标识符：``session_affinity``。"""
        return "session_affinity"

    @property
    def priority(self) -> int:
        """策略优先级（1 = 最高，最先尝试）。"""
        return 1

    async def _get_redis(self) -> aioredis.Redis:
        """获取或创建 Redis 连接。"""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._settings.redis_url,
                decode_responses=True,
            )
        return self._redis

    async def route(
        self,
        request: UserRequest,
        candidates: list[Any],
        session_ctx: SessionContext,
    ) -> RouteResult | None:
        """检查现有的会话→Agent 绑定。"""
        redis = await self._get_redis()
        binding_key = f"session:{request.session_id}:agent_binding"
        bound_agent_id = await redis.get(binding_key)

        if bound_agent_id is None:
            return None

        # 验证绑定的 Agent 是否仍然启用
        bound_agent = next(
            (c for c in candidates if c.agent_id == bound_agent_id and c.routing.enabled),
            None,
        )

        if bound_agent is None:
            logger.info(
                "Session affinity: bound agent not available",
                session_id=request.session_id,
                bound_agent_id=bound_agent_id,
            )
            return None

        logger.info(
            "Session affinity match",
            session_id=request.session_id,
            agent_id=bound_agent_id,
        )

        return RouteResult(
            agent_id=bound_agent_id,
            strategy_used=self.name,
            confidence=1.0,
            metadata={"reason": "session_affinity"},
        )

    def is_applicable(
        self,
        request: UserRequest,
        session_ctx: SessionContext,
    ) -> bool:
        """始终适用 — 首先检查现有绑定。"""
        return True
