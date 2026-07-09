"""RouteLogger — 将路由决策持久化到 PostgreSQL 以实现可观测性。

将每次路由决策（匹配的 Agent、使用的策略、置信度、
延迟）记录到 route_logs 表中，使管理后台能够
显示路由统计信息、Agent 流量分布和策略命中率分析。
"""

from __future__ import annotations
from typing import Any

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import db_session_context
from src.models.session import RouteLogModel
from src.router.models import RouteLog, RouteLogFilter, RouteResult, RouteStats, UserRequest
from src.utils.logging import get_logger

logger = get_logger("router.route_logger")


class RouteLogger:
    """
    将路由决策记录到数据库。

    提供写入（log_route）和读取（query_logs、get_stats）
    操作，用于路由可观测性。
    """

    async def log_route(
        self,
        request: UserRequest,
        result: RouteResult,
    ) -> None:
        """
        将路由决策持久化到数据库。

        Args:
            request: 原始用户请求。
            result: AgentRouter 产生的路由决策。
        """
        # 根据 schema 将输入文本截断为前 200 个字符
        truncated_text: Any = request.text[:200]

        route_log: RouteLogModel = RouteLogModel(
            id=uuid.uuid4(),
            session_id=request.session_id,
            user_id=request.user_id,
            input_text=truncated_text,
            matched_agent_id=result.agent_id,
            strategy_used=result.strategy_used,
            confidence=result.confidence,
            latency_ms=result.latency_ms,
            timestamp=datetime.now(timezone.utc),
        )

        try:
            async with db_session_context() as session:
                session.add(route_log)
                await session.commit()
            logger.debug(
                "Route logged",
                session_id=request.session_id,
                agent_id=result.agent_id,
                strategy=result.strategy_used,
            )
        except Exception as exc:
            logger.error("Failed to log route", error=str(exc), session_id=request.session_id)

    async def query_logs(
        self,
        filter_obj: RouteLogFilter,
    ) -> list[RouteLog]:
        """
        带过滤条件查询路由日志。

        Args:
            filter_obj: 过滤条件（session_id、user_id、agent_id 等）

        Returns:
            匹配的 RouteLog 条目列表。
        """
        async with db_session_context() as session:
            stmt: Any = select(RouteLogModel).order_by(RouteLogModel.timestamp.desc())

            if filter_obj.session_id:
                stmt: Any = stmt.where(RouteLogModel.session_id == filter_obj.session_id)
            if filter_obj.user_id:
                stmt: Any = stmt.where(RouteLogModel.user_id == filter_obj.user_id)
            if filter_obj.agent_id:
                stmt: Any = stmt.where(RouteLogModel.matched_agent_id == filter_obj.agent_id)
            if filter_obj.strategy:
                stmt: Any = stmt.where(RouteLogModel.strategy_used == filter_obj.strategy)
            if filter_obj.start_time:
                stmt: Any = stmt.where(RouteLogModel.timestamp >= filter_obj.start_time)
            if filter_obj.end_time:
                stmt: Any = stmt.where(RouteLogModel.timestamp <= filter_obj.end_time)

            stmt: Any = stmt.limit(filter_obj.limit).offset(filter_obj.offset)
            result: ToolResult = await session.execute(stmt)
            rows: Any = result.scalars().all()

        return [
            RouteLog(
                id=str(row.id),
                session_id=row.session_id,
                user_id=row.user_id,
                input_text=row.input_text,
                matched_agent_id=row.matched_agent_id,
                strategy_used=row.strategy_used,
                confidence=row.confidence,
                latency_ms=row.latency_ms,
                timestamp=row.timestamp,
            )
            for row in rows
        ]

    async def get_stats(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> RouteStats:
        """
        计算聚合的路由统计信息。

        Args:
            start_time: 可选的时间范围起始时间。
            end_time: 可选的时间范围结束时间。

        Returns:
            包含流量分布和性能指标的 RouteStats。
        """
        async with db_session_context() as session:
            stmt: Any = select(RouteLogModel)
            if start_time:
                stmt: Any = stmt.where(RouteLogModel.timestamp >= start_time)
            if end_time:
                stmt: Any = stmt.where(RouteLogModel.timestamp <= end_time)

            result: ToolResult = await session.execute(stmt)
            rows: Any = result.scalars().all()

        if not rows:
            return RouteStats()

        by_agent: dict[str, int] = {}
        by_strategy: dict[str, int] = {}
        total_latency: float = 0.0
        total_confidence: float = 0.0

        for row in rows:
            by_agent[row.matched_agent_id] = by_agent.get(row.matched_agent_id, 0) + 1
            by_strategy[row.strategy_used] = by_strategy.get(row.strategy_used, 0) + 1
            total_latency += row.latency_ms
            total_confidence += row.confidence

        count: Any = len(rows)
        return RouteStats(
            total_routes=count,
            by_agent=by_agent,
            by_strategy=by_strategy,
            avg_latency_ms=round(total_latency / count, 2),
            avg_confidence=round(total_confidence / count, 4),
        )


# 单例实例
_route_logger: RouteLogger | None = None


def get_route_logger() -> RouteLogger:
    """返回单例 RouteLogger 实例。"""
    global _route_logger
    if _route_logger is None:
        _route_logger = RouteLogger()
    return _route_logger
