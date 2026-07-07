"""AgentRouter — 主路由入口点。

实现四级策略链：
  1. SessionAffinityStrategy（优先级 1）— Redis 会话→Agent 绑定
  2. KeywordMatchStrategy（优先级 2）— 关键词子串匹配
  3. SemanticSearchStrategy（优先级 3）— Qdrant 向量相似度搜索
  4. DefaultFallbackStrategy（优先级 4）— 默认 Agent 回退

按优先级顺序尝试各策略；第一个返回非 None RouteResult 的策略胜出。
结果会缓存到 Redis（会话→Agent 绑定，TTL 24h），并通过 RouteLogger 记录到 PostgreSQL。
"""

from __future__ import annotations

import time
from typing import Any

from src.agent.config import AgentConfig
from src.agent.session import get_session_manager
from src.router.models import RouteResult, SessionContext, UserRequest
from src.router.route_logger import get_route_logger
from src.router.strategies.base import RoutingStrategy
from src.router.strategies.default_fallback import DefaultFallbackStrategy
from src.router.strategies.keyword_match import KeywordMatchStrategy
from src.router.strategies.semantic_search import SemanticSearchStrategy
from src.router.strategies.session_affinity import SessionAffinityStrategy
from src.utils.logging import get_logger

logger = get_logger("router.agent_router")


class AgentRouter:
    """
    主路由协调器 — 应用四级策略链。

    持有按优先级排序的路由策略列表。对于每个传入请求，
    它会遍历策略并返回第一个匹配结果。结果将作为会话→Agent 绑定
    持久化到 Redis，并记录到 PostgreSQL。
    """

    def __init__(self) -> None:
        self._strategies: list[RoutingStrategy] = [
            SessionAffinityStrategy(),
            KeywordMatchStrategy(),
            SemanticSearchStrategy(),
            DefaultFallbackStrategy(),
        ]
        # 确保策略按优先级排序（1 为最高）
        self._strategies.sort(key=lambda s: s.priority)
        self._candidates: list[AgentConfig] = []
        self._route_logger = get_route_logger()
        self._session_manager = get_session_manager()

    def set_candidates(self, candidates: list[AgentConfig]) -> None:
        """
        设置用于路由的候选 Agent 配置列表。

        由 ConfigManager 在配置加载或更新时调用。
        """
        self._candidates = candidates
        logger.info("Router candidates updated", count=len(candidates))

    def add_candidate(self, config: AgentConfig) -> None:
        """添加单个 Agent 配置作为路由候选。"""
        # 移除已存在的相同 agent_id 的条目（如有）
        self._candidates = [
            c for c in self._candidates if c.agent_id != config.agent_id
        ]
        self._candidates.append(config)
        logger.info("Router candidate added", agent_id=config.agent_id)

    def remove_candidate(self, agent_id: str) -> None:
        """从路由候选中移除一个 Agent 配置。"""
        self._candidates = [
            c for c in self._candidates if c.agent_id != agent_id
        ]
        logger.info("Router candidate removed", agent_id=agent_id)

    async def route(
        self,
        request: UserRequest,
    ) -> RouteResult:
        """
        将用户请求路由到最合适的 Agent。

        按优先级顺序尝试每个策略。第一个返回非 None RouteResult 的策略胜出。
        然后结果会：
        1. 作为会话→Agent 绑定缓存到 Redis（TTL 24h）
        2. 通过 RouteLogger 记录到 PostgreSQL

        Args:
            request: 用户的传入请求。

        Returns:
            包含匹配的 agent_id、策略和置信度的 RouteResult。

        Raises:
            此方法始终返回 RouteResult，因为 DefaultFallbackStrategy 始终匹配。
        """
        start_time = time.monotonic()

        # 构建会话上下文
        session_ctx = SessionContext(
            session_id=request.session_id,
            user_id=request.user_id,
            channel=request.channel,
        )

        # Try existing session binding first (also captured by strategy 1)
        existing_binding = await self._session_manager.get_agent_binding(
            request.session_id
        )
        if existing_binding:
            session_ctx.existing_agent_id = existing_binding

        result: RouteResult | None = None

        for strategy in self._strategies:
            if not strategy.is_applicable(request, session_ctx):
                continue

            try:
                result = await strategy.route(
                    request=request,
                    candidates=self._candidates,
                    session_ctx=session_ctx,
                )
            except Exception as exc:
                logger.error(
                    "Strategy failed",
                    strategy=strategy.name,
                    error=str(exc),
                )
                continue

            if result is not None:
                logger.info(
                    "Route matched",
                    strategy=strategy.name,
                    agent_id=result.agent_id,
                    confidence=result.confidence,
                    session_id=request.session_id,
                )
                break

        # DefaultFallbackStrategy 保证有结果，但加上保护以防万一
        if result is None:
            fallback = DefaultFallbackStrategy()
            result = await fallback.route(
                request=request,
                candidates=self._candidates,
                session_ctx=session_ctx,
            )

        # 计算延迟
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        result.latency_ms = elapsed_ms

        # 将绑定缓存到 Redis（置信度为 0 的默认回退则跳过）
        if result.confidence > 0:
            await self._session_manager.set_agent_binding(
                request.session_id,
                result.agent_id,
            )

        # 记录路由决策
        await self._route_logger.log_route(request, result)

        return result

    def get_strategies(self) -> list[RoutingStrategy]:
        """返回已注册的策略列表（用于内省/调试）。"""
        return list(self._strategies)


# 单例实例
_agent_router: AgentRouter | None = None


def get_agent_router() -> AgentRouter:
    """返回单例 AgentRouter 实例。"""
    global _agent_router
    if _agent_router is None:
        _agent_router = AgentRouter()
    return _agent_router
