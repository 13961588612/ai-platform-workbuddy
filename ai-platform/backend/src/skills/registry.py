"""
SkillRegistry — 所有 Skills 的中央注册与发现。

管理三种 Skill 来源：
1. **自定义 Skill** — 由操作员通过 API 或 YAML 配置注册。
2. **MCP 发现的工具** — 连接 MCP Server 时自动导入。
3. **内置 Skill** — 平台工具（搜索、计算等）。

注册时，Skill 的 embedding 会通过 VectorIndexer 生成并
upsert 到 Qdrant，同时更新 HotSkillCache。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog

from src.skills.models import Skill, SkillSource, SkillStatus

if TYPE_CHECKING:
    from src.mcp.discovery import MCPDiscovery
    from src.skills.cache import HotSkillCache
    from src.skills.indexer import VectorIndexer

logger = structlog.get_logger(__name__)


class SkillRegistry:
    """所有 Skills 的内存 + Qdrant 索引注册表。"""

    def __init__(
        self,
        indexer: VectorIndexer | None = None,
        cache: HotSkillCache | None = None,
    ) -> None:
        self._skills: dict[str, Skill] = {}
        self._indexer = indexer
        self._cache = cache

    # ---- 注册 ----

    async def register(self, skill: Skill) -> None:
        """注册新 Skill 或更新已有 Skill。

        如果 Skill（按 ``skill_id`` 判断）已存在，则覆盖。
        Qdrant 索引和缓存会相应更新。
        """
        self._skills[skill.skill_id] = skill
        logger.info(
            "Skill registered",
            skill_id=skill.skill_id,
            name=skill.name,
            category=skill.category,
            source=skill.source,
        )

        # 索引到 Qdrant（异步，失败时不阻塞）
        if self._indexer:
            try:
                await self._indexer.index_skill(skill)
            except Exception:
                logger.exception(
                    "Failed to index skill in Qdrant",
                    skill_id=skill.skill_id,
                )

        # 更新缓存
        if self._cache:
            try:
                await self._cache.set_skill(skill)
                await self._cache.invalidate_skill(skill.skill_id)
            except Exception:
                logger.exception(
                    "Failed to update skill cache",
                    skill_id=skill.skill_id,
                )

    async def unregister(self, skill_id: str) -> None:
        """从注册表、Qdrant 索引和缓存中移除 Skill。"""
        if skill_id not in self._skills:
            logger.warning("Unregister: skill not found", skill_id=skill_id)
            return

        self._skills.pop(skill_id, None)

        if self._indexer:
            try:
                await self._indexer.delete_index(skill_id)
            except Exception:
                logger.exception("Failed to delete skill index", skill_id=skill_id)

        if self._cache:
            try:
                await self._cache.invalidate_skill(skill_id)
            except Exception:
                logger.exception("Failed to invalidate cache", skill_id=skill_id)

        logger.info("Skill unregistered", skill_id=skill_id)

    # ---- 查找 ----

    def get(self, skill_id: str) -> Skill | None:
        """按 ID 返回 Skill，未找到返回 ``None``。"""
        return self._skills.get(skill_id)

    async def get_async(self, skill_id: str) -> Skill | None:
        """异步获取 Skill — 先查内存，再查缓存。"""
        skill = self._skills.get(skill_id)
        if skill:
            return skill
        if self._cache:
            cached = await self._cache.get_skill(skill_id)
            if cached:
                self._skills[skill_id] = cached
                return cached
        return None

    async def load_full(self, skill_id: str) -> Skill | None:
        """
        渐进式披露 — 阶段二：懒加载 SKILL.md 正文与附件索引。

        若 Skill 非技能包或已加载，直接返回。
        """
        skill = await self.get_async(skill_id)
        if skill is None:
            return None
        if skill.body_loaded or not skill.package_dir:
            return skill

        from src.skills.loader import load_skill_package_body

        skill = await load_skill_package_body(skill)
        self._skills[skill_id] = skill
        if self._cache:
            try:
                await self._cache.set_skill(skill)
            except Exception:
                logger.exception("更新 Skill 缓存失败", skill_id=skill_id)
        return skill

    def list_all(self) -> list[Skill]:
        """返回所有已注册的 Skill。"""
        return list(self._skills.values())

    def list_active(self) -> list[Skill]:
        """仅返回活跃的 Skill。"""
        return [s for s in self._skills.values() if s.status == SkillStatus.ACTIVE]

    def list_by_category(self, category: str) -> list[Skill]:
        """返回 *category* 中的所有 Skill。"""
        return [s for s in self._skills.values() if s.category == category]

    def list_by_source(self, source: SkillSource) -> list[Skill]:
        """返回来自指定 *source* 的所有 Skill。"""
        return [s for s in self._skills.values() if s.source == source]

    # ---- 索引 ----

    async def update_embedding(self, skill_id: str) -> None:
        """为单个 Skill 重新生成 embedding。"""
        skill = self._skills.get(skill_id)
        if not skill:
            logger.warning("update_embedding: skill not found", skill_id=skill_id)
            return
        if self._indexer:
            await self._indexer.index_skill(skill)

    async def reindex_all(self) -> int:
        """将所有活跃 Skill 重新索引到 Qdrant。"""
        if not self._indexer:
            return 0
        return await self._indexer.reindex_all(self.list_active())

    # ---- MCP 导入 ----

    async def import_from_mcp(
        self,
        server_name: str,
        discovery: MCPDiscovery,
    ) -> list[Skill]:
        """从 MCP Server 发现工具并注册为 Skill。

        返回新注册的 Skill 列表。
        """
        tools = await discovery.list_tools(server_name)
        new_skills: list[Skill] = []
        for tool in tools:
            skill_id = f"mcp-{server_name}-{tool.get('name', 'unknown')}"
            skill = Skill(
                skill_id=skill_id,
                name=tool.get("name", skill_id),
                description=tool.get("description", ""),
                category=tool.get("category", "built_in"),
                tags=tool.get("tags", []),
                parameters=tool.get("inputSchema", {}),
                required_permissions=tool.get("requiredPermissions", []),
                handler=f"mcp:{server_name}:{tool.get('name')}",
                timeout=tool.get("timeout", 30),
                version=tool.get("version", "1.0.0"),
                status=SkillStatus.ACTIVE,
                source=SkillSource.MCP,
                mcp_server=server_name,
            )
            await self.register(skill)
            new_skills.append(skill)

        logger.info(
            "MCP tools imported",
            server=server_name,
            count=len(new_skills),
        )
        return new_skills

    # ---- 使用追踪 ----

    def record_call(self, skill_id: str) -> None:
        """递增内存调用计数器并更新 last_called_at。"""
        skill = self._skills.get(skill_id)
        if skill:
            skill.call_count += 1
            skill.last_called_at = datetime.now(timezone.utc)

    # ---- 统计 ----

    def stats(self) -> dict[str, Any]:
        """返回注册表统计信息。"""
        categories: dict[str, int] = {}
        sources: dict[str, int] = {}
        for skill in self._skills.values():
            categories[skill.category] = categories.get(skill.category, 0) + 1
            src = skill.source.value if hasattr(skill.source, "value") else str(skill.source)
            sources[src] = sources.get(src, 0) + 1
        return {
            "total": len(self._skills),
            "active": len(self.list_active()),
            "by_category": categories,
            "by_source": sources,
        }
