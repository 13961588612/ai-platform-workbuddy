"""AgentRuntime 抽象基类 — 定义运行时接口契约。

所有运行时实现（OpenHarness、自定义、LangGraph）必须继承此基类
并实现其中的抽象方法。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from src.runtime.events import AgentEvent, HealthStatus


class AgentRuntime(ABC):
    """
    Agent 运行时的抽象基类。

    运行时负责执行 Agent 的逻辑：处理消息、调用 LLM、调用工具/技能，
    并生成 AgentEvent 对象流。

    实现必须兼容异步，并对并发会话处理保证线程安全。
    """

    @property
    @abstractmethod
    def runtime_type(self) -> str:
        """返回运行时类型标识符（例如 'openharness'）。"""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """返回运行时版本字符串。"""
        ...

    @abstractmethod
    async def initialize(self, config: Any) -> None:
        """
        使用 AgentConfig 初始化运行时。

        在创建 Agent 实例时调用一次。设置工具、MCP 服务器、
        系统提示词及其他运行时资源。
        """
        ...

    @abstractmethod
    async def run(
        self,
        messages: list[dict[str, Any]],
        config: Any,
        session_id: str,
    ) -> AsyncIterator[AgentEvent]:
        """
        执行 Agent 并产出 AgentEvent 对象。

        Args:
            messages: 包含 'role' 和 'content' 的消息字典列表。
            config: AgentConfig 实例。
            session_id: 当前会话标识符。

        Yields:
            按顺序产出 AgentEvent 对象（text.delta、tool.call 等）。
        """
        ...

    @abstractmethod
    async def register_tools(self, skills: list[dict[str, Any]]) -> None:
        """将 Skill 定义注册为可调用的工具。"""
        ...

    @abstractmethod
    async def register_mcp(self, server_config: dict[str, Any]) -> None:
        """注册 MCP Server 连接。"""
        ...

    @abstractmethod
    async def get_state(self, session_id: str) -> dict[str, Any]:
        """获取指定会话的当前状态。"""
        ...

    @abstractmethod
    async def set_state(self, session_id: str, state: dict[str, Any]) -> None:
        """设置指定会话的状态。"""
        ...

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """对运行时执行健康检查。"""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """清理资源并关闭运行时。"""
        ...
