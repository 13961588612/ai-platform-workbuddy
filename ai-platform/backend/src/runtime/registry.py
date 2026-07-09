"""RuntimeRegistry — 运行时类型注册与工厂管理。

维护一个按运行时类型索引的 RuntimeFactory 实例注册表。
在启动时，内置的 OpenHarness 运行时会作为默认项被注册。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

from src.runtime.base import AgentRuntime
from src.utils.exceptions import AIPlatformError
from src.utils.logging import get_logger

logger = get_logger("runtime.registry")


class RuntimeCapabilities:
    """声明运行时实现的能力。"""

    def __init__(
        self,
        streaming: bool = True,
        generative_ui: bool = True,
        mcp: bool = True,
        multi_agent: bool = False,
        hitl: bool = True,
        stateful: bool = True,
    ) -> None:
        """声明运行时支持的能力开关。

        Args:
            streaming: 是否支持流式输出。
            generative_ui: 是否支持生成式 UI。
            mcp: 是否支持 MCP 工具。
            multi_agent: 是否支持多 Agent 协作。
            hitl: 是否支持人机协同（HITL）。
            stateful: 是否支持有状态会话。
        """
        self.streaming = streaming
        self.generative_ui = generative_ui
        self.mcp = mcp
        self.multi_agent = multi_agent
        self.hitl = hitl
        self.stateful = stateful

    def to_dict(self) -> dict[str, bool]:
        """以字典形式返回能力集。"""
        return {
            "streaming": self.streaming,
            "generative_ui": self.generative_ui,
            "mcp": self.mcp,
            "multi_agent": self.multi_agent,
            "hitl": self.hitl,
            "stateful": self.stateful,
        }


class RuntimeInfo:
    """已注册运行时的元数据。"""

    def __init__(
        self,
        type_name: str,
        version: str,
        capabilities: RuntimeCapabilities,
        is_default: bool = False,
    ) -> None:
        """构造已注册运行时的元数据记录。

        Args:
            type_name: 运行时类型标识。
            version: 运行时版本号。
            capabilities: 能力声明对象。
            is_default: 是否为默认运行时类型。
        """
        self.type = type_name
        self.version = version
        self.capabilities = capabilities
        self.is_default = is_default
        self.registered_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """以字典形式返回运行时信息。"""
        return {
            "type": self.type,
            "version": self.version,
            "capabilities": self.capabilities.to_dict(),
            "is_default": self.is_default,
            "registered_at": self.registered_at.isoformat(),
        }


class RuntimeFactory(Protocol):
    """运行时工厂函数的协议。"""

    def create(self, config: Any) -> AgentRuntime:
        """根据配置创建并返回 ``AgentRuntime`` 实例。"""
        ...

    def validate_config(self, config: Any) -> bool:
        """校验配置是否适用于本运行时类型。"""
        ...

    def capabilities(self) -> RuntimeCapabilities:
        """返回本运行时声明的能力集。"""
        ...


class RuntimeRegistry:
    """
    Agent 运行时工厂的注册表。

    支持在启动时或通过管理 API 动态注册自定义运行时类型。
    默认运行时为 'openharness'。
    """

    def __init__(self) -> None:
        """初始化空的运行时工厂注册表，默认类型为 ``openharness``。"""
        self._factories: dict[str, RuntimeFactory] = {}
        self._infos: dict[str, RuntimeInfo] = {}
        self._default_type: str = "openharness"

    def register(
        self,
        type_name: str,
        factory: RuntimeFactory,
        capabilities: RuntimeCapabilities | None = None,
        is_default: bool = False,
    ) -> None:
        """注册一个运行时工厂。"""
        caps = capabilities or factory.capabilities()
        version = "1.0.0"

        # 尝试从工厂创建的实例中获取版本
        try:
            temp = factory.create(config=None)  # type: ignore[arg-type]
            version = temp.version
        except Exception:
            pass

        self._factories[type_name] = factory
        self._infos[type_name] = RuntimeInfo(
            type_name=type_name,
            version=version,
            capabilities=caps,
            is_default=is_default,
        )

        if is_default:
            self._default_type = type_name

        logger.info("Runtime registered", type=type_name, is_default=is_default)

    def unregister(self, type_name: str) -> None:
        """注销一个运行时类型。"""
        if type_name == self._default_type:
            raise AIPlatformError(
                f"Cannot unregister default runtime: {type_name}",
                code=2003,
            )
        self._factories.pop(type_name, None)
        self._infos.pop(type_name, None)
        logger.info("Runtime unregistered", type=type_name)

    def create(self, type_name: str | None, config: Any) -> AgentRuntime:
        """
        创建一个运行时实例。

        Args:
            type_name: 运行时类型。若为 None，则使用默认类型。
            config: 用于初始化的 AgentConfig。

        Returns:
            一个已初始化的 AgentRuntime 实例。
        """
        rt_type = type_name or self._default_type
        if rt_type not in self._factories:
            raise AIPlatformError(
                f"Runtime type not registered: {rt_type}",
                code=2004,
            )

        factory = self._factories[rt_type]
        if not factory.validate_config(config):
            raise AIPlatformError(
                f"Invalid configuration for runtime: {rt_type}",
                code=7001,
            )

        runtime = factory.create(config)
        logger.info("Runtime created", type=rt_type)
        return runtime

    def get_info(self, type_name: str) -> RuntimeInfo:
        """获取已注册运行时的元数据。"""
        if type_name not in self._infos:
            raise AIPlatformError(
                f"Runtime type not registered: {type_name}",
                code=2004,
            )
        return self._infos[type_name]

    def list_all(self) -> list[RuntimeInfo]:
        """列出所有已注册的运行时。"""
        return list(self._infos.values())

    def get_default(self) -> str:
        """返回默认运行时类型。"""
        return self._default_type

    def set_default(self, type_name: str) -> None:
        """设置默认运行时类型。"""
        if type_name not in self._factories:
            raise AIPlatformError(
                f"Runtime type not registered: {type_name}",
                code=2004,
            )
        for info in self._infos.values():
            info.is_default = (info.type == type_name)
        self._default_type = type_name
        logger.info("Default runtime set", type=type_name)


# Singleton instance
_registry: RuntimeRegistry | None = None


def get_runtime_registry() -> RuntimeRegistry:
    """返回单例 RuntimeRegistry 实例。"""
    global _registry
    if _registry is None:
        _registry = RuntimeRegistry()
    return _registry
