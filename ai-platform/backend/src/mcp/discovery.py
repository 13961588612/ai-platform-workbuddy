"""
MCPDiscovery — 从 MCP Server 自动发现工具并将其注册为 Skill。

当新的 MCP Server 连接时，MCPDiscovery：
  1. 在服务器上调用 ``list_tools()``。
  2. 将每个工具转换为 :class:`Skill` 对象。
  3. 将其注册到 :class:`SkillRegistry`（后者将其索引到 Qdrant）。
  4. 可选地根据服务器名称推断分类标签。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from src.skills.models import Skill, SkillSource, SkillStatus

if TYPE_CHECKING:
    from src.mcp.manager import MCPManager
    from src.skills.registry import SkillRegistry

logger = structlog.get_logger(__name__)

# 从 MCP 服务器名称关键词到 Skill 分类的映射。
_SERVER_CATEGORY_MAP: dict[str, str] = {
    "finance": "finance",
    "retail": "retail",
    "department_store": "department_store",
    "dept_store": "department_store",
    "hr": "hr",
    "human": "hr",
    "property": "property",
    "crm": "crm",
    "valuecard": "valuecard",
    "value_card": "valuecard",
}


class MCPDiscovery:
    """从 MCP Server 发现工具并注册为 Skill。"""

    def __init__(
        self,
        manager: MCPManager,
        registry: SkillRegistry | None = None,
    ) -> None:
        """初始化 MCP 工具发现器。

        Args:
            manager: 用于 ``list_tools`` 的 MCP 连接管理器。
            registry: 可选的 Skill 注册表；未设置时无法注册发现的工具。
        """
        self._manager = manager
        self._registry = registry

    def set_registry(self, registry: SkillRegistry) -> None:
        """设置用于注册发现工具的 SkillRegistry。"""
        self._registry = registry

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        """返回已连接 MCP Server 的原始工具列表。"""
        return await self._manager.discover_tools(server_name)

    async def discover_and_register(
        self,
        server_name: str,
    ) -> list[Skill]:
        """从 *server_name* 发现工具并注册为 Skill。

        返回新创建的 Skill 对象列表。
        """
        if not self._registry:
            logger.error("No SkillRegistry set; cannot register discovered tools")
            return []

        tools: dict[str, Any] = await self.list_tools(server_name)
        category: str = self._infer_category(server_name)

        new_skills: list[Skill] = []
        for tool in tools:
            skill: Skill = self._tool_to_skill(server_name, tool, category)
            await self._registry.register(skill)
            new_skills.append(skill)

        logger.info(
            "MCP tools discovered and registered",
            server=server_name,
            tools_found=len(tools),
            skills_registered=len(new_skills),
            category=category,
        )
        return new_skills

    def _tool_to_skill(
        self,
        server_name: str,
        tool: dict[str, Any],
        category: str,
    ) -> Skill:
        """将原始 MCP 工具描述转换为 Skill。"""
        tool_name: str = tool.get("name", "unknown")
        skill_id: str = f"mcp-{server_name}-{tool_name}"

        return Skill(
            skill_id=skill_id,
            name=tool_name,
            description=tool.get("description", ""),
            category=tool.get("category", category),
            tags=tool.get("tags", [server_name]),
            parameters=tool.get("inputSchema", {}),
            required_permissions=tool.get("requiredPermissions", []),
            handler=f"mcp:{server_name}:{tool_name}",
            timeout=tool.get("timeout", 30),
            version=tool.get("version", "1.0.0"),
            status=SkillStatus.ACTIVE,
            source=SkillSource.MCP,
            mcp_server=server_name,
            priority=tool.get("priority", 1.0),
            requires_approval=tool.get("requiresApproval", False),
        )

    @staticmethod
    def _infer_category(server_name: str) -> str:
        """从 MCP 服务器名称推断 Skill 分类。"""
        name_lower: str = server_name.lower()
        for keyword, category in _SERVER_CATEGORY_MAP.items():
            if keyword in name_lower:
                return category
        return "built_in"

    async def discover_all_servers(self) -> dict[str, list[Skill]]:
        """从所有已注册的 MCP Server 发现工具。

        返回 server_name → 已注册 Skill 列表的映射。
        """
        results: dict[str, list[Skill]] = {}
        servers: dict[str, Any] = self._manager.list_servers()
        for config in servers:
            try:
                skills: dict[str, Any] = await self.discover_and_register(config.name)
                results[config.name] = skills
            except Exception:
                logger.exception(
                    "Failed to discover tools from server",
                    server=config.name,
                )
                results[config.name] = []
        return results
