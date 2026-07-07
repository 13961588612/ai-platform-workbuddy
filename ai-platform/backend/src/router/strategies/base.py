"""RoutingStrategy 抽象基类 — 定义策略接口契约。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.router.models import RouteResult, SessionContext, UserRequest


class RoutingStrategy(ABC):
    """
    路由策略的抽象接口。

    每个策略实现 route() 方法，如果策略匹配则返回 RouteResult，
    否则返回 None 以推迟到链中的下一个策略。

    策略按优先级排序（1 = 最高优先级）。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称标识符。"""
        ...

    @property
    @abstractmethod
    def priority(self) -> int:
        """优先级（1 = 最高，优先评估）。"""
        ...

    @abstractmethod
    async def route(
        self,
        request: UserRequest,
        candidates: list[Any],
        session_ctx: SessionContext,
    ) -> RouteResult | None:
        """
        执行路由逻辑。

        Args:
            request: 用户请求。
            candidates: AgentConfig 候选列表。
            session_ctx: 当前会话上下文。

        Returns:
            如果匹配则返回 RouteResult，否则返回 None 以推迟到下一个策略。
        """
        ...

    @abstractmethod
    def is_applicable(
        self,
        request: UserRequest,
        session_ctx: SessionContext,
    ) -> bool:
        """
        检查此策略是否适用于给定请求。

        Args:
            request: 用户请求。
            session_ctx: 当前会话上下文。

        Returns:
            如果应评估此策略则返回 True。
        """
        ...
