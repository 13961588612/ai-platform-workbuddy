"""DefaultFallbackStrategy — 最后手段的路由策略（优先级 4）。

始终路由到配置的默认 Agent，确保每个用户请求
即使没有其他策略匹配也能获得响应。
"""

from __future__ import annotations

from typing import Any

from src.config import get_settings
from src.router.models import RouteResult, SessionContext, UserRequest
from src.router.strategies.base import RoutingStrategy
from src.utils.logging import get_logger

logger = get_logger("router.default_fallback")


class DefaultFallbackStrategy(RoutingStrategy):
    """
    路由到配置的默认 Agent。

    此策略始终适用且始终产生匹配，
    确保用户请求永远不会无法路由。
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._default_agent_id: str = self._settings.AGENT_ROUTER_DEFAULT_AGENT

    @property
    def name(self) -> str:
        return "default_fallback"

    @property
    def priority(self) -> int:
        return 4

    async def route(
        self,
        request: UserRequest,
        candidates: list[Any],
        session_ctx: SessionContext,
    ) -> RouteResult | None:
        """路由到默认 Agent（始终返回结果）。"""
        logger.info(
            "Default fallback routing",
            default_agent=self._default_agent_id,
            session_id=request.session_id,
        )
        return RouteResult(
            agent_id=self._default_agent_id,
            strategy_used=self.name,
            confidence=0.0,
            metadata={
                "reason": "default_fallback",
                "candidates_count": len(candidates),
            },
        )

    def is_applicable(
        self,
        request: UserRequest,
        session_ctx: SessionContext,
    ) -> bool:
        """始终适用 — 这是最后手段的策略。"""
        return True
