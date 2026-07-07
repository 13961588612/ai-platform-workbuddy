"""API 包 — FastAPI 路由处理器与依赖注入。"""

from src.api.deps import (
    get_agent_manager_dep,
    get_config_manager_dep,
    get_llm_gateway_dep,
    get_session_manager_dep,
)

__all__ = [
    "get_agent_manager_dep",
    "get_config_manager_dep",
    "get_llm_gateway_dep",
    "get_session_manager_dep",
]
