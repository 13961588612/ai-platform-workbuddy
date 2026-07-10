"""Runtime 工厂 — 创建并注册运行时实例。

为每种运行时类型提供工厂函数，并在应用启动时将其注册到
RuntimeRegistry 中。
"""

from __future__ import annotations
from typing import Any


from src.runtime.base import AgentRuntime
from src.runtime.openharness import OpenHarnessRuntime
from src.runtime.registry import RuntimeCapabilities, RuntimeRegistry, get_runtime_registry
from src.utils.logging import get_logger

logger = get_logger("runtime.factory")


class OpenHarnessFactory:
    """用于创建 OpenHarnessRuntime 实例的工厂。"""

    def create(self, config: Any) -> AgentRuntime:
        """创建并返回一个新的 OpenHarnessRuntime 实例。"""
        runtime: OpenHarnessRuntime = OpenHarnessRuntime()
        return runtime

    def validate_config(self, config: Any) -> bool:
        """
        验证配置是否与 OpenHarness 兼容。

        检查 OpenHarness 特定的配置要求：
        - 若 config 为 None，则视为有效（将使用默认值）。
        - 若 config 包含 runtime 部分，则验证 maxSteps、temperature 和
          maxTokens 参数。
        - 若 config 包含运行时类型，则必须为 'openharness' 或 None。
        """
        if config is None:
            return True

        # If config has no runtime attribute, accept it
        if not hasattr(config, "runtime") or config.runtime is None:
            return True

        runtime: Any = config.runtime
        runtime_type: Any = getattr(runtime, "type", "openharness")

        # 若指定了类型，则运行时类型必须为 'openharness'
        if runtime_type and runtime_type != "openharness":
            logger.warning(
                "Runtime type mismatch for OpenHarness factory",
                expected="openharness",
                actual=runtime_type,
            )
            return False

        # Validate runtime params
        params: Any = getattr(runtime, "params", {}) or {}
        max_steps: int | None = params.get("maxSteps")
        if max_steps is not None:
            if not isinstance(max_steps, int) or max_steps < 1:
                logger.warning("Invalid maxSteps", value=max_steps)
                return False

        temperature: float | None = params.get("temperature")
        if temperature is not None:
            if not isinstance(temperature, int | float) or temperature < 0 or temperature > 2:
                logger.warning("Invalid temperature", value=temperature)
                return False

        max_tokens: int | None = params.get("maxTokens")
        if max_tokens is not None:
            if not isinstance(max_tokens, int) or max_tokens < 1:
                logger.warning("Invalid maxTokens", value=max_tokens)
                return False

        return True

    def capabilities(self) -> RuntimeCapabilities:
        """
        返回 OpenHarness 运行时的能力集。

        OpenHarness 支持：
        - 流式 LLM 响应
        - 生成式 UI 渲染
        - MCP 协议客户端，用于接入业务系统适配器
        - Multi-Agent Swarm 协调（通过 openharness.coordinator）
        - Human-in-the-loop 审批流程
        - 有状态的会话管理
        """
        return RuntimeCapabilities(
            streaming=True,
            generative_ui=True,
            mcp=True,
            multi_agent=True,
            hitl=True,
            stateful=True,
        )


def register_default_runtimes() -> RuntimeRegistry:
    """
    将所有内置运行时类型注册到 RuntimeRegistry。

    在应用启动时调用。OpenHarness 运行时会作为默认项注册。
    """
    registry: RuntimeRegistry = get_runtime_registry()

    # Register OpenHarness as default
    registry.register(
        type_name="openharness",
        factory=OpenHarnessFactory(),
        is_default=True,
    )

    logger.info("Default runtimes registered", count=len(registry.list_all()))
    return registry


def create_runtime(type_name: str | None, config: Any) -> AgentRuntime:
    """
    按类型名称创建一个运行时实例。

    Args:
        type_name: 运行时类型（None 表示使用默认类型）。
        config: 传递给工厂的 AgentConfig。

    Returns:
        一个已初始化的 AgentRuntime 实例。
    """
    registry: RuntimeRegistry = get_runtime_registry()
    return registry.create(type_name, config)
