"""从 configs/skills/packages/ 加载 Agent Skills Spec 技能包。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.config import get_settings
from src.skills.models import Skill, SkillSource, SkillStatus
from src.skills.registry import SkillRegistry
from src.skills.schema import resolve_input_schema
from src.skills.spec_parser import (
    iter_skill_packages,
    list_package_attachments,
    read_skill_full,
    read_skill_metadata,
    resolve_skill_id,
)
from src.utils.logging import get_logger

logger = get_logger("skills.loader")


def _parse_source(raw: str) -> SkillSource:
    key = raw.lower()
    if key == "mcp":
        return SkillSource.MCP
    if key == "builtin":
        return SkillSource.BUILTIN
    if key == "package":
        return SkillSource.PACKAGE
    return SkillSource.CUSTOM


def _parse_status(raw: str) -> SkillStatus:
    key = raw.lower()
    if key == "inactive":
        return SkillStatus.INACTIVE
    if key == "deprecated":
        return SkillStatus.DEPRECATED
    return SkillStatus.ACTIVE


def _metadata_to_skill(
    metadata: dict[str, Any],
    *,
    package_name: str = "",
    package_dir: str = "",
) -> Skill:
    """将 Front Matter 元数据转换为 Skill 模型（不含正文）。"""
    skill_id = resolve_skill_id(metadata, package_name)
    source = _parse_source(str(metadata.get("source", "package" if package_name else "custom")))

    return Skill(
        skill_id=skill_id,
        name=str(metadata.get("name", skill_id)),
        description=str(metadata.get("description", "")),
        category=str(metadata.get("category", "built_in")),
        tags=list(metadata.get("tags", []) or []),
        parameters=resolve_input_schema(metadata),
        required_permissions=list(metadata.get("required_permissions", metadata.get("permissions", [])) or []),
        handler=str(metadata.get("handler", "")),
        timeout=int(metadata.get("timeout", 30)),
        version=str(metadata.get("version", "1.0.0")),
        status=_parse_status(str(metadata.get("status", "active"))),
        source=source,
        priority=float(metadata.get("priority", 1.0)),
        requires_approval=bool(metadata.get("requires_approval", False)),
        mcp_server=metadata.get("mcp_server"),
        package_name=package_name,
        package_dir=package_dir,
        body_loaded=False,
    )


def load_enabled_skill_ids(config_base: Path) -> set[str]:
    """从各 Agent 的 enabled-skills.yaml 收集已启用的 skill_id。"""
    enabled: set[str] = set()
    agents_dir = config_base / "agents"
    if not agents_dir.is_dir():
        return enabled

    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        enabled_file = agent_dir / "skills" / "enabled-skills.yaml"
        if not enabled_file.is_file():
            continue
        try:
            with open(enabled_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            logger.warning("解析 enabled-skills 失败", path=str(enabled_file), error=str(exc))
            continue

        for item in data.get("skills", {}).get("enabled", []):
            if isinstance(item, dict) and item.get("skill_id") and item.get("enabled", True):
                enabled.add(item["skill_id"])

    return enabled


async def load_skill_package_body(skill: Skill) -> Skill:
    """
    渐进式披露 — 阶段二：加载 SKILL.md 完整正文与附件索引。

    若已加载或非技能包，直接返回原对象。
    """
    if skill.body_loaded or not skill.package_dir:
        return skill

    skill_md = Path(skill.package_dir) / "SKILL.md"
    metadata, body = read_skill_full(skill_md)
    attachments = list_package_attachments(Path(skill.package_dir))

    # 元数据以注册时为准，此处仅填充正文
    skill.load_body(body, attachments)
    logger.info(
        "Skill 正文已懒加载",
        skill_id=skill.skill_id,
        body_chars=len(body),
        references=len(skill.references),
        scripts=len(skill.scripts),
    )
    return skill


async def load_skills_from_files(
    registry: SkillRegistry,
    *,
    config_base: Path | None = None,
    enabled_only: bool = True,
) -> int:
    """
    加载 Skill 并注册（渐进式披露阶段一）。

    扫描 ``packages/*/SKILL.md``，仅解析 Front Matter 元数据，不加载 Markdown 正文。
    """
    base = config_base or Path(get_settings().CONFIG_BASE_PATH)
    enabled_ids = load_enabled_skill_ids(base) if enabled_only else set()
    filter_enabled = enabled_only and bool(enabled_ids)
    loaded = 0
    seen_ids: set[str] = set()

    # ----- Agent Skills Spec 技能包 -----
    packages_root = base / "skills" / "packages"
    for package_dir in iter_skill_packages(packages_root):
        skill_md = package_dir / "SKILL.md"
        metadata, _ = read_skill_metadata(skill_md)
        if not metadata:
            logger.warning("跳过无元数据的技能包", path=str(package_dir))
            continue

        skill = _metadata_to_skill(
            metadata,
            package_name=package_dir.name,
            package_dir=str(package_dir.resolve()),
        )
        if filter_enabled and skill.skill_id not in enabled_ids:
            continue
        if skill.skill_id in seen_ids:
            continue

        await registry.register(skill)
        seen_ids.add(skill.skill_id)
        loaded += 1

    logger.info(
        "Skill 元数据加载完成",
        count=loaded,
        enabled_filter=filter_enabled,
        packages_root=str(packages_root),
    )
    return loaded
