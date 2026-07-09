"""ConfigLoader — 从 YAML 文件加载和解析 Agent 配置。

在 FILE_SYSTEM 模式下，从 configs/agents/{agent_id}/agent.yaml
及其包含的子配置文件（runtime.yaml、model.yaml 等）读取。
在 DATABASE 模式下，从 agent_configs PostgreSQL 表读取。
"""

from __future__ import annotations
from typing import Any

import json
import os
from pathlib import Path

import yaml
from sqlalchemy import select

from src.agent.config import AgentConfig
from src.config import get_settings
from src.db.session import db_session_context
from src.models.agent import AgentConfigModel
from src.utils.exceptions import ConfigLoadError, ConfigNotFoundError
from src.utils.logging import get_logger

logger = get_logger("config_manager.loader")


class ConfigLoader:
    """
    从文件系统或数据库加载 Agent 配置。

    支持两种模式：
    - FILE_SYSTEM：从 configs/ 目录读取 YAML 文件
    - DATABASE：查询 agent_configs PostgreSQL 表
    """

    def __init__(self) -> None:
        """从应用配置初始化配置加载器（文件系统或数据库模式）。"""
        self._settings = get_settings()
        self._base_path: str = self._settings.CONFIG_BASE_PATH
        self._mode: str = self._settings.CONFIG_MODE

    async def load_agent_config(self, agent_id: str) -> AgentConfig:
        """
        加载单个 Agent 的配置。

        Args:
            agent_id: Agent ID（= 文件模式下的目录名）。

        Returns:
            解析后的 AgentConfig 对象。

        Raises:
            ConfigNotFoundError: Agent 配置不存在时抛出。
            ConfigLoadError: 配置文件无法解析时抛出。
        """
        if self._mode == "database":
            return await self._load_from_db(agent_id)
        return self._load_from_file(agent_id)

    async def load_all_agents(self) -> list[AgentConfig]:
        """加载所有 Agent 配置。"""
        if self._mode == "database":
            return await self._load_all_from_db()
        return self._load_all_from_file()

    def _load_from_file(self, agent_id: str) -> AgentConfig:
        """从文件系统加载 agent 配置。"""
        agent_dir: Any = Path(self._base_path) / "agents" / agent_id
        agent_yaml: Any = agent_dir / "agent.yaml"

        if not agent_yaml.exists():
            raise ConfigNotFoundError(str(agent_yaml))

        try:
            with open(agent_yaml, encoding="utf-8") as f:
                data: Any = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigLoadError(str(agent_yaml), str(exc))

        # 加载引用的子配置文件
        data: dict[str, Any] = self._resolve_includes(data, agent_dir)

        config: AgentConfig = AgentConfig.from_yaml_dict(data)
        config.config_path = str(agent_yaml)
        return config

    def _resolve_includes(
        self,
        data: dict[str, Any],
        agent_dir: Path,
    ) -> dict[str, Any]:
        """解析 agent.yaml 中引用的子配置文件。"""
        agent_section: Skill | None = data.get("agent", data)
        includes: Skill | None = agent_section.get("includes", {})

        # 加载 runtime 配置
        if "runtime" in includes:
            runtime_path: Any = agent_dir / includes["runtime"]
            runtime_data: dict[str, Any] = self._load_yaml(runtime_path)
            if runtime_data:
                data.setdefault("runtime", {}).update(
                    runtime_data.get("runtime", runtime_data)
                )

        # 加载 model 配置
        if "system" in includes:
            model_path: Any = agent_dir / includes["system"]
            model_data: dict[str, Any] = self._load_yaml(model_path)
            if model_data:
                data.setdefault("model", {}).update(
                    model_data.get("model", model_data)
                )

        # 加载 metadata
        metadata_path: Any = agent_dir / "metadata.yaml"
        if metadata_path.exists():
            metadata_data: dict[str, Any] = self._load_yaml(metadata_path)
            if metadata_data:
                data.setdefault("metadata", {}).update(
                    metadata_data.get("metadata", metadata_data)
                )

        # 加载已启用的 skills
        skills_path: Any = agent_dir / "skills" / "enabled-skills.yaml"
        if skills_path.exists():
            skills_data: dict[str, Any] = self._load_yaml(skills_path)
            if skills_data:
                data["skills"] = skills_data.get("skills", skills_data)

        # 加载 MCP server 配置
        mcp_path: Any = agent_dir / "system" / "mcp-servers.yaml"
        if mcp_path.exists():
            mcp_data: dict[str, Any] = self._load_yaml(mcp_path)
            if mcp_data:
                data["mcp_servers"] = mcp_data.get("mcp_servers", [])

        # 当 system prompt 通过路径引用时，从 markdown 文件加载
        runtime_section: Skill | None = data.get("runtime", {})
        prompts: Skill | None = runtime_section.get("prompts", {})
        system_ref: Any = prompts.get("system") or prompts.get("system_prompt")
        if isinstance(system_ref, str) and system_ref.endswith((".md", ".txt")):
            prompt_path: Any = agent_dir / system_ref
            if prompt_path.is_file():
                try:
                    data["system_prompt"] = prompt_path.read_text(encoding="utf-8")
                except OSError as exc:
                    logger.warning(
                        "Failed to read system prompt",
                        path=str(prompt_path),
                        error=str(exc),
                    )

        return data

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        """加载 YAML 文件并将其内容作为字典返回。"""
        if not path.exists():
            return {}
        try:
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            logger.warning("Failed to parse YAML", path=str(path), error=str(exc))
            return {}

    def _load_all_from_file(self) -> list[AgentConfig]:
        """从文件系统加载所有 agent 配置。"""
        agents_dir: Any = Path(self._base_path) / "agents"
        if not agents_dir.exists():
            logger.warning("Agents config directory not found", path=str(agents_dir))
            return []

        configs: list[AgentConfig] = []
        for entry in sorted(agents_dir.iterdir()):
            if not entry.is_dir():
                continue
            agent_yaml: Any = entry / "agent.yaml"
            if not agent_yaml.exists():
                continue
            try:
                config: AgentConfig = self._load_from_file(entry.name)
                configs.append(config)
            except Exception as exc:
                logger.error(
                    "Failed to load agent config",
                    agent_id=entry.name,
                    error=str(exc),
                )
        return configs

    async def _load_from_db(self, agent_id: str) -> AgentConfig:
        """从数据库加载 agent 配置。"""
        async with db_session_context() as session:
            stmt: Any = select(AgentConfigModel).where(
                AgentConfigModel.agent_id == agent_id,
                AgentConfigModel.is_deleted == False,  # noqa: E712
            )
            result: ToolResult = await session.execute(stmt)
            row: Any = result.scalar_one_or_none()

        if row is None:
            raise ConfigNotFoundError(f"agent_configs:{agent_id}")

        try:
            config_data: Any = json.loads(row.config_yaml) if row.config_yaml else {}
        except (json.JSONDecodeError, TypeError):
            config_data: dict[str, Any] = {}

        config: AgentConfig = AgentConfig.from_yaml_dict(config_data)
        config.config_path = f"db:{agent_id}"
        return config

    async def _load_all_from_db(self) -> list[AgentConfig]:
        """从数据库加载所有 agent 配置。"""
        async with db_session_context() as session:
            stmt: Any = select(AgentConfigModel).where(
                AgentConfigModel.is_deleted == False,  # noqa: E712
                AgentConfigModel.is_active == True,  # noqa: E712
            )
            result: ToolResult = await session.execute(stmt)
            rows: Any = result.scalars().all()

        configs: list[AgentConfig] = []
        for row in rows:
            try:
                config_data: Any = json.loads(row.config_yaml) if row.config_yaml else {}
                config: AgentConfig = AgentConfig.from_yaml_dict(config_data)
                configs.append(config)
            except Exception as exc:
                logger.error(
                    "Failed to parse agent config from DB",
                    agent_id=row.agent_id,
                    error=str(exc),
                )
        return configs

    def list_agent_ids(self) -> list[str]:
        """列出所有可用的 Agent ID（仅文件系统模式）。"""
        agents_dir: Any = Path(self._base_path) / "agents"
        if not agents_dir.exists():
            return []
        return [
            entry.name
            for entry in sorted(agents_dir.iterdir())
            if entry.is_dir() and (entry / "agent.yaml").exists()
        ]


# 单例实例
_config_loader: ConfigLoader | None = None


def get_config_loader() -> ConfigLoader:
    """返回单例 ConfigLoader 实例。"""
    global _config_loader
    if _config_loader is None:
        _config_loader = ConfigLoader()
    return _config_loader
