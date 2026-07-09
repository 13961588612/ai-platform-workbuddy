"""
StaticMemoryLoader — 从文件系统加载并缓存 Agent 静态记忆。

静态记忆位于 ``configs/agents/{agent_name}/memory/`` 下：
  - ``agent-memory.yaml`` — 记忆配置入口（引用 personality + facts）
  - ``personality.md``    — 角色身份、人格风格、行为规则
  - ``facts/*.yaml``      — 领域知识、策略、操作流程

加载器将解析后的内容缓存到内存中，并通过轮询文件 ``mtime`` 来检测变更
以支持热重载（清除缓存，使下一次读取获取最新内容）。热重载基于 mtime
轮询——不需要 OS 级别的文件监控依赖。
"""

from __future__ import annotations
from typing import Any

from pathlib import Path

import yaml
from structlog import get_logger

from src.config import get_settings

logger = get_logger("memory.static_loader")


class _CachedStaticMemory:
    """单个 agent 静态记忆的内存缓存条目。"""

    __slots__ = ("content", "mtime")

    def __init__(self, content: str, mtime: float) -> None:
        """创建静态记忆缓存条目。

        Args:
            content: 组装后的静态记忆文本。
            mtime: 源文件最大修改时间（用于热重载检测）。
        """
        self.content: str = content
        self.mtime: float = mtime


class StaticMemoryLoader:
    """
    加载、缓存和热重载 Agent 的静态记忆。

    文件布局（相对于 ``CONFIG_BASE_PATH/agents/{agent_name}/``）::

        memory/
          agent-memory.yaml      # 入口点：memory_type、fields
          personality.md         # 角色身份和风格
          facts/
            *.yaml               # 领域知识

    热重载：``check_and_reload()`` 轮询所有监控文件的最大 mtime。
    如果有任何文件自上次加载以来发生了变更，缓存将失效，下一次
    ``load()`` 调用会从磁盘重新读取。
    """

    def __init__(self) -> None:
        """从配置初始化静态记忆加载器（按 agent 名称缓存）。"""
        self._settings = get_settings()
        self._base_path: str = self._settings.CONFIG_BASE_PATH
        # agent_name -> _CachedStaticMemory
        self._cache: dict[str, _CachedStaticMemory] = {}

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def load(self, agent_name: str) -> str:
        """
        为 *agent_name* 加载并返回组装后的静态记忆文本。

        文本按以下顺序组装：
        1. ``personality.md`` 内容（角色身份、风格、规则）
        2. ``facts/*.yaml`` 内容（领域知识，以文本形式呈现）

        结果被缓存；调用 :meth:`check_and_reload` 来检测文件
        变更并使缓存失效。

        Args:
            agent_name: Agent 标识符（= agents/ 下的目录名）。

        Returns:
            组装后的静态记忆文本。如果 agent 没有记忆文件，
            则返回空字符串。
        """
        cached: Skill | None = self._cache.get(agent_name)
        if cached is not None:
            return cached.content

        content: str
        mtime: float
        content, mtime = self._load_from_disk(agent_name)
        self._cache[agent_name] = _CachedStaticMemory(content, mtime)
        return content

    def check_and_reload(self, agent_name: str) -> bool:
        """
        检查 *agent_name* 的任何静态记忆文件自上次加载以来
        是否在磁盘上发生了变更。

        如果检测到变更，缓存将失效，下一次 :meth:`load` 调用
        会从磁盘重新读取。

        Args:
            agent_name: Agent 标识符。

        Returns:
            如果缓存已失效（文件变更或尚未缓存）返回 ``True``，
            如果缓存内容仍然是最新的返回 ``False``。
        """
        memory_dir: Path = self._memory_dir(agent_name)
        watched_files: list[Path] = self._discover_files(memory_dir)
        if not watched_files:
            # 完全没有文件 —— 如果之前缓存过则使其失效
            if agent_name in self._cache:
                del self._cache[agent_name]
                return True
            return False

        current_mtime: float = self._max_mtime(watched_files)
        cached: Skill | None = self._cache.get(agent_name)
        if cached is None or current_mtime > cached.mtime:
            # 使其失效；下一次 load() 会重新读取
            self._cache.pop(agent_name, None)
            return True
        return False

    def invalidate(self, agent_name: str) -> None:
        """强制清除 *agent_name* 的缓存（用于配置热重载时）。"""
        self._cache.pop(agent_name, None)
        logger.debug("Static memory cache invalidated", agent_name=agent_name)

    def invalidate_all(self) -> None:
        """清除整个静态记忆缓存。"""
        self._cache.clear()
        logger.debug("All static memory caches invalidated")

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    def _memory_dir(self, agent_name: str) -> Path:
        """返回 *agent_name* 的 ``memory/`` 目录路径。"""
        return (
            Path(self._base_path) / "agents" / agent_name / "memory"
        )

    def _discover_files(self, memory_dir: Path) -> list[Path]:
        """
        发现 *memory_dir* 下的所有静态记忆文件。

        返回 ``agent-memory.yaml`` 入口点（如果存在）、
        ``personality.md`` 文件和所有 ``facts/*.yaml`` 文件。
        """
        if not memory_dir.exists():
            return []

        files: list[Path] = []

        # 入口点配置
        entry: Any = memory_dir / "agent-memory.yaml"
        if entry.exists():
            files.append(entry)

        # 人格 markdown
        personality: Any = memory_dir / "personality.md"
        if personality.exists():
            files.append(personality)

        # Facts 目录
        facts_dir: Any = memory_dir / "facts"
        if facts_dir.exists():
            for f in sorted(facts_dir.iterdir()):
                if f.suffix in (".yaml", ".yml") and f.is_file():
                    files.append(f)

        return files

    @staticmethod
    def _max_mtime(files: list[Path]) -> float:
        """返回 *files* 中的最大 mtime。"""
        return max(f.stat().st_mtime for f in files if f.exists())

    def _load_from_disk(self, agent_name: str) -> tuple[str, float]:
        """
        从磁盘读取 *agent_name* 的所有静态记忆文件。

        返回 (组装文本, 最大 mtime) 的元组。
        """
        memory_dir: Path = self._memory_dir(agent_name)
        files: list[Path] = self._discover_files(memory_dir)

        if not files:
            logger.debug(
                "No static memory files found",
                agent_name=agent_name,
                path=str(memory_dir),
            )
            return "", 0.0

        parts: list[str] = []

        # 1. 解析入口点 YAML 以确定要包含哪些字段
        entry_path: Any = memory_dir / "agent-memory.yaml"
        fields_order: list[str] = []
        if entry_path.exists():
            entry_data: dict[str, Any] = self._read_yaml(entry_path)
            fields_order: list[str] = self._parse_fields(entry_data)

        # 2. 加载 personality.md
        personality_path: Any = memory_dir / "personality.md"
        personality_text: str = ""
        if personality_path.exists():
            personality_text: str = self._read_text(personality_path)
            if personality_text:
                parts.append("# 角色人格\n")
                parts.append(personality_text.strip())
                parts.append("\n")

        # 3. 加载 facts/*.yaml
        facts_dir: Any = memory_dir / "facts"
        if facts_dir.exists():
            fact_files: Any = sorted(
                f for f in facts_dir.iterdir()
                if f.suffix in (".yaml", ".yml") and f.is_file()
            )
            for fact_file in fact_files:
                fact_text: str = self._render_yaml_as_text(fact_file)
                if fact_text:
                    parts.append(fact_text)

        # 4. 如果没有入口点 YAML 指导，使用默认顺序
        if not fields_order and not parts:
            # 回退方案：直接输出存在的文件内容
            for f in files:
                if f.suffix == ".md":
                    parts.append(self._read_text(f).strip())
                elif f.suffix in (".yaml", ".yml") and f.name != "agent-memory.yaml":
                    parts.append(self._render_yaml_as_text(f))

        content: str = "\n\n".join(p for p in parts if p.strip())
        max_mtime: float = self._max_mtime(files)
        logger.debug(
            "Static memory loaded from disk",
            agent_name=agent_name,
            file_count=len(files),
            content_length=len(content),
        )
        return content, max_mtime

    @staticmethod
    def _read_text(path: Path) -> str:
        """以 UTF-8 编码读取文本文件。"""
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read file", path=str(path), error=str(exc))
            return ""

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        """读取并解析 YAML 文件。"""
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as exc:
            logger.warning("Failed to parse YAML", path=str(path), error=str(exc))
            return {}

    @classmethod
    def _render_yaml_as_text(cls, path: Path) -> str:
        """
        读取 YAML facts 文件并将其呈现为人类可读的文本。

        每个顶级键成为一个章节标题；嵌套的键/值以 ``key: value``
        行或子章节的形式呈现。
        """
        data: dict[str, Any] = cls._read_yaml(path)
        if not data:
            return ""

        lines: list[str] = []
        section_title: Any = path.stem.replace("_", " ").replace("-", " ").title()
        lines.append(f"# {section_title}")
        cls._render_yaml_node(data, lines, indent=0)
        return "\n".join(lines)

    @classmethod
    def _render_yaml_node(
        cls,
        node: Any,
        lines: list[str],
        indent: int,
    ) -> None:
        """递归将 YAML 数据节点呈现为缩进的文本行。"""
        prefix: Any = "  " * indent
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, dict):
                    lines.append(f"{prefix}{key}:")
                    cls._render_yaml_node(value, lines, indent + 1)
                elif isinstance(value, list):
                    lines.append(f"{prefix}{key}:")
                    for item in value:
                        if isinstance(item, (dict, list)):
                            cls._render_yaml_node(item, lines, indent + 1)
                        else:
                            lines.append(f"{prefix}  - {item}")
                else:
                    lines.append(f"{prefix}{key}: {value}")
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    cls._render_yaml_node(item, lines, indent)
                else:
                    lines.append(f"{prefix}- {item}")
        else:
            lines.append(f"{prefix}{node}")

    @staticmethod
    def _parse_fields(entry_data: dict[str, Any]) -> list[str]:
        """
        从 agent-memory.yaml 入口点解析 ``fields`` 列表。

        预期结构::

            memory_type: static
            fields:
              - personality
              - facts

        返回字段名称列表（默认为 ``["personality", "facts"]``）。
        """
        fields: Skill | None = entry_data.get("fields", [])
        if isinstance(fields, list):
            return [str(f) for f in fields]
        return ["personality", "facts"]


# ---------------------------------------------------------------------------
# 单例
# ---------------------------------------------------------------------------

_static_memory_loader: StaticMemoryLoader | None = None


def get_static_memory_loader() -> StaticMemoryLoader:
    """返回单例 StaticMemoryLoader 实例。"""
    global _static_memory_loader
    if _static_memory_loader is None:
        _static_memory_loader = StaticMemoryLoader()
    return _static_memory_loader
