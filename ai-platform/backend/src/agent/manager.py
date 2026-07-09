"""AgentManager — Agent 实例的生命周期管理。

管理 Agent 实例的创建、启动、暂停、恢复、停止和删除。
与 RuntimeRegistry 协调运行时创建，与 SessionManager 协调会话处理。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from src.agent.config import AgentConfig
from src.agent.lifecycle import InstanceState, LifecycleEvent, LifecycleStateMachine
from src.agent.runtime_setup import wire_agent_runtime
from src.agent.session import Message, Session, get_session_manager
from src.runtime.base import AgentRuntime
from src.runtime.events import AgentEvent, HealthStatus
from src.runtime.factory import create_runtime
from src.runtime.registry import get_runtime_registry
from src.utils.exceptions import AgentNotFoundError, AgentNotRunningError, AgentStateError
from src.utils.logging import get_logger

logger = get_logger("agent.manager")


class AgentInstance:
    """
    一个包含运行时与生命周期状态的运行中 Agent 实例。

    通过委托运行时来处理消息，并追踪活跃会话和健康状态。
    """

    def __init__(self, config: AgentConfig, runtime: AgentRuntime) -> None:
        """创建 Agent 实例包装（状态为 CREATED，运行时待初始化）。

        Args:
            config: Agent 配置。
            runtime: 与此实例绑定的运行时实现。
        """
        self.id: str = config.agent_id
        self.config: AgentConfig = config
        self.runtime: AgentRuntime = runtime
        self.lifecycle: LifecycleStateMachine = LifecycleStateMachine()
        self.started_at: datetime | None = None
        self.active_sessions: int = 0
        self._initialized: bool = False

    async def initialize(self) -> None:
        """使用 Agent 配置初始化运行时。"""
        if not self._initialized:
            await self.runtime.initialize(self.config)
            await wire_agent_runtime(self.runtime, self.config)
            self._initialized = True
            logger.info("Agent instance initialized", agent_id=self.id)

    async def process_message(
        self,
        session: Session,
        message: Message,
    ) -> AsyncIterator[AgentEvent]:
        """
        处理用户消息并产出 AgentEvent 流。

        Args:
            session: 当前活跃会话。
            message: 要处理的用户消息。

        Yields:
            来自运行时的 AgentEvent 对象。
        """
        if not self.lifecycle.is_active():
            raise AgentNotRunningError(self.id)

        self.active_sessions += 1
        try:
            # 构建运行时所需的消息列表
            messages = session.get_messages()
            messages.append(message.to_dict())

            # 通过运行时执行
            async for event in self.runtime.run(
                messages=messages,
                config=self.config,
                session_id=session.session_id,
            ):
                yield event
        finally:
            self.active_sessions -= 1

    async def health_check(self) -> HealthStatus:
        """检查此 Agent 实例的健康状态。"""
        runtime_health = await self.runtime.health_check()
        return HealthStatus(
            healthy=runtime_health.healthy and self.lifecycle.is_active(),
            details={
                "agent_id": self.id,
                "state": self.lifecycle.current_state.value,
                "active_sessions": self.active_sessions,
                "runtime": runtime_health.details,
            },
        )

    async def shutdown(self) -> None:
        """关闭运行时并进行清理。"""
        await self.runtime.shutdown()
        self._initialized = False
        logger.info("Agent instance shut down", agent_id=self.id)


class AgentManager:
    """
    管理 Agent 实例的生命周期。

    职责：
    - 根据 AgentConfig 创建 Agent 实例
    - 管理生命周期状态（启动/暂停/恢复/停止/删除）
    - 提供实例访问以处理消息
    - 支持运行时切换
    - 支持配置热重载
    """

    def __init__(self) -> None:
        """初始化 Agent 管理器（空实例表）。"""
        self._instances: dict[str, AgentInstance] = {}
        self._runtime_registry = get_runtime_registry()
        self._llm_gateway: Any = None

    def set_llm_gateway(self, gateway: Any) -> None:
        """注入 LLM Gateway 供运行时使用。"""
        self._llm_gateway = gateway

    async def create_agent(self, config: AgentConfig) -> AgentInstance:
        """
        根据配置创建一个新的 Agent 实例。

        Args:
            config: 由 ConfigManager 加载的 AgentConfig。

        Returns:
            处于 CREATED 状态的 AgentInstance。

        Raises:
            若已存在相同 ID 的 agent，则抛出 AgentAlreadyExistsError。
        """
        if config.agent_id in self._instances:
            from src.utils.exceptions import AgentAlreadyExistsError

            raise AgentAlreadyExistsError(config.agent_id)

        # Create runtime via registry
        runtime_type = config.runtime.type if config.runtime else None
        runtime = create_runtime(runtime_type, config)

        # Inject LLM gateway if available
        if self._llm_gateway is not None and hasattr(runtime, "set_llm_gateway"):
            runtime.set_llm_gateway(self._llm_gateway)

        instance = AgentInstance(config=config, runtime=runtime)
        await instance.initialize()
        self._instances[config.agent_id] = instance

        logger.info("Agent created", agent_id=config.agent_id)
        return instance

    async def start_agent(self, agent_id: str) -> InstanceState:
        """启动一个 Agent 实例（CREATED/STOPPED → RUNNING）。"""
        instance = self._get_instance(agent_id)
        instance.started_at = datetime.now(timezone.utc)
        state = instance.lifecycle.transition(LifecycleEvent.START)
        logger.info("Agent started", agent_id=agent_id, state=state.value)
        return state

    async def pause_agent(self, agent_id: str) -> InstanceState:
        """暂停一个 Agent 实例（RUNNING → PAUSED）。"""
        instance = self._get_instance(agent_id)
        state = instance.lifecycle.transition(LifecycleEvent.PAUSE)
        logger.info("Agent paused", agent_id=agent_id)
        return state

    async def resume_agent(self, agent_id: str) -> InstanceState:
        """恢复一个已暂停的 Agent 实例（PAUSED → RUNNING）。"""
        instance = self._get_instance(agent_id)
        state = instance.lifecycle.transition(LifecycleEvent.RESUME)
        logger.info("Agent resumed", agent_id=agent_id)
        return state

    async def stop_agent(self, agent_id: str) -> InstanceState:
        """停止一个 Agent 实例（转换到 STOPPED）。"""
        instance = self._get_instance(agent_id)
        state = instance.lifecycle.transition(LifecycleEvent.STOP)
        logger.info("Agent stopped", agent_id=agent_id)
        return state

    async def delete_agent(self, agent_id: str) -> None:
        """永久删除一个 Agent 实例。"""
        instance = self._get_instance(agent_id)
        await instance.shutdown()
        instance.lifecycle.transition(LifecycleEvent.DELETE)
        del self._instances[agent_id]
        logger.info("Agent deleted", agent_id=agent_id)

    def get_agent(self, agent_id: str) -> AgentInstance:
        """按 ID 获取一个 Agent 实例。"""
        return self._get_instance(agent_id)

    def list_agents(self) -> list[AgentInstance]:
        """列出所有 Agent 实例。"""
        return list(self._instances.values())

    async def update_config(self, agent_id: str, config: AgentConfig) -> None:
        """
        更新 Agent 的配置（热重载）。

        新配置对新会话生效。现有会话将继续使用旧配置直到完成。
        """
        instance = self._get_instance(agent_id)
        old_config = instance.config
        instance.config = config

        # Re-initialize runtime with new config for new sessions
        await instance.runtime.initialize(config)
        await wire_agent_runtime(instance.runtime, config)

        logger.info(
            "Agent config updated",
            agent_id=agent_id,
            old_version=old_config.version,
            new_version=config.version,
        )

    async def switch_runtime(self, agent_id: str, runtime_type: str) -> None:
        """
        将 Agent 切换到不同的运行时类型。

        旧运行时进入 DRAINING 状态，继续服务现有会话，
        新运行时处理新会话。
        """
        instance = self._get_instance(agent_id)

        # Create new runtime
        new_runtime = create_runtime(runtime_type, instance.config)
        if self._llm_gateway is not None and hasattr(new_runtime, "set_llm_gateway"):
            new_runtime.set_llm_gateway(self._llm_gateway)
        await new_runtime.initialize(instance.config)
        await wire_agent_runtime(new_runtime, instance.config)

        # Drain old runtime
        old_runtime = instance.runtime
        instance.lifecycle.transition(LifecycleEvent.DRAIN)

        # Switch to new runtime
        instance.runtime = new_runtime
        instance.lifecycle.transition(LifecycleEvent.START)

        # Shut down old runtime after draining
        await old_runtime.shutdown()

        logger.info(
            "Agent runtime switched",
            agent_id=agent_id,
            new_runtime=runtime_type,
        )

    async def sync_from_configs(self, configs: list[AgentConfig]) -> int:
        """根据 ConfigManager 的配置创建并启动 agent（幂等操作）。"""
        from src.utils.exceptions import AgentAlreadyExistsError

        synced = 0
        for config in configs:
            try:
                await self.create_agent(config)
            except AgentAlreadyExistsError:
                instance = self._instances.get(config.agent_id)
                if instance is not None:
                    await self.update_config(config.agent_id, config)
            except Exception as exc:
                logger.error(
                    "Failed to sync agent from config",
                    agent_id=config.agent_id,
                    error=str(exc),
                )
                continue

            if config.agent_id in self._instances:
                instance = self._instances[config.agent_id]
                if not instance.lifecycle.is_active():
                    await self.start_agent(config.agent_id)
                synced += 1

        logger.info("Agents synced from configs", count=synced)
        return synced

    async def ensure_agent_ready(self, agent_id: str) -> AgentInstance:
        """
        确保 Agent 实例存在且处于 RUNNING 状态。

        若启动时未同步成功，在首次发消息时从 ConfigManager 懒加载并启动。
        """
        instance = self._instances.get(agent_id)
        if instance is not None:
            if not instance.lifecycle.is_active():
                await self.start_agent(agent_id)
            return instance

        if self._llm_gateway is None:
            from src.llm.gateway import get_llm_gateway

            self.set_llm_gateway(get_llm_gateway())

        from src.config_manager.manager import get_config_manager

        config = await get_config_manager().get_config(agent_id)
        await self.create_agent(config)
        await self.start_agent(agent_id)
        logger.info("Agent lazy-provisioned on demand", agent_id=agent_id)
        return self._instances[agent_id]

    async def get_agent_health(self, agent_id: str) -> HealthStatus:
        """检查指定 Agent 的健康状态。"""
        instance = self._get_instance(agent_id)
        return await instance.health_check()

    async def shutdown_all(self) -> None:
        """关闭所有 Agent 实例（优雅关闭）。"""
        for agent_id, instance in list(self._instances.items()):
            try:
                await instance.shutdown()
                logger.info("Agent shut down during cleanup", agent_id=agent_id)
            except Exception as exc:
                logger.error("Error shutting down agent", agent_id=agent_id, error=str(exc))
        self._instances.clear()

    def _get_instance(self, agent_id: str) -> AgentInstance:
        """获取实例，若不存在则抛出 AgentNotFoundError。"""
        instance = self._instances.get(agent_id)
        if instance is None:
            raise AgentNotFoundError(agent_id)
        return instance


# Singleton instance
_agent_manager: AgentManager | None = None


def get_agent_manager() -> AgentManager:
    """返回单例 AgentManager 实例。"""
    global _agent_manager
    if _agent_manager is None:
        _agent_manager = AgentManager()
    return _agent_manager
