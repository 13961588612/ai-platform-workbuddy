"""FastAPI 依赖注入提供者。

通过 FastAPI 的 Depends() 机制向路由处理器提供核心服务的单例实例。
"""

from __future__ import annotations
from typing import Any


from fastapi import Depends, Header, HTTPException, status

from src.agent.manager import AgentManager, get_agent_manager
from src.agent.session import SessionManager, get_session_manager
from src.config_manager.manager import ConfigManager, get_config_manager
from src.identity.token import TokenError, TokenManager
from src.llm.gateway import LLMGateway, get_llm_gateway
from src.router.agent_router import AgentRouter, get_agent_router
from src.router.route_logger import RouteLogger, get_route_logger
from src.utils.logging import get_logger

logger = get_logger("api.deps")


def get_agent_manager_dep() -> AgentManager:
    """提供单例 AgentManager。"""
    return get_agent_manager()


def get_session_manager_dep() -> SessionManager:
    """提供单例 SessionManager。"""
    return get_session_manager()


def get_config_manager_dep() -> ConfigManager:
    """提供单例 ConfigManager。"""
    return get_config_manager()


def get_llm_gateway_dep() -> LLMGateway:
    """提供单例 LLMGateway。"""
    return get_llm_gateway()


def get_agent_router_dep() -> AgentRouter:
    """提供单例 AgentRouter。"""
    return get_agent_router()


def get_route_logger_dep() -> RouteLogger:
    """提供单例 RouteLogger。"""
    return get_route_logger()


async def get_current_user(
    authorization: str = Header(default=""),
) -> dict[str, Any]:
    """
    从 Authorization 头部提取并验证 JWT token。

    Returns:
        包含 user_id、name、department、role 等字段的字典。

    Raises:
        HTTPException: token 缺失或无效时返回 401。
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
        )

    token: Any = authorization[7:]  # 去掉 "Bearer " 前缀
    try:
        token_manager: TokenManager = TokenManager()
        payload: TokenPayload = token_manager.verify_access_token(token)
        return payload.model_dump()
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {exc}",
        )
    except Exception as exc:
        logger.error("Token validation failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
        )


async def get_trace_id(
    x_trace_id: str = Header(default=""),
) -> str:
    """从请求头部提取 trace ID。"""
    return x_trace_id
