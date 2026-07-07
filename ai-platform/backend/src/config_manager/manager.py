"""ConfigManager — 中央配置管理编排器。

协调 ConfigLoader、ConfigValidator、ConfigWatcher 和 ConfigSync，
提供统一的配置管理接口。支持三种模式：FILE_SYSTEM、DATABASE 和 DUAL。

在 DUAL 模式下，文件系统为数据源头，变更会自动同步到数据库以支持在线编辑。
"""

from __future__ import annotations

from typing import Any

from src.agent.config import AgentConfig
from src.config import get_settings
from src.config_manager.loader import ConfigLoader, get_config_loader
from src.config_manager.sync import ConfigSync, get_config_sync
from src.config_manager.validator import ConfigValidator, get_config_validator
from src.config_manager.watcher import ConfigWatcher, get_config_watcher
from src.utils.exceptions import ConfigValidationError
from src.utils.logging import get_logger

logger = get_logger("config_manager.manager")


class ConfigManager:
    """
    所有 Agent 实例的中央配置管理。

    职责：
    - 从文件系统和/或数据库加载 agent 配置
    - 在激活前验证配置
    - 监控配置变更并触发热重载
    - 在文件系统和数据库之间同步配置（DUAL 模式）
    - 提供对所有活跃 agent 配置的访问

    模式：
    - FILE_SYSTEM：configs/ YAML 文件（Git 管理）
    - DATABASE：PostgreSQL agent_configs 表（在线编辑）
    - DUAL：两者并用，文件系统作为数据源头
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._mode: str = self._settings.CONFIG_MODE
        self._loader: ConfigLoader = get_config_loader()
        self._validator: ConfigValidator = get_config_validator()
        self._watcher: ConfigWatcher = get_config_watcher()
        self._sync: ConfigSync = get_config_sync()
        self._configs: dict[str, AgentConfig] = {}
        self._on_config_change_callbacks: list[Any] = []
        self._initialized: bool = False

    async def initialize(self) -> None:
        """初始化 ConfigManager —— 加载所有配置并开始监控。"""
        logger.info("ConfigManager initializing", mode=self._mode)

        # 初始加载
        await self.reload_all()

        # 注册内部变更处理器
        self._watcher.on_change(self._handle_config_change)

        # 如果启用了监控则启动
        if self._settings.CONFIG_WATCH_ENABLED:
            await self._watcher.start()

        # DUAL 模式下的初始同步
        if self._mode == "dual":
            await self._sync.sync_all_files_to_db()

        self._initialized = True
        logger.info(
            "ConfigManager initialized",
            agent_count=len(self._configs),
            agents=list(self._configs.keys()),
        )

    async def shutdown(self) -> None:
        """关闭 ConfigManager 并停止监控。"""
        await self._watcher.stop()
        self._configs.clear()
        self._initialized = False
        logger.info("ConfigManager shut down")

    async def reload_all(self) -> None:
        """从数据源重新加载所有 agent 配置。"""
        configs = await self._loader.load_all_agents()
        self._configs = {config.agent_id: config for config in configs}
        logger.info("All configs reloaded", count=len(self._configs))

    async def get_config(self, agent_id: str) -> AgentConfig:
        """
        获取单个 agent 的配置。

        Args:
            agent_id: Agent ID。

        Returns:
            指定 agent 的 AgentConfig。

        Raises:
            KeyError: agent 配置不存在时抛出。
        """
        if agent_id not in self._configs:
            # 尝试按需加载
            try:
                config = await self._loader.load_agent_config(agent_id)
                self._configs[agent_id] = config
                return config
            except Exception:
                raise KeyError(f"Agent config not found: {agent_id}")
        return self._configs[agent_id]

    def get_config_cached(self, agent_id: str) -> AgentConfig | None:
        """获取缓存的配置而不加载（未缓存时返回 None）。"""
        return self._configs.get(agent_id)

    def list_configs(self) -> list[AgentConfig]:
        """列出所有已加载的 agent 配置。"""
        return list(self._configs.values())

    def list_agent_ids(self) -> list[str]:
        """列出所有已加载的 agent ID。"""
        return list(self._configs.keys())

    async def save_config(self, config: AgentConfig) -> None:
        """
        保存新的或更新的 agent 配置。

        验证配置后，根据模式保存到适当的存储（文件系统、数据库或两者）。

        Args:
            config: 要保存的 AgentConfig。

        Raises:
            ConfigValidationError: 验证失败时抛出。
        """
        # 验证
        self._validator.validate_or_raise(config)

        # 根据模式保存
        if self._mode in ("file_system", "dual"):
            await self._save_to_file(config)

        if self._mode in ("database", "dual"):
            await self._save_to_db(config)

        # 更新内存缓存
        self._configs[config.agent_id] = config

        logger.info("Config saved", agent_id=config.agent_id, mode=self._mode)

    async def delete_config(self, agent_id: str) -> None:
        """删除 agent 配置。"""
        if self._mode in ("file_system", "dual"):
            self._delete_from_file(agent_id)

        if self._mode in ("database", "dual"):
            await self._delete_from_db(agent_id)

        self._configs.pop(agent_id, None)
        logger.info("Config deleted", agent_id=agent_id)

    def on_config_change(self, callback: Any) -> None:
        """
        为配置变更事件注册回调。

        回调函数接收 (agent_id, change_type, config) 参数。
        change_type 为 "created"、"updated" 或 "deleted"。
        """
        self._on_config_change_callbacks.append(callback)

    async def _handle_config_change(
        self,
        agent_id: str,
        change_type: str,
    ) -> None:
        """处理监控器检测到的配置变更。"""
        logger.info(
            "Config change detected by watcher",
            agent_id=agent_id,
            change_type=change_type,
        )

        config: AgentConfig | None = None

        if change_type == "deleted":
            self._configs.pop(agent_id, None)
        else:
            try:
                config = await self._loader.load_agent_config(agent_id)
                errors = self._validator.validate(config)
                if errors:
                    logger.error(
                        "Config validation failed on reload",
                        agent_id=agent_id,
                        errors=errors,
                    )
                    return
                self._configs[agent_id] = config

                # DUAL 模式下同步到数据库
                if self._mode == "dual":
                    await self._sync.file_to_db(agent_id)
            except Exception as exc:
                logger.error(
                    "Failed to reload config after change",
                    agent_id=agent_id,
                    error=str(exc),
                )
                return

        # 通知所有已注册的回调
        for callback in self._on_config_change_callbacks:
            try:
                result = callback(agent_id, change_type, config)
                if hasattr(result, "__await__"):
                    await result
            except Exception as exc:
                logger.error(
                    "Config change callback failed",
                    agent_id=agent_id,
                    error=str(exc),
                )

    async def _save_to_file(self, config: AgentConfig) -> None:
        """将配置保存到文件系统。"""
        import yaml
        from pathlib import Path

        agent_dir = Path(self._settings.CONFIG_BASE_PATH) / "agents" / config.agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "agent": {
                "name": config.agent_id,
                "display_name": config.display_name,
                "description": config.description,
                "version": config.version,
                "tags": config.tags,
                "routing": {
                    "keywords": config.routing.keywords,
                    "enabled": config.routing.enabled,
                    "priority": config.routing.priority,
                },
            }
        }
        agent_yaml = agent_dir / "agent.yaml"
        with open(agent_yaml, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    async def _save_to_db(self, config: AgentConfig) -> None:
        """将配置保存到数据库。"""
        import json
        import uuid
        from sqlalchemy import select

        from src.db.session import db_session_context
        from src.models.agent import AgentConfigModel

        config_json = json.dumps(
            {"agent": {
                "name": config.agent_id,
                "display_name": config.display_name,
                "description": config.description,
                "version": config.version,
                "tags": config.tags,
            }},
            ensure_ascii=False,
        )

        async with db_session_context() as session:
            stmt = select(AgentConfigModel).where(
                AgentConfigModel.agent_id == config.agent_id
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.display_name = config.display_name
                existing.description = config.description
                existing.version = config.version
                existing.config_yaml = config_json
                existing.routing_enabled = config.routing.enabled
                existing.routing_priority = config.routing.priority
                existing.routing_keywords = json.dumps(
                    config.routing.keywords, ensure_ascii=False
                )
                existing.runtime_type = config.runtime.type
            else:
                record = AgentConfigModel(
                    id=uuid.uuid4(),
                    agent_id=config.agent_id,
                    display_name=config.display_name,
                    description=config.description,
                    version=config.version,
                    config_yaml=config_json,
                    routing_enabled=config.routing.enabled,
                    routing_priority=config.routing.priority,
                    routing_keywords=json.dumps(
                        config.routing.keywords, ensure_ascii=False
                    ),
                    runtime_type=config.runtime.type,
                    is_active=True,
                )
                session.add(record)

    def _delete_from_file(self, agent_id: str) -> None:
        """从文件系统删除配置。"""
        import shutil
        from pathlib import Path

        agent_dir = Path(self._settings.CONFIG_BASE_PATH) / "agents" / agent_id
        if agent_dir.exists():
            shutil.rmtree(agent_dir)

    async def _delete_from_db(self, agent_id: str) -> None:
        """在数据库中软删除配置。"""
        from sqlalchemy import select

        from src.db.session import db_session_context
        from src.models.agent import AgentConfigModel

        async with db_session_context() as session:
            stmt = select(AgentConfigModel).where(
                AgentConfigModel.agent_id == agent_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()
            if record:
                record.is_deleted = True
                record.is_active = False


# 单例实例
_config_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    """返回单例 ConfigManager 实例。"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
