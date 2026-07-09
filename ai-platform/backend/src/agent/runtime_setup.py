"""将平台 Agent 配置接入原生 OpenHarness 运行时。"""

from __future__ import annotations
from typing import Any

from pathlib import Path

from src.agent.config import AgentConfig
from src.config import get_settings
from src.runtime.base import AgentRuntime
from src.runtime.oh_runtime_builder import connect_mcp_manager, resolve_extra_skill_dirs
from src.utils.logging import get_logger

logger = get_logger("agent.runtime_setup")


async def wire_agent_runtime(runtime: AgentRuntime, config: AgentConfig) -> dict[str, Any]:
    """
    准备原生 OpenHarness 运行时：通过 ``McpClientManager`` 接入 MCP，
    通过 ``extra_skill_dirs`` 接入 Skills。
    """
    config_base: Path = Path(get_settings().CONFIG_BASE_PATH)
    skill_dirs: list[str] = resolve_extra_skill_dirs(config, config_base)

    mcp_connected: int = 0
    if hasattr(runtime, "set_native_mcp_manager"):
        try:
            mcp_manager: McpClientManager = await connect_mcp_manager(config)
            runtime.set_native_mcp_manager(mcp_manager)
            mcp_connected: Any = len(config.mcp_servers)
        except Exception as exc:
            logger.warning(
                "Native OpenHarness MCP connect failed",
                agent_id=config.agent_id,
                error=str(exc),
            )

    logger.info(
        "Agent runtime wired (native OpenHarness)",
        agent_id=config.agent_id,
        skill_dirs=skill_dirs,
        mcp_servers=len(config.mcp_servers),
        mcp_connected=mcp_connected,
    )
    return {
        "tools_registered": 0,
        "skill_dirs": skill_dirs,
        "mcp_servers": len(config.mcp_servers),
        "mcp_connected": mcp_connected,
        "runtime": "native_openharness",
    }
