"""Agent API 路由 — CRUD 操作与生命周期管理。

端点：
- POST   /api/v1/agents              — 创建新 Agent
- GET    /api/v1/agents              — 列出所有 Agent
- GET    /api/v1/agents/{agent_id}   — 获取 Agent 详情
- PUT    /api/v1/agents/{agent_id}   — 更新 Agent 配置
- DELETE /api/v1/agents/{agent_id}   — 删除 Agent
- POST   /api/v1/agents/{agent_id}/start   — 启动 Agent
- POST   /api/v1/agents/{agent_id}/pause   — 暂停 Agent
- POST   /api/v1/agents/{agent_id}/resume  — 恢复 Agent
- POST   /api/v1/agents/{agent_id}/stop    — 停止 Agent
- GET    /api/v1/agents/{agent_id}/health  — 检查 Agent 健康状态
- POST   /api/v1/agents/{agent_id}/runtime — 切换运行时
"""

from __future__ import annotations
from typing import Any


from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.agent.config import AgentConfig
from src.agent.lifecycle import InstanceState
from src.agent.manager import AgentManager
from src.api.deps import get_agent_manager_dep, get_config_manager_dep, get_current_user
from src.api.response import error_response, success, success_response
from src.config_manager.manager import ConfigManager
from src.runtime.events import HealthStatus
from src.utils.exceptions import (
    AgentAlreadyExistsError,
    AgentNotFoundError,
    AgentNotRunningError,
    AgentStateError,
    ConfigValidationError,
)
from src.utils.logging import get_logger

logger = get_logger("api.routes.agent")

router = APIRouter(prefix="/agents", tags=["agents"])


# ===== 请求/响应模型 =====


class CreateAgentRequest(BaseModel):
    """创建新 Agent 的请求体。"""

    agent_id: str = Field(..., description="Agent ID（必须唯一）")
    display_name: str = Field(..., description="显示名称")
    description: str = Field(default="")
    version: str = Field(default="1.0.0")
    tags: list[str] = Field(default_factory=list)
    runtime_type: str = Field(default="openharness")
    model_primary: str = Field(default="deepseek-v4-flash")
    model_fallback: str = Field(default="qwen3.6-plus")
    keywords: list[str] = Field(default_factory=list)
    routing_enabled: bool = True
    routing_priority: int = 10


class UpdateAgentRequest(BaseModel):
    """更新 Agent 配置的请求体。"""

    display_name: str | None = None
    description: str | None = None
    version: str | None = None
    tags: list[str] | None = None
    keywords: list[str] | None = None
    routing_enabled: bool | None = None
    routing_priority: int | None = None


class SwitchRuntimeRequest(BaseModel):
    """切换 Agent 运行时的请求体。"""

    runtime_type: str = Field(..., description="新的运行时类型：openharness | custom | langgraph")


class AgentSummary(BaseModel):
    """列表响应中的 Agent 实例摘要。"""

    agent_id: str
    display_name: str
    state: str
    runtime_type: str
    active_sessions: int
    is_active: bool


class AgentDetail(BaseModel):
    """Agent 详细信息。"""

    agent_id: str
    display_name: str
    description: str
    version: str
    tags: list[str]
    state: str
    runtime_type: str
    active_sessions: int
    model_primary: str
    model_fallback: str
    routing_enabled: bool
    routing_priority: int
    routing_keywords: list[str]
    started_at: str | None = None


# ===== 端点 =====


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_agent(
    req: CreateAgentRequest,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    config_manager: ConfigManager = Depends(get_config_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """创建新 Agent 实例。"""
    try:
        # 从请求构建 AgentConfig
        from src.agent.config import (
            AccessControl,
            MCPServerConfig,
            MemoryConfig,
            ModelConfig,
            PushConfig,
            RoutingConfig,
            RuntimeConfig,
        )

        config: AgentConfig = AgentConfig(
            agent_id=req.agent_id,
            name=req.agent_id,
            display_name=req.display_name,
            description=req.description,
            version=req.version,
            tags=req.tags,
            runtime=RuntimeConfig(type=req.runtime_type),
            model=ModelConfig(primary=req.model_primary, fallback=req.model_fallback),
            routing=RoutingConfig(
                keywords=req.keywords,
                enabled=req.routing_enabled,
                priority=req.routing_priority,
            ),
        )

        # 保存配置
        await config_manager.save_config(config)

        # 创建 agent 实例
        instance: dict[str, Any] = await agent_manager.create_agent(config)

        return success(
            data={"agent_id": req.agent_id, "state": instance.lifecycle.current_state.value},
            message="Agent created successfully",
        )
    except AgentAlreadyExistsError as exc:
        return error_response(exc.code, exc.message, status.HTTP_409_CONFLICT)
    except ConfigValidationError as exc:
        return error_response(exc.code, exc.message, status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        logger.error("Failed to create agent", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("")
async def list_agents(
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """列出所有 Agent 实例。"""
    instances: dict[str, Any] = agent_manager.list_agents()
    summaries: list[dict[str, Any]] = [
        AgentSummary(
            agent_id=inst.id,
            display_name=inst.config.display_name,
            state=inst.lifecycle.current_state.value,
            runtime_type=inst.config.runtime.type,
            active_sessions=inst.active_sessions,
            is_active=inst.lifecycle.is_active(),
        ).model_dump()
        for inst in instances
    ]
    return success(data=summaries)


@router.get("/{agent_id}")
async def get_agent(
    agent_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """获取指定 Agent 的详细信息。"""
    try:
        instance: dict[str, Any] = agent_manager.get_agent(agent_id)
        config: Any = instance.config
        detail: AgentDetail = AgentDetail(
            agent_id=config.agent_id,
            display_name=config.display_name,
            description=config.description,
            version=config.version,
            tags=config.tags,
            state=instance.lifecycle.current_state.value,
            runtime_type=config.runtime.type,
            active_sessions=instance.active_sessions,
            model_primary=config.model.primary,
            model_fallback=config.model.fallback,
            routing_enabled=config.routing.enabled,
            routing_priority=config.routing.priority,
            routing_keywords=config.routing.keywords,
            started_at=instance.started_at.isoformat() if instance.started_at else None,
        )
        return success(data=detail.model_dump())
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)


@router.put("/{agent_id}")
async def update_agent(
    agent_id: str,
    req: UpdateAgentRequest,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    config_manager: ConfigManager = Depends(get_config_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """更新 Agent 配置（热重载）。"""
    try:
        instance: dict[str, Any] = agent_manager.get_agent(agent_id)
        config: Any = instance.config

        # 应用更新
        if req.display_name is not None:
            config.display_name = req.display_name
        if req.description is not None:
            config.description = req.description
        if req.version is not None:
            config.version = req.version
        if req.tags is not None:
            config.tags = req.tags
        if req.keywords is not None:
            config.routing.keywords = req.keywords
        if req.routing_enabled is not None:
            config.routing.enabled = req.routing_enabled
        if req.routing_priority is not None:
            config.routing.priority = req.routing_priority

        # 保存并热重载
        await config_manager.save_config(config)
        await agent_manager.update_config(agent_id, config)

        return success(message="Agent updated successfully")
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)
    except ConfigValidationError as exc:
        return error_response(exc.code, exc.message, status.HTTP_400_BAD_REQUEST)


@router.delete("/{agent_id}")
async def delete_agent(
    agent_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    config_manager: ConfigManager = Depends(get_config_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """删除 Agent 实例及其配置。"""
    try:
        await agent_manager.delete_agent(agent_id)
        await config_manager.delete_config(agent_id)
        return success(message="Agent deleted successfully")
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)


@router.post("/{agent_id}/start")
async def start_agent(
    agent_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """启动 Agent 实例。"""
    try:
        state: dict[str, Any] = await agent_manager.start_agent(agent_id)
        return success(
            data={"agent_id": agent_id, "state": state.value},
            message="Agent started",
        )
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)
    except AgentStateError as exc:
        return error_response(exc.code, exc.message, status.HTTP_409_CONFLICT)


@router.post("/{agent_id}/pause")
async def pause_agent(
    agent_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """暂停正在运行的 Agent 实例。"""
    try:
        state: dict[str, Any] = await agent_manager.pause_agent(agent_id)
        return success(
            data={"agent_id": agent_id, "state": state.value},
            message="Agent paused",
        )
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)
    except AgentStateError as exc:
        return error_response(exc.code, exc.message, status.HTTP_409_CONFLICT)


@router.post("/{agent_id}/resume")
async def resume_agent(
    agent_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """恢复已暂停的 Agent 实例。"""
    try:
        state: dict[str, Any] = await agent_manager.resume_agent(agent_id)
        return success(
            data={"agent_id": agent_id, "state": state.value},
            message="Agent resumed",
        )
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)
    except AgentStateError as exc:
        return error_response(exc.code, exc.message, status.HTTP_409_CONFLICT)


@router.post("/{agent_id}/stop")
async def stop_agent(
    agent_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """停止 Agent 实例。"""
    try:
        state: dict[str, Any] = await agent_manager.stop_agent(agent_id)
        return success(
            data={"agent_id": agent_id, "state": state.value},
            message="Agent stopped",
        )
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)


@router.get("/{agent_id}/health")
async def get_agent_health(
    agent_id: str,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """检查指定 Agent 的健康状态。"""
    try:
        health: dict[str, Any] = await agent_manager.get_agent_health(agent_id)
        return success(data=health.model_dump())
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)


@router.post("/{agent_id}/runtime")
async def switch_runtime(
    agent_id: str,
    req: SwitchRuntimeRequest,
    agent_manager: AgentManager = Depends(get_agent_manager_dep),
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """将 Agent 切换到不同的运行时类型。"""
    try:
        await agent_manager.switch_runtime(agent_id, req.runtime_type)
        return success(
            data={"agent_id": agent_id, "runtime_type": req.runtime_type},
            message="Runtime switched successfully",
        )
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)
    except AgentStateError as exc:
        return error_response(exc.code, exc.message, status.HTTP_409_CONFLICT)
