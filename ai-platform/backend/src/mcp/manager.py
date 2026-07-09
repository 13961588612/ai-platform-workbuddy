"""
MCPManager — MCP Server 连接的生命周期管理。

维护 MCPClient 实例的注册表，每个实例连接到一个 MCP
Server。提供以下方法：
  - ``register()`` — 添加 MCP Server 配置
  - ``connect()`` — 建立连接
  - ``disconnect()`` — 关闭连接
  - ``discover_tools()`` — 列出已连接服务器的工具
  - ``call_tool()`` — 在已连接服务器上调用工具
  - ``list_servers()`` — 枚举已注册的服务器
  - ``health_check_all()`` — 对所有服务器进行健康检测
"""

from __future__ import annotations

from typing import Any

import structlog
from pydantic import BaseModel, Field

from src.mcp.client import MCPClient, MCPClientError, MCPTransportType

logger = structlog.get_logger(__name__)


class MCPServerConfig(BaseModel):
    """单个 MCP Server 连接的配置。"""

    name: str
    transport: MCPTransportType = MCPTransportType.HTTP
    endpoint: str  # http/sse 的 URL，stdio 的可执行文件路径
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = 30.0
    auto_connect: bool = True
    description: str = ""


class MCPManager:
    """管理所有 MCP Server 连接。"""

    def __init__(self) -> None:
        """初始化 MCP 管理器（空注册表，无活跃连接）。"""
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    # ---- 注册 ----

    def register(self, config: MCPServerConfig) -> None:
        """注册 MCP Server 配置（不连接）。"""
        self._configs[config.name] = config
        logger.info(
            "MCP server registered",
            name=config.name,
            transport=config.transport.value,
            endpoint=config.endpoint,
        )

    def unregister(self, name: str) -> None:
        """取消注册并断开 MCP Server。"""
        if name in self._clients:
            # 同步断开不可行；标记等待清理
            logger.warning("Unregistering connected server; call disconnect first", name=name)
        self._configs.pop(name, None)
        self._clients.pop(name, None)

    # ---- 连接生命周期 ----

    async def connect(self, name: str) -> MCPClient:
        """建立到已注册 MCP Server 的连接。"""
        config = self._configs.get(name)
        if not config:
            raise MCPClientError(f"MCP server '{name}' is not registered")

        if name in self._clients and self._clients[name].is_connected:
            return self._clients[name]

        client = MCPClient(
            server_name=config.name,
            transport=config.transport,
            endpoint=config.endpoint,
            args=config.args,
            env=config.env,
            timeout=config.timeout,
        )
        await client.connect()
        self._clients[name] = client
        return client

    async def disconnect(self, name: str) -> None:
        """关闭到 MCP Server 的连接。"""
        client = self._clients.pop(name, None)
        if client:
            await client.disconnect()

    async def disconnect_all(self) -> None:
        """关闭所有 MCP Server 连接。"""
        names = list(self._clients.keys())
        for name in names:
            await self.disconnect(name)

    # ---- 工具操作 ----

    async def discover_tools(self, name: str) -> list[dict[str, Any]]:
        """列出已连接 MCP Server 暴露的所有工具。"""
        client = await self._get_connected_client(name)
        return await client.list_tools()

    async def call_tool(
        self, name: str, tool_name: str, args: dict[str, Any]
    ) -> dict[str, Any]:
        """在已连接 MCP Server 上调用工具。"""
        client = await self._get_connected_client(name)
        try:
            return await client.call_tool(tool_name, args)
        except Exception:
            logger.exception(
                "MCP tool call failed",
                server=name,
                tool=tool_name,
            )
            raise

    # ---- 信息查询 ----

    def list_servers(self) -> list[MCPServerConfig]:
        """返回所有已注册的 MCP Server 配置。"""
        return list(self._configs.values())

    def get_server_config(self, name: str) -> MCPServerConfig | None:
        """返回指定服务器的配置。"""
        return self._configs.get(name)

    async def health_check_all(self) -> dict[str, bool]:
        """对所有已连接 MCP Server 进行健康检测，返回其健康状态。"""
        results: dict[str, bool] = {}
        for name, client in self._clients.items():
            results[name] = await client.health_check()
        return results

    # ---- 自动连接 ----

    async def auto_connect_all(self) -> int:
        """连接所有 ``auto_connect=True`` 的服务器。

        返回成功建立的连接数。
        """
        count = 0
        for name, config in self._configs.items():
            if not config.auto_connect:
                continue
            if name in self._clients and self._clients[name].is_connected:
                count += 1
                continue
            try:
                await self.connect(name)
                count += 1
            except Exception:
                logger.exception("Auto-connect failed", server=name)
        return count

    # ---- 内部方法 ----

    async def _get_connected_client(self, name: str) -> MCPClient:
        """返回 *name* 对应的已连接客户端，必要时自动连接。"""
        client = self._clients.get(name)
        if client and client.is_connected:
            return client
        return await self.connect(name)
