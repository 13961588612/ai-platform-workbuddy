"""
BusinessSystemAdapter — 所有业务系统适配器的抽象基类。

每个适配器封装一个特定的业务系统（财务、零售、HR 等），
并将其 API 暴露为 MCP 兼容的工具。适配器负责：
  1. 向后端系统认证（使用 CredentialVault 中的凭据）。
  2. 将工具调用转换为后端 API 请求。
  3. 将响应转换回统一的 MCP 工具结果格式。

子类必须实现：
  - ``_define_tools()`` — 返回工具定义列表
  - ``_execute_tool(name, args, credential)`` — 执行工具调用
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx
import structlog
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)


class ToolDefinition(BaseModel):
    """适配器暴露的单个工具定义。"""

    name: str
    description: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    required_permissions: list[str] = Field(default_factory=list)
    timeout: int = 30
    requires_approval: bool = False


class ToolResult(BaseModel):
    """工具执行的结果。"""

    success: bool = True
    data: Any = None
    error: str | None = None


class BusinessSystemAdapter(ABC):
    """所有业务系统适配器的抽象基类。

    每个适配器封装一个业务系统，并将其能力
    暴露为一组 MCP 兼容的工具。适配器处理认证、
    请求转换和错误处理。
    """

    def __init__(
        self,
        system_type: str,
        base_url: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._system_type = system_type
        self._base_url = base_url
        self._timeout = timeout
        self._tools: list[ToolDefinition] = []
        self._define_tools()

    @property
    def system_type(self) -> str:
        """返回业务系统类型标识符。"""
        return self._system_type

    @property
    def base_url(self) -> str:
        """返回后端系统的基础 URL。"""
        return self._base_url

    # ---- 工具发现 ----

    def list_tools(self) -> list[dict[str, Any]]:
        """以字典形式返回所有工具定义（MCP 兼容格式）。"""
        return [
            {
                "name": t.name,
                "description": t.description,
                "category": t.category,
                "tags": t.tags,
                "inputSchema": t.input_schema,
                "requiredPermissions": t.required_permissions,
                "timeout": t.timeout,
                "requiresApproval": t.requires_approval,
            }
            for t in self._tools
        ]

    def get_tool(self, name: str) -> ToolDefinition | None:
        """按名称返回工具定义，未找到则返回 None。"""
        for tool in self._tools:
            if tool.name == name:
                return tool
        return None

    # ---- 工具执行 ----

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行工具调用并返回结果。

        Args:
            tool_name: 要执行的工具名称。
            arguments: 工具的参数。
            credential: 解密后的凭据字典（来自 CredentialVault）。

        Returns:
            包含 ``success``、``data`` 和 ``error`` 键的字典。
        """
        tool = self.get_tool(tool_name)
        if not tool:
            return ToolResult(
                success=False, error=f"Unknown tool: {tool_name}"
            ).model_dump()

        try:
            result = await self._execute_tool(tool_name, arguments, credential)
            return result.model_dump()
        except Exception as exc:
            logger.exception(
                "Tool execution failed",
                system=self._system_type,
                tool=tool_name,
            )
            return ToolResult(success=False, error=str(exc)).model_dump()

    # ---- 健康检查 ----

    async def health_check(self) -> bool:
        """检查后端系统是否可访问。

        子类可以重写此方法以实现系统特定的检查。
        """
        if not self._base_url:
            return False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code < 500
        except Exception:
            return False

    # ---- 受保护的 HTTP 辅助方法 ----

    async def _http_request(
        self,
        method: str,
        path: str,
        credential: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """执行到后端系统的 HTTP 请求。

        自动从 *credential* 注入认证头。
        """
        url = f"{self._base_url}{path}"
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if credential:
            token = credential.get("token") or credential.get("api_key")
            if token:
                headers["Authorization"] = f"Bearer {token}"
            username = credential.get("username")
            password = credential.get("password")
            if username and password:
                import base64

                basic = base64.b64encode(
                    f"{username}:{password}".encode("utf-8")
                ).decode("ascii")
                headers["Authorization"] = f"Basic {basic}"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                json=json_body,
                params=params,
            )
            resp.raise_for_status()
            return resp.json()

    # ---- 抽象方法 ----

    @abstractmethod
    def _define_tools(self) -> None:
        """用工具定义填充 ``self._tools``。

        子类必须实现此方法以声明其
        业务系统暴露的工具。
        """

    @abstractmethod
    async def _execute_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        credential: dict[str, Any] | None,
    ) -> ToolResult:
        """针对后端系统执行工具调用。

        子类必须实现此方法，将 *tool_name* 和
        *arguments* 转换为后端 API 调用并返回结果。
        """
