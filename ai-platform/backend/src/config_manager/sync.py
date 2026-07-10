"""ConfigSync — 文件系统与数据库之间的双向同步。

在 DUAL 模式下，保持 configs/ YAML 文件和 agent_configs 数据库表同步：
- 文件变更 → 同步到数据库（upsert）
- 数据库变更 → 同步到文件（写入 YAML）

这样可同时支持基于 Git 的配置管理（文件）和在线编辑（数据库）。
"""

from __future__ import annotations
from typing import Any

import json
from pathlib import Path

import yaml
from sqlalchemy import select

from src.config import get_settings
from src.db.session import db_session_context
from src.models.agent import AgentConfigModel
from src.utils.logging import get_logger

logger = get_logger("config_manager.sync")


class ConfigSync:
    """
    文件系统配置与数据库之间的双向同步。

    方法：
    - file_to_db：将文件系统的配置写入数据库
    - db_to_file：将数据库的配置写入文件系统
    - sync_all：全量双向同步
    """

    def __init__(self) -> None:
        """从应用配置初始化双向同步器。"""
        self._settings = get_settings()
        self._base_path: str = self._settings.CONFIG_BASE_PATH

    async def file_to_db(self, agent_id: str) -> None:
        """
        将单个 agent 的配置从文件系统同步到数据库。

        读取 YAML 文件，解析后 upsert 到 agent_configs 表。
        """
        agent_dir: Any = Path(self._base_path) / "agents" / agent_id
        agent_yaml: Any = agent_dir / "agent.yaml"

        if not agent_yaml.exists():
            logger.warning("Agent YAML not found for sync", agent_id=agent_id)
            return

        try:
            with open(agent_yaml, encoding="utf-8") as f:
                config_data: Any = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            logger.error("Failed to parse YAML for sync", agent_id=agent_id, error=str(exc))
            return

        agent_section: dict[str, Any] = config_data.get("agent", config_data)
        config_json: str = json.dumps(config_data, ensure_ascii=False)

        # 如果存在则加载 metadata
        metadata_yaml: Any = agent_dir / "metadata.yaml"
        metadata_str: str = ""
        if metadata_yaml.exists():
            with open(metadata_yaml, encoding="utf-8") as f:
                metadata_str: Any = f.read()

        routing: dict[str, Any] = agent_section.get("routing", {})

        async with db_session_context() as session:
            # 检查记录是否已存在
            stmt: Any = select(AgentConfigModel).where(
                AgentConfigModel.agent_id == agent_id
            )
            result: Any = await session.execute(stmt)
            existing: Any = result.scalar_one_or_none()

            if existing:
                # 更新
                existing.display_name = agent_section.get("display_name", agent_id)
                existing.description = agent_section.get("description", "")
                existing.version = agent_section.get("version", "1.0.0")
                existing.config_yaml = config_json
                existing.metadata_yaml = metadata_str
                existing.routing_enabled = routing.get("enabled", True)
                existing.routing_priority = routing.get("priority", 10)
                existing.routing_keywords = json.dumps(
                    routing.get("keywords", []), ensure_ascii=False
                )
                existing.runtime_type = config_data.get("runtime", {}).get(
                    "type", "openharness"
                )
                existing.is_active = True
            else:
                # 插入
                record: AgentConfigModel = AgentConfigModel(
                    agent_id=agent_id,
                    display_name=agent_section.get("display_name", agent_id),
                    description=agent_section.get("description", ""),
                    version=agent_section.get("version", "1.0.0"),
                    config_yaml=config_json,
                    metadata_yaml=metadata_str,
                    routing_enabled=routing.get("enabled", True),
                    routing_priority=routing.get("priority", 10),
                    routing_keywords=json.dumps(
                        routing.get("keywords", []), ensure_ascii=False
                    ),
                    runtime_type=config_data.get("runtime", {}).get(
                        "type", "openharness"
                    ),
                    is_active=True,
                )
                session.add(record)

        logger.info("Config synced file → DB", agent_id=agent_id)

    async def db_to_file(self, agent_id: str) -> None:
        """
        将单个 agent 的配置从数据库同步到文件系统。

        读取 agent_configs 记录并写入 YAML 文件。
        """
        async with db_session_context() as session:
            stmt: Any = select(AgentConfigModel).where(
                AgentConfigModel.agent_id == agent_id,
                AgentConfigModel.is_deleted == False,  # noqa: E712
            )
            result: Any = await session.execute(stmt)
            row: Any = result.scalar_one_or_none()

        if row is None:
            logger.warning("Agent config not found in DB for sync", agent_id=agent_id)
            return

        agent_dir: Any = Path(self._base_path) / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        # 写入 agent.yaml
        config_data: Any = json.loads(row.config_yaml) if row.config_yaml else {}
        agent_yaml: Any = agent_dir / "agent.yaml"
        with open(agent_yaml, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

        # 如果存在则写入 metadata.yaml
        if row.metadata_yaml:
            metadata_path: Any = agent_dir / "metadata.yaml"
            with open(metadata_path, "w", encoding="utf-8") as f:
                f.write(row.metadata_yaml)

        logger.info("Config synced DB → file", agent_id=agent_id)

    async def sync_all_files_to_db(self) -> int:
        """
        将所有文件系统的配置同步到数据库。

        Returns:
            同步的配置数量。
        """
        agents_dir: Any = Path(self._base_path) / "agents"
        if not agents_dir.exists():
            return 0

        count: int = 0
        for entry in sorted(agents_dir.iterdir()):
            if entry.is_dir() and (entry / "agent.yaml").exists():
                try:
                    await self.file_to_db(entry.name)
                    count += 1
                except Exception as exc:
                    logger.error(
                        "Failed to sync config to DB",
                        agent_id=entry.name,
                        error=str(exc),
                    )

        logger.info("Batch sync file → DB complete", count=count)
        return count

    async def sync_all_db_to_files(self) -> int:
        """
        将所有数据库配置同步到文件系统。

        Returns:
            同步的配置数量。
        """
        async with db_session_context() as session:
            stmt: Any = select(AgentConfigModel).where(
                AgentConfigModel.is_deleted == False,  # noqa: E712
                AgentConfigModel.is_active == True,  # noqa: E712
            )
            result: Any = await session.execute(stmt)
            rows: Any = result.scalars().all()

        count: int = 0
        for row in rows:
            try:
                await self.db_to_file(row.agent_id)
                count += 1
            except Exception as exc:
                logger.error(
                    "Failed to sync config to file",
                    agent_id=row.agent_id,
                    error=str(exc),
                )

        logger.info("Batch sync DB → file complete", count=count)
        return count


# 单例实例
_config_sync: ConfigSync | None = None


def get_config_sync() -> ConfigSync:
    """返回单例 ConfigSync 实例。"""
    global _config_sync
    if _config_sync is None:
        _config_sync = ConfigSync()
    return _config_sync
