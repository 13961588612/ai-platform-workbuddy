"""Skills 和 MCP 子系统的启动/关闭辅助函数。"""

from __future__ import annotations
from typing import Any


from src.mcp.discovery import MCPDiscovery
from src.mcp.loader import load_mcp_servers_from_files
from src.mcp.manager import MCPManager
from src.skills.cache import HotSkillCache
from src.skills.indexer import VectorIndexer
from src.skills.loader import load_skills_from_files
from src.skills.registry import SkillRegistry
from src.utils.logging import get_logger

logger = get_logger("bootstrap.skills_mcp")

_skill_registry: SkillRegistry | None = None
_mcp_manager: MCPManager | None = None
_mcp_discovery: MCPDiscovery | None = None


def get_skill_registry() -> SkillRegistry | None:
    """返回启动时注入的全局 ``SkillRegistry``，未初始化时返回 ``None``。"""
    return _skill_registry


def get_mcp_manager() -> MCPManager | None:
    """返回启动时注入的全局 ``MCPManager``，未初始化时返回 ``None``。"""
    return _mcp_manager


async def initialize_skills_and_mcp() -> dict[str, Any]:
    """从配置文件加载 Skills/MCP，并接入 API 路由单例。"""
    global _skill_registry, _mcp_manager, _mcp_discovery

    # 延迟导入以避免与 agent.manager → runtime.openharness 的循环依赖
    from src.api.routes.mcp import set_discovery, set_manager
    from src.api.routes.skill import set_registry

    registry: SkillRegistry = SkillRegistry(
        indexer=VectorIndexer(),
        cache=HotSkillCache(),
    )
    skills_loaded: int = await load_skills_from_files(registry, enabled_only=True)
    set_registry(registry)
    _skill_registry = registry

    manager: MCPManager = MCPManager()
    mcp_loaded: int = load_mcp_servers_from_files(manager)
    set_manager(manager)
    _mcp_manager = manager

    discovery: MCPDiscovery = MCPDiscovery(manager, registry)
    set_discovery(discovery)
    _mcp_discovery = discovery

    connected: int = 0
    try:
        connected: int = await manager.auto_connect_all()
    except Exception as exc:
        logger.warning("MCP auto-connect failed", error=str(exc))

    return {
        "skills_loaded": skills_loaded,
        "mcp_servers_loaded": mcp_loaded,
        "mcp_connected": connected,
    }


async def shutdown_skills_and_mcp() -> None:
    """断开 MCP 客户端连接并清理注入的单例。"""
    global _skill_registry, _mcp_manager, _mcp_discovery

    if _mcp_manager is not None:
        try:
            await _mcp_manager.disconnect_all()
        except Exception as exc:
            logger.warning("MCP disconnect error", error=str(exc))

    from src.api.routes.mcp import set_discovery, set_manager
    from src.api.routes.skill import set_registry

    set_registry(None)  # type: ignore[arg-type]
    set_manager(None)  # type: ignore[arg-type]
    set_discovery(None)  # type: ignore[arg-type]
    _skill_registry = None
    _mcp_manager = None
    _mcp_discovery = None
