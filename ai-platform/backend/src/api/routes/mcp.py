"""
MCP Server 管理 API 路由。

端点：
  GET    /api/v1/mcp                   — 列出已注册的 MCP Server
  POST   /api/v1/mcp                   — 注册新的 MCP Server
  GET    /api/v1/mcp/{name}            — 获取 MCP Server 配置
  POST   /api/v1/mcp/{name}/connect    — 连接到 MCP Server
  POST   /api/v1/mcp/{name}/disconnect — 断开 MCP Server 连接
  GET    /api/v1/mcp/{name}/tools      — 列出服务器暴露的工具
  POST   /api/v1/mcp/{name}/call       — 调用服务器上的工具
  GET    /api/v1/mcp/health            — 对所有已连接服务器进行健康检查
  POST   /api/v1/mcp/{name}/discover   — 发现工具并将其注册为 Skill
"""

from __future__ import annotations
from typing import Any

import uuid

import structlog
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.mcp.client import MCPClientError, MCPTransportType
from src.mcp.manager import MCPServerConfig

logger = structlog.get_logger(__name__)

router = APIRouter()

# 单例（在应用启动时注入）
_manager: Any = None
_discovery: Any = None


def set_manager(manager: Any) -> None:
    """注入 MCPManager 实例。"""
    global _manager
    _manager = manager


def set_discovery(discovery: Any) -> None:
    """注入 MCPDiscovery 实例。"""
    global _discovery
    _discovery = discovery


def _api_response(code: int, data: Any, message: str) -> dict[str, Any]:
    """组装统一的 MCP API JSON 响应体。

    Args:
        code: 业务状态码（``0`` 表示成功）。
        data: 响应载荷。
        message: 人类可读说明。

    Returns:
        含 ``code``、``data``、``message``、``traceId`` 的字典。
    """
    return {
        "code": code,
        "data": data,
        "message": message,
        "traceId": str(uuid.uuid4()),
    }


class RegisterServerRequest(BaseModel):
    """注册 MCP Server 的请求体。"""

    name: str
    transport: MCPTransportType = MCPTransportType.HTTP
    endpoint: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = 30.0
    auto_connect: bool = True
    description: str = ""


class CallToolRequest(BaseModel):
    """在 MCP Server 上调用工具的请求体。"""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


@router.get("", response_model=dict)
async def list_servers() -> dict[str, Any]:
    """列出所有已注册的 MCP Server。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")
    servers: list[dict[str, Any]] = [s.model_dump(mode="json") for s in _manager.list_servers()]
    return _api_response(0, servers, "OK")


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register_server(req: RegisterServerRequest) -> dict[str, Any]:
    """注册新的 MCP Server。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")

    config: MCPServerConfig = MCPServerConfig(
        name=req.name,
        transport=req.transport,
        endpoint=req.endpoint,
        args=req.args,
        env=req.env,
        timeout=req.timeout,
        auto_connect=req.auto_connect,
        description=req.description,
    )
    _manager.register(config)
    return _api_response(0, config.model_dump(mode="json"), "Server registered")


@router.get("/health", response_model=dict)
async def health_check_all() -> dict[str, Any]:
    """对所有已连接的 MCP Server 进行健康检查。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")
    results: dict[str, Any] = await _manager.health_check_all()
    return _api_response(0, results, "OK")


@router.get("/{name}", response_model=dict)
async def get_server(name: str) -> dict[str, Any]:
    """获取指定 MCP Server 的配置。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")
    config: MCPServerConfig | None = _manager.get_server_config(name)
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"MCP server '{name}' not found",
        )
    return _api_response(0, config.model_dump(mode="json"), "OK")


@router.post("/{name}/connect", response_model=dict)
async def connect_server(name: str) -> dict[str, Any]:
    """连接到 MCP Server。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")
    try:
        await _manager.connect(name)
        return _api_response(0, {"connected": True}, f"Connected to {name}")
    except MCPClientError as exc:
        return _api_response(4001, None, str(exc))


@router.post("/{name}/disconnect", response_model=dict)
async def disconnect_server(name: str) -> dict[str, Any]:
    """断开 MCP Server 连接。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")
    await _manager.disconnect(name)
    return _api_response(0, {"disconnected": True}, f"Disconnected from {name}")


@router.get("/{name}/tools", response_model=dict)
async def list_tools(name: str) -> dict[str, Any]:
    """列出已连接 MCP Server 暴露的工具。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")
    try:
        tools: list[dict[str, Any]] = await _manager.discover_tools(name)
        return _api_response(0, tools, "OK")
    except MCPClientError as exc:
        return _api_response(4002, None, str(exc))


@router.post("/{name}/call", response_model=dict)
async def call_tool(name: str, req: CallToolRequest) -> dict[str, Any]:
    """在已连接的 MCP Server 上调用工具。"""
    if _manager is None:
        return _api_response(9001, None, "MCPManager not initialized")
    try:
        result: dict[str, Any] = await _manager.call_tool(name, req.tool_name, req.arguments)
        return _api_response(0, result, "OK")
    except MCPClientError as exc:
        return _api_response(4003, None, str(exc))


@router.post("/{name}/discover", response_model=dict)
async def discover_and_register(name: str) -> dict[str, Any]:
    """从 MCP Server 发现工具并将其注册为 Skill。"""
    if _discovery is None:
        return _api_response(9001, None, "MCPDiscovery not initialized")
    try:
        skills: dict[str, Any] = await _discovery.discover_and_register(name)
        return _api_response(
            0,
            {"discovered": len(skills), "skill_ids": [s.skill_id for s in skills]},
            "Discovery complete",
        )
    except Exception as exc:
        return _api_response(4004, None, str(exc))
