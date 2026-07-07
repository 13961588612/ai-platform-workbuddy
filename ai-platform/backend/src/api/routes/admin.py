"""Admin API 路由 — 系统监控、路由日志和 LLM 网关状态。

端点：
- GET  /api/v1/admin/health              — 系统健康概览
- GET  /api/v1/admin/route-logs          — 查询路由决策日志
- GET  /api/v1/admin/route-stats         — 路由统计仪表板
- GET  /api/v1/admin/llm/status          — LLM 网关状态
- GET  /api/v1/admin/llm/token-usage     — token 用量摘要
- GET  /api/v1/admin/llm/quota/{user_id} — 用户配额信息
- POST /api/v1/admin/llm/quota/{user_id}/reset — 重置用户配额
- GET  /api/v1/admin/proxy/status        — 出站代理池状态
- POST /api/v1/admin/failover/reset      — 重置故障转移到主节点
- GET  /api/v1/admin/configs             — 列出所有 Agent 配置
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field

from src.api.deps import (
    get_config_manager_dep,
    get_llm_gateway_dep,
    get_route_logger_dep,
)
from src.api.response import error_response, success
from src.config_manager.manager import ConfigManager
from src.llm.gateway import LLMGateway
from src.llm.quota_manager import QuotaManager, get_quota_manager
from src.router.models import RouteLogFilter
from src.router.route_logger import RouteLogger
from src.utils.logging import get_logger

logger = get_logger("api.routes.admin")

router = APIRouter(prefix="/admin", tags=["admin"])


# ===== 请求/响应模型 =====


class RouteLogQuery(BaseModel):
    """路由日志查询参数。"""

    session_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    strategy: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# ===== 端点 =====


@router.get("/health")
async def system_health(
    llm_gateway: LLMGateway = Depends(get_llm_gateway_dep),
) -> dict[str, Any]:
    """获取所有子系统的整体健康概览。"""
    try:
        llm_status = llm_gateway.get_status()
        return success(
            data={
                "llm_gateway": {
                    "initialized": llm_status["initialized"],
                    "active_provider": llm_status["failover"]["active_provider"],
                    "is_failover_active": llm_status["failover"]["is_failover_active"],
                },
                "proxy_nodes": len(llm_status.get("proxy_pool", [])),
                "healthy_proxy_nodes": sum(
                    1 for n in llm_status.get("proxy_pool", []) if n.get("is_healthy")
                ),
            }
        )
    except Exception as exc:
        logger.error("Health check failed", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/route-logs")
async def get_route_logs(
    session_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    agent_id: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    route_logger: RouteLogger = Depends(get_route_logger_dep),
) -> dict[str, Any]:
    """按条件筛选查询路由决策日志。"""
    try:
        filter_obj = RouteLogFilter(
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
            strategy=strategy,
            limit=limit,
            offset=offset,
        )
        logs = await route_logger.query_logs(filter_obj)
        return success(
            data=[log.model_dump() for log in logs],
            message=f"Found {len(logs)} route logs",
        )
    except Exception as exc:
        logger.error("Failed to query route logs", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/route-stats")
async def get_route_stats(
    route_logger: RouteLogger = Depends(get_route_logger_dep),
) -> dict[str, Any]:
    """获取仪表板所用的聚合路由统计数据。"""
    try:
        stats = await route_logger.get_stats()
        return success(data=stats.model_dump())
    except Exception as exc:
        logger.error("Failed to get route stats", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/llm/status")
async def get_llm_status(
    llm_gateway: LLMGateway = Depends(get_llm_gateway_dep),
) -> dict[str, Any]:
    """获取当前 LLM 网关状态，包括故障转移和代理信息。"""
    try:
        status_info = llm_gateway.get_status()
        return success(data=status_info)
    except Exception as exc:
        logger.error("Failed to get LLM status", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/llm/token-usage")
async def get_token_usage(
    user_id: str | None = Query(default=None),
    department: str | None = Query(default=None),
    model: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    llm_gateway: LLMGateway = Depends(get_llm_gateway_dep),
) -> dict[str, Any]:
    """按可选条件筛选获取 token 用量记录。"""
    try:
        from src.llm.token_tracker import get_token_tracker

        tracker = get_token_tracker()
        records = await tracker.query_usage(
            user_id=user_id,
            dept=department,
            model=model,
            limit=limit,
            offset=offset,
        )
        return success(data=records)
    except Exception as exc:
        logger.error("Failed to get token usage", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/llm/token-summary")
async def get_token_summary(
    user_id: str | None = Query(default=None),
    department: str | None = Query(default=None),
) -> dict[str, Any]:
    """获取聚合 token 用量摘要。"""
    try:
        from src.llm.token_tracker import get_token_tracker

        tracker = get_token_tracker()
        summary = await tracker.get_summary(user_id=user_id, dept=department)
        return success(data=summary)
    except Exception as exc:
        logger.error("Failed to get token summary", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/llm/quota/{user_id}")
async def get_user_quota(
    user_id: str,
    department: str = Query(default=""),
) -> dict[str, Any]:
    """获取用户的当前 token 配额信息。"""
    try:
        quota_manager = get_quota_manager()
        info = await quota_manager.get_quota_info(user_id, department)
        return success(data=info.model_dump())
    except Exception as exc:
        logger.error("Failed to get quota info", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/llm/quota/{user_id}/reset")
async def reset_user_quota(
    user_id: str,
) -> dict[str, Any]:
    """重置用户的每日 token 配额（管理员覆盖）。"""
    try:
        quota_manager = get_quota_manager()
        await quota_manager.reset_quota(user_id)
        return success(message=f"Quota reset for user {user_id}")
    except Exception as exc:
        logger.error("Failed to reset quota", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/proxy/status")
async def get_proxy_status(
    llm_gateway: LLMGateway = Depends(get_llm_gateway_dep),
) -> dict[str, Any]:
    """获取出站代理池状态。"""
    try:
        status_info = llm_gateway.get_status()
        return success(data=status_info.get("proxy_pool", []))
    except Exception as exc:
        logger.error("Failed to get proxy status", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/failover/reset")
async def reset_failover() -> dict[str, Any]:
    """将 LLM 故障转移管理器重置为使用主提供商。"""
    try:
        from src.llm.failover import get_failover_manager

        manager = get_failover_manager()
        manager.reset()
        return success(
            data={"active_provider": manager.active_provider},
            message="Failover reset to primary provider",
        )
    except Exception as exc:
        logger.error("Failed to reset failover", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/configs")
async def list_configs(
    config_manager: ConfigManager = Depends(get_config_manager_dep),
) -> dict[str, Any]:
    """列出所有 Agent 配置。"""
    try:
        configs = config_manager.list_configs()
        return success(
            data=[
                {
                    "agent_id": c.agent_id,
                    "display_name": c.display_name,
                    "description": c.description,
                    "version": c.version,
                    "runtime_type": c.runtime.type,
                    "model_primary": c.model.primary,
                    "model_fallback": c.model.fallback,
                    "routing_enabled": c.routing.enabled,
                    "routing_priority": c.routing.priority,
                    "routing_keywords": c.routing.keywords,
                }
                for c in configs
            ]
        )
    except Exception as exc:
        logger.error("Failed to list configs", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
