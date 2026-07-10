"""根据平台的 AgentConfig 构建原生 OpenHarness QueryEngine。"""

from __future__ import annotations
from typing import Any

from pathlib import Path

from openharness.config.settings import PermissionSettings, load_settings
from openharness.engine.query_engine import QueryEngine
from openharness.mcp.client import McpClientManager
from openharness.mcp.types import McpHttpServerConfig, McpServerConfig, McpStdioServerConfig
from openharness.permissions.checker import PermissionChecker
from openharness.permissions.modes import PermissionMode
from openharness.prompts import build_runtime_system_prompt
from openharness.tools.base import ToolRegistry

from src.agent.config import AgentConfig, MCPServerConfig
from src.config import get_settings
from src.runtime.gateway_api_client import GatewayApiClient
from src.runtime.tool_registry_builder import (
    create_agent_source_registry,
    create_platform_tool_registry,
    is_tool_allowed,
)
from src.skills.spec_parser import read_skill_metadata, resolve_skill_id
from src.utils.logging import get_logger

logger = get_logger("runtime.oh_builder")


def agent_mcp_to_openharness_configs(
    mcp_servers: list[MCPServerConfig],
) -> dict[str, McpServerConfig]:
    """将平台的 mcp-servers.yaml 条目映射为 OpenHarness MCP 配置模型。"""
    configs: dict[str, McpServerConfig] = {}
    for server in mcp_servers:
        if not server.enabled:
            continue
        transport: str = server.transport.strip().lower()
        if transport in {"http", "streamable_http", "streamable-http", "sse"}:
            if not server.endpoint:
                logger.warning("MCP server missing endpoint", name=server.name)
                continue
            configs[server.name] = McpHttpServerConfig(
                url=server.endpoint,
                headers={},
            )
        elif transport == "stdio":
            command: Any = server.command or server.endpoint
            if not command:
                logger.warning("MCP stdio server missing command", name=server.name)
                continue
            configs[server.name] = McpStdioServerConfig(
                command=command,
                args=list(server.args),
                env=dict(server.env) or None,
            )
    return configs


def resolve_extra_skill_dirs(config: AgentConfig, config_base: Path) -> list[str]:
    """
    根据已启用的 agent skills 解析 OpenHarness 的 extra_skill_dirs。

    OpenHarness 期望目录结构为 ``<extra_skill_dir>/<skill-name>/SKILL.md``。
    我们传入业务分类目录（例如 packages/crm）。
    """
    packages_root: Any = config_base / "skills" / "packages"
    if not packages_root.is_dir():
        return []

    enabled_ids: set[Any] = {ref.skill_id for ref in config.skills if ref.enabled}
    if not enabled_ids:
        return []

    category_dirs: set[str] = set()
    for skill_md in packages_root.rglob("SKILL.md"):
        category_dir: Any = skill_md.parent.parent
        if category_dir == packages_root:
            continue
        metadata: dict[str, Any]
        _: str
        metadata, _ = read_skill_metadata(skill_md)
        skill_id: str = resolve_skill_id(metadata, skill_md.parent.name)
        if skill_id in enabled_ids:
            category_dirs.add(str(category_dir.resolve()))

    return sorted(category_dirs)


async def connect_mcp_manager(config: AgentConfig) -> McpClientManager:
    """根据 agent config 创建并连接 OpenHarness MCP 管理器。"""
    mcp_configs: dict[str, McpServerConfig] = agent_mcp_to_openharness_configs(config.mcp_servers)
    mcp_manager: McpClientManager = McpClientManager(mcp_configs)
    await mcp_manager.connect_all()
    return mcp_manager


async def build_native_query_engine(
    config: AgentConfig,
    gateway: Any,
    mcp_manager: McpClientManager,
    *,
    session_id: str = "",
    user_id: str = "",
    dept: str = "",
) -> QueryEngine:
    """使用原生 SkillTool + MCP 工具组装 OpenHarness QueryEngine。"""
    settings: Any = load_settings()
    config_base: Path = Path(get_settings().CONFIG_BASE_PATH)
    cwd: str = str(config_base.resolve())
    extra_skill_dirs: list[str] = resolve_extra_skill_dirs(config, config_base)

    mcp_configs: dict[str, McpServerConfig] = agent_mcp_to_openharness_configs(config.mcp_servers)
    allowed_tools: Any = config.runtime.allowed_tools if config.runtime else []
    source_registry: ToolRegistry = create_agent_source_registry(mcp_manager)
    allowed_patterns: Any = allowed_tools or ["skill", "mcp__*"]
    concrete_allowed: list[Any] = [
        tool.name
        for tool in source_registry.list_tools()
        if is_tool_allowed(tool.name, allowed_patterns)
    ]
    settings.permission = PermissionSettings(
        mode=PermissionMode.FULL_AUTO,
        allowed_tools=concrete_allowed,
    )
    tool_registry: ToolRegistry = create_platform_tool_registry(mcp_manager, allowed_tools)

    model: Any = config.model.primary if config.model else "deepseek-v4-flash"
    runtime_params: Any = config.runtime.params if config.runtime else {}
    max_tokens: int = int(runtime_params.get("maxTokens", 4096))
    max_steps: int = int(runtime_params.get("maxSteps", 20))
    temperature: float = float(runtime_params.get("temperature", 0.7))

    oh_system_prompt: Any = build_runtime_system_prompt(
        settings,
        cwd=cwd,
        extra_skill_dirs=extra_skill_dirs,
        include_project_memory=False,
    )
    agent_prompt: Any = config.system_prompt or ""
    if config.runtime and config.runtime.prompts.get("system_prompt"):
        agent_prompt: Any = config.runtime.prompts["system_prompt"]
    system_prompt: str = "\n\n".join(
        part for part in (agent_prompt, oh_system_prompt) if part
    ).strip()

    api_client: GatewayApiClient = GatewayApiClient(
        gateway,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        session_id=session_id,
        user_id=user_id,
        dept=dept,
    )

    engine: QueryEngine = QueryEngine(
        api_client=api_client,
        tool_registry=tool_registry,
        permission_checker=PermissionChecker(settings.permission),
        cwd=cwd,
        model=model,
        system_prompt=system_prompt,
        max_tokens=max_tokens,
        max_turns=max_steps,
        tool_metadata={
            "extra_skill_dirs": extra_skill_dirs,
            "session_id": session_id,
        },
    )

    logger.info(
        "Native OpenHarness QueryEngine built",
        model=model,
        max_turns=max_steps,
        skill_dirs=extra_skill_dirs,
        mcp_servers=list(mcp_configs.keys()),
        tools=[tool.name for tool in tool_registry.list_tools()],
    )
    return engine
