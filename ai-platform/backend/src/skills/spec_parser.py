"""Agent Skills Spec 解析器 — 文件夹 + SKILL.md 技能包格式。

规范要点（2026 事实行业标准）：
- 每个 Skill 一个目录，目录名：小写英文 + 横线分隔
- SKILL.md：YAML Front Matter（元数据）+ Markdown 正文（执行流程）
- 可选子目录：scripts/、references/、assets/
- 渐进式披露：启动时仅解析 Front Matter；确认使用后再加载正文与附件
"""

from __future__ import annotations
from typing import Any

import re
from pathlib import Path

import yaml

from src.utils.logging import get_logger

logger = get_logger("skills.spec_parser")

# Front Matter 分隔符
_FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

# 渐进式加载时仅读取文件头部（足够覆盖 YAML 元数据）
_METADATA_READ_BYTES = 8192


def parse_front_matter(content: str) -> tuple[dict[str, Any], str]:
    """
    从 SKILL.md 全文解析 YAML Front Matter 与 Markdown 正文。

    返回 (metadata, body)。
    """
    match: Any = _FRONT_MATTER_RE.match(content)
    if not match:
        return {}, content.strip()

    raw_yaml: Any = match.group(1)
    body: str = content[match.end() :].strip()
    try:
        metadata: Any = yaml.safe_load(raw_yaml) or {}
    except yaml.YAMLError as exc:
        logger.warning("SKILL.md Front Matter 解析失败", error=str(exc))
        metadata: dict[str, Any] = {}

    if not isinstance(metadata, dict):
        metadata: dict[str, Any] = {}
    return metadata, body


def read_skill_metadata(skill_md: Path) -> tuple[dict[str, Any], str]:
    """
    渐进式披露 — 阶段一：仅读取 SKILL.md 头部以解析元数据。

    正文不在此阶段加载，body 返回空字符串。
    """
    if not skill_md.is_file():
        return {}, ""

    try:
        with open(skill_md, encoding="utf-8") as f:
            head: Any = f.read(_METADATA_READ_BYTES)
    except OSError as exc:
        logger.error("读取 SKILL.md 失败", path=str(skill_md), error=str(exc))
        return {}, ""

    metadata: dict[str, Any]
    _: str
    metadata, _ = parse_front_matter(head)
    return metadata, ""


def read_skill_full(skill_md: Path) -> tuple[dict[str, Any], str]:
    """渐进式披露 — 阶段二：加载 SKILL.md 完整正文。"""
    if not skill_md.is_file():
        return {}, ""

    try:
        content: str = skill_md.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("读取 SKILL.md 失败", path=str(skill_md), error=str(exc))
        return {}, ""

    return parse_front_matter(content)


def list_package_attachments(package_dir: Path) -> dict[str, list[str]]:
    """列出技能包内 scripts / references / assets 相对路径。"""
    result: dict[str, list[str]] = {
        "scripts": [],
        "references": [],
        "assets": [],
    }
    for subdir in ("scripts", "references", "assets"):
        folder: Any = package_dir / subdir
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                result[subdir].append(str(path.relative_to(package_dir)).replace("\\", "/"))
    return result


def resolve_skill_id(metadata: dict[str, Any], package_name: str) -> str:
    """
    解析 Skill 唯一 ID。

    优先 front matter 中的 skill_id，其次 name，最后使用目录名。
    """
    skill_id: Any = metadata.get("skill_id") or metadata.get("name") or package_name
    return str(skill_id)


def iter_skill_packages(packages_root: Path) -> list[Path]:
    """
    扫描 packages/ 下所有含 SKILL.md 的技能包目录。

    目录结构：``packages/{业务分类}/{skill-name}/SKILL.md``
    例如 ``packages/crm/member-profile-by-vip-id/SKILL.md``。

    以 ``_`` 开头的目录（如 ``_shared``）跳过；分类目录下同样跳过 ``_`` 前缀子目录。
    """
    if not packages_root.is_dir():
        return []

    packages: list[Path] = []
    for top in sorted(packages_root.iterdir()):
        if not top.is_dir() or top.name.startswith("_"):
            continue

        # 业务分类层：packages/crm/member-profile-xxx/
        if (top / "SKILL.md").is_file():
            # 兼容：无分类层、技能包直接在 packages/ 根下
            packages.append(top)
            continue

        for entry in sorted(top.iterdir()):
            if not entry.is_dir() or entry.name.startswith("_"):
                continue
            if (entry / "SKILL.md").is_file():
                packages.append(entry)

    return packages
