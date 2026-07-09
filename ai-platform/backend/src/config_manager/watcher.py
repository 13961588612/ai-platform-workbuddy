"""ConfigWatcher — 监控配置变更以支持热重载。

在 FILE_SYSTEM 模式下，使用 watchdog 监控 YAML 文件变更。
在 DATABASE 模式下，每隔 N 秒轮询 agent_configs 表。
检测到变更后，通知 ConfigManager 触发 AgentManager 热重载。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.utils.logging import get_logger

logger = get_logger("config_manager.watcher")


class ConfigWatcher:
    """
    监控配置变更并触发回调。

    文件系统模式使用 asyncio 任务进行周期性目录扫描（如果 watchdog
    依赖可用，可以启用）。数据库模式轮询 agent_configs 表的 updated_at
    变更。

    回调函数会接收到发生变更的配置的 agent_id。
    """

    def __init__(self) -> None:
        """初始化配置变更监控器（文件 mtime 或数据库轮询）。"""
        self._settings = get_settings()
        self._base_path: str = self._settings.CONFIG_BASE_PATH
        self._mode: str = self._settings.CONFIG_MODE
        self._poll_interval: int = self._settings.CONFIG_RELOAD_INTERVAL
        self._callbacks: list[Any] = []
        self._task: asyncio.Task[None] | None = None
        self._running: bool = False
        self._file_mtimes: dict[str, float] = {}
        self._db_versions: dict[str, str] = {}

    def on_change(self, callback: Any) -> None:
        """
        为配置变更注册回调。

        回调函数接收以下参数：
        - agent_id: str — 变更的 agent 的 ID
        - change_type: str — "created"、"updated" 或 "deleted"
        """
        self._callbacks.append(callback)

    async def start(self) -> None:
        """开始监控配置变更。"""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._watch_loop())
        logger.info(
            "ConfigWatcher started",
            mode=self._mode,
            poll_interval=self._poll_interval,
        )

    async def stop(self) -> None:
        """停止监控配置变更。"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("ConfigWatcher stopped")

    async def _watch_loop(self) -> None:
        """主监控循环 —— 按配置的时间间隔轮询变更。"""
        # 初始快照
        await self._take_snapshot()

        while self._running:
            try:
                await asyncio.sleep(self._poll_interval)
                await self._check_for_changes()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("ConfigWatcher error", error=str(exc))
                await asyncio.sleep(self._poll_interval)

    async def _take_snapshot(self) -> None:
        """获取当前配置状态的初始快照。"""
        if self._mode == "database":
            await self._snapshot_db()
        else:
            self._snapshot_files()

    def _snapshot_files(self) -> None:
        """快照文件修改时间。"""
        agents_dir = Path(self._base_path) / "agents"
        if not agents_dir.exists():
            return

        self._file_mtimes.clear()
        for entry in agents_dir.iterdir():
            if not entry.is_dir():
                continue
            agent_yaml = entry / "agent.yaml"
            if agent_yaml.exists():
                self._file_mtimes[entry.name] = agent_yaml.stat().st_mtime

    async def _snapshot_db(self) -> None:
        """快照数据库配置版本。"""
        from sqlalchemy import select

        from src.db.session import db_session_context
        from src.models.agent import AgentConfigModel

        self._db_versions.clear()
        try:
            async with db_session_context() as session:
                stmt = select(AgentConfigModel.agent_id, AgentConfigModel.updated_at).where(
                    AgentConfigModel.is_deleted == False,  # noqa: E712
                )
                result = await session.execute(stmt)
                for row in result:
                    self._db_versions[row[0]] = row[1].isoformat() if row[1] else ""
        except Exception as exc:
            logger.error("Failed to snapshot DB configs", error=str(exc))

    async def _check_for_changes(self) -> None:
        """检查自上次快照以来的配置变更。"""
        if self._mode == "database":
            await self._check_db_changes()
        else:
            self._check_file_changes()

    def _check_file_changes(self) -> None:
        """检查文件系统变更。"""
        agents_dir = Path(self._base_path) / "agents"
        if not agents_dir.exists():
            return

        current_mtimes: dict[str, float] = {}
        current_dirs: set[str] = set()

        for entry in agents_dir.iterdir():
            if not entry.is_dir():
                continue
            current_dirs.add(entry.name)
            agent_yaml = entry / "agent.yaml"
            if agent_yaml.exists():
                current_mtimes[entry.name] = agent_yaml.stat().st_mtime

        # 检查新增或更新的配置
        for agent_id, mtime in current_mtimes.items():
            old_mtime = self._file_mtimes.get(agent_id)
            if old_mtime is None:
                self._notify_change(agent_id, "created")
            elif mtime > old_mtime:
                self._notify_change(agent_id, "updated")

        # 检查已删除的配置
        for agent_id in self._file_mtimes:
            if agent_id not in current_dirs:
                self._notify_change(agent_id, "deleted")

        self._file_mtimes = current_mtimes

    async def _check_db_changes(self) -> None:
        """检查数据库配置变更。"""
        from sqlalchemy import select

        from src.db.session import db_session_context
        from src.models.agent import AgentConfigModel

        current_versions: dict[str, str] = {}
        try:
            async with db_session_context() as session:
                stmt = select(
                    AgentConfigModel.agent_id,
                    AgentConfigModel.updated_at,
                    AgentConfigModel.is_deleted,
                )
                result = await session.execute(stmt)
                for row in result:
                    agent_id = row[0]
                    version = row[1].isoformat() if row[1] else ""
                    is_deleted = row[2]
                    if is_deleted:
                        current_versions[agent_id] = "deleted"
                    else:
                        current_versions[agent_id] = version
        except Exception as exc:
            logger.error("Failed to check DB config changes", error=str(exc))
            return

        # 与之前的快照进行比较
        for agent_id, version in current_versions.items():
            old_version = self._db_versions.get(agent_id)
            if old_version is None:
                if version != "deleted":
                    self._notify_change(agent_id, "created")
            elif version == "deleted" and old_version != "deleted":
                self._notify_change(agent_id, "deleted")
            elif version != old_version and version != "deleted":
                self._notify_change(agent_id, "updated")

        self._db_versions = current_versions

    def _notify_change(self, agent_id: str, change_type: str) -> None:
        """通知所有已注册的回调函数发生了配置变更。"""
        logger.info(
            "Config change detected",
            agent_id=agent_id,
            change_type=change_type,
        )
        for callback in self._callbacks:
            try:
                result = callback(agent_id, change_type)
                # 同时支持同步和异步回调
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as exc:
                logger.error(
                    "Config change callback failed",
                    agent_id=agent_id,
                    error=str(exc),
                )


# 单例实例
_config_watcher: ConfigWatcher | None = None


def get_config_watcher() -> ConfigWatcher:
    """返回单例 ConfigWatcher 实例。"""
    global _config_watcher
    if _config_watcher is None:
        _config_watcher = ConfigWatcher()
    return _config_watcher
