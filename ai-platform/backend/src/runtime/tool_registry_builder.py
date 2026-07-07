"""按 Agent 配置构建 OpenHarness 工具注册表。"""

from __future__ import annotations

import fnmatch
import json
import re
from typing import Any

from openharness.mcp.client import McpClientManager, McpServerNotConnectedError
from openharness.mcp.types import McpToolInfo
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolRegistry, ToolResult
from openharness.tools.skill_tool import SkillTool
from pydantic import BaseModel, ConfigDict, Field, create_model

from src.utils.logging import get_logger

logger = get_logger("runtime.tool_registry")

_MCP_LOG_LIMIT = 4000


def _clip_mcp_log(text: str, limit: int = _MCP_LOG_LIMIT) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "…"


def _format_mcp_output(output: str) -> str:
    """尽量格式化 JSON 输出，便于日志阅读。"""
    cleaned = (output or "").strip()
    try:
        parsed = json.loads(cleaned)
        formatted = json.dumps(parsed, ensure_ascii=False, indent=2)
        return _clip_mcp_log(formatted)
    except (json.JSONDecodeError, TypeError):
        return _clip_mcp_log(cleaned)

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _sanitize_tool_segment(value: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", value)
    if not sanitized:
        return "tool"
    if not sanitized[0].isalpha():
        return f"mcp_{sanitized}"
    return sanitized


def _pydantic_field_name(json_key: str) -> str:
    """将 JSON Schema 字段名转为 Pydantic 合法属性名（不能以 _ 开头）。"""
    name = re.sub(r"[^A-Za-z0-9_]", "_", json_key)
    if not name or name[0] == "_":
        name = f"field_{name.lstrip('_')}" or "field"
    if name[0].isdigit():
        name = f"field_{name}"
    return name


def _input_model_from_schema(tool_name: str, schema: dict[str, object]) -> type[BaseModel]:
    """从 MCP JSON Schema 构建 Pydantic 输入模型，兼容 _ 开头字段名。"""
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        return create_model(f"{tool_name.title().replace('-', '_')}Input")

    fields: dict[str, tuple[Any, Any]] = {}
    required = set(schema.get("required", [])) if isinstance(schema.get("required", []), list) else set()
    for json_key in properties:
        prop = properties[json_key] if isinstance(properties[json_key], dict) else {}
        py_type = _JSON_TYPE_MAP.get(str(prop.get("type", "")), object)
        attr_name = _pydantic_field_name(str(json_key))
        field_kwargs: dict[str, Any] = {}
        if str(json_key) != attr_name:
            field_kwargs["alias"] = str(json_key)
        if json_key in required:
            fields[attr_name] = (py_type, Field(default=..., **field_kwargs))
        else:
            fields[attr_name] = (py_type | None, Field(default=None, **field_kwargs))
    model_base = type(
        "_McpToolInputBase",
        (BaseModel,),
        {"model_config": ConfigDict(populate_by_name=True)},
    )
    return create_model(
        f"{tool_name.title().replace('-', '_')}Input",
        __base__=model_base,
        **fields,
    )


class PlatformMcpToolAdapter(BaseTool):
    """MCP 工具适配器 — 修复 Pydantic v2 对 _ 开头字段名的限制。"""

    def __init__(self, manager: McpClientManager, tool_info: McpToolInfo) -> None:
        self._manager = manager
        self._tool_info = tool_info
        server_segment = _sanitize_tool_segment(tool_info.server_name)
        tool_segment = _sanitize_tool_segment(tool_info.name)
        self.name = f"mcp__{server_segment}__{tool_segment}"
        self.description = tool_info.description or f"MCP tool {tool_info.name}"
        self.input_model = _input_model_from_schema(self.name, tool_info.input_schema)

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        del context
        payload = arguments.model_dump(mode="json", exclude_none=True, by_alias=True)
        logger.info(
            "MCP tool call started",
            tool=self.name,
            server=self._tool_info.server_name,
            mcp_tool=self._tool_info.name,
            arguments=payload,
        )
        try:
            output = await self._manager.call_tool(
                self._tool_info.server_name,
                self._tool_info.name,
                payload,
            )
        except McpServerNotConnectedError as exc:
            logger.warning(
                "MCP tool call failed",
                tool=self.name,
                server=self._tool_info.server_name,
                mcp_tool=self._tool_info.name,
                arguments=payload,
                error=str(exc),
            )
            return ToolResult(output=str(exc), is_error=True)

        logger.info(
            "MCP tool response",
            tool=self.name,
            server=self._tool_info.server_name,
            mcp_tool=self._tool_info.name,
            arguments=payload,
            output=_format_mcp_output(output),
            output_length=len(output or ""),
        )
        return ToolResult(output=output)

    def is_read_only(self, arguments: BaseModel) -> bool:
        return True


def create_agent_source_registry(mcp_manager: McpClientManager | None) -> ToolRegistry:
    """构建 Agent 可用工具源：skill + MCP（跳过 schema 不兼容的工具）。"""
    registry = ToolRegistry()
    registry.register(SkillTool())

    if mcp_manager is None:
        return registry

    for tool_info in mcp_manager.list_tools():
        try:
            registry.register(PlatformMcpToolAdapter(mcp_manager, tool_info))
        except Exception as exc:
            logger.warning(
                "Skipped MCP tool due to schema error",
                server=tool_info.server_name,
                tool=tool_info.name,
                error=str(exc),
            )
    return registry


class SafeToolWrapper(BaseTool):
    """包装工具执行，将未捕获异常转为 ToolResult 错误，避免中断 Agent 循环。"""

    def __init__(self, inner: BaseTool) -> None:
        self._inner = inner
        self.name = inner.name
        self.description = inner.description
        self.input_model = inner.input_model

    async def execute(self, arguments: BaseModel, context: ToolExecutionContext) -> ToolResult:
        try:
            return await self._inner.execute(arguments, context)
        except Exception as exc:
            logger.warning(
                "Tool execution failed (captured)",
                tool=self.name,
                error=str(exc),
                exc_type=exc.__class__.__name__,
            )
            message = str(exc).strip() or exc.__class__.__name__
            return ToolResult(output=message, is_error=True)

    def is_read_only(self, arguments: BaseModel) -> bool:
        return self._inner.is_read_only(arguments)


def resolve_allowed_tool_patterns(
    configured: list[str],
    mcp_manager: McpClientManager | None,
) -> list[str]:
    """
    解析 allowed_tools 配置。

    未配置时默认仅暴露 ``skill`` 与 ``mcp__*``（业务 Agent 安全默认值）。
    """
    if configured:
        return configured
    patterns = ["skill", "mcp__*"]
    if mcp_manager is not None:
        mcp_names = [
            f"mcp__{info.server_name}__{info.name}"
            for info in mcp_manager.list_tools()
        ]
        logger.debug("Default allowed_tools patterns", patterns=patterns, mcp_tools=mcp_names)
    return patterns


def is_tool_allowed(tool_name: str, patterns: list[str]) -> bool:
    """支持精确匹配与 glob（如 ``mcp__*``）。"""
    for pattern in patterns:
        if fnmatch.fnmatch(tool_name, pattern):
            return True
    return False


def create_platform_tool_registry(
    mcp_manager: McpClientManager | None,
    allowed_tools: list[str] | None = None,
) -> ToolRegistry:
    """
    从 OpenHarness 默认工具集按 allowed_tools 过滤，并包装为安全执行。

    Args:
        mcp_manager: 已连接的 MCP 管理器。
        allowed_tools: agent.yaml / runtime.yaml 中的工具白名单；空则使用平台默认。
    """
    patterns = resolve_allowed_tool_patterns(allowed_tools or [], mcp_manager)
    source = create_agent_source_registry(mcp_manager)

    registry = ToolRegistry()
    registered: list[str] = []
    for tool in source.list_tools():
        if not is_tool_allowed(tool.name, patterns):
            continue
        registry.register(SafeToolWrapper(tool))
        registered.append(tool.name)

    if not registered:
        logger.warning(
            "No tools matched allowed_tools; falling back to skill only",
            patterns=patterns,
        )
        skill_tool = source.get("skill")
        if skill_tool is not None:
            registry.register(SafeToolWrapper(skill_tool))
            registered.append(skill_tool.name)

    logger.info(
        "Platform tool registry built",
        allowed_patterns=patterns,
        tools=registered,
    )
    return registry
