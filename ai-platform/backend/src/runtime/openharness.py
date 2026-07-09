"""OpenHarness 运行时 — 原生 QueryEngine 集成。

使用 OpenHarness 的 ``QueryEngine`` 驱动 agent 循环，``skill`` 工具搭配
``extra_skill_dirs`` 实现渐进式 skill 发现，``McpClientManager`` 用于
MCP 工具注册。LLM 调用通过 ``GatewayApiClient`` 路由到平台的 ``LLMGateway``。
"""

from __future__ import annotations
from typing import Any

import json
from collections.abc import AsyncIterator
from pathlib import Path

from src.agent.config import AgentConfig
from src.config import get_settings
from src.llm.gateway import LLMGateway
from src.runtime.base import AgentRuntime
from src.runtime.events import AgentEvent, HealthStatus, TokenUsage
from src.runtime.oh_runtime_builder import (
    build_native_query_engine,
    connect_mcp_manager,
    resolve_extra_skill_dirs,
)
from src.utils.logging import get_logger

try:
    from openharness.engine.messages import ConversationMessage, TextBlock
    from openharness.engine.stream_events import (
        AssistantTextDelta,
        AssistantTurnComplete,
        ErrorEvent,
        ToolExecutionCompleted,
        ToolExecutionStarted,
    )
    from openharness.mcp.client import McpClientManager

    _OPENHARNESS_AVAILABLE = True
except ImportError:  # pragma: no cover
    _OPENHARNESS_AVAILABLE = False
    McpClientManager = None  # type: ignore[misc, assignment]

logger = get_logger("runtime.openharness")

_TRACE_LOG_LIMIT = 1000


def _agent_trace_enabled() -> bool:
    """判断当前是否开启 Agent 执行轨迹日志。

    Returns:
        ``True`` 表示应输出 ``Agent trace`` 结构化日志。
    """
    return get_settings().AGENT_TRACE_LOG


def _clip_log_text(text: str, limit: int = _TRACE_LOG_LIMIT) -> str:
    """截断过长文本，避免轨迹日志撑爆单行。

    Args:
        text: 原始文本。
        limit: 最大保留字符数；超出时末尾追加 ``…``。

    Returns:
        去首尾空白并截断后的字符串。
    """
    cleaned: str = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "…"


def _log_agent_trace(session_id: str, step: int, phase: str, **fields: Any) -> None:
    """在开启轨迹日志时写入一条 Agent 执行阶段记录。

    字符串与 JSON 序列化结果会经 ``_clip_log_text`` 截断后写入
    ``logger.info`` 的 ``Agent trace`` 事件。

    Args:
        session_id: 会话 ID。
        step: 当前执行步序号。
        phase: 阶段标识（如 ``run_start``、``tool_call``）。
        **fields: 附加字段；``None`` 值会被忽略。
    """
    if not _agent_trace_enabled():
        return
    payload: dict[str, Any] = {"session_id": session_id, "step": step, "phase": phase}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, str):
            payload[key] = _clip_log_text(value)
        elif isinstance(value, (dict, list)):
            try:
                serialized: str = json.dumps(value, ensure_ascii=False, default=str)
                payload[key] = _clip_log_text(serialized, limit=1500)
            except (TypeError, ValueError):
                payload[key] = str(value)
        else:
            payload[key] = value
    logger.info("Agent trace", **payload)


def _platform_messages_to_conversation(messages: list[dict[str, Any]]) -> list[Any]:
    """将平台会话消息转换为 OpenHarness 的 ConversationMessage 列表。"""
    if not _OPENHARNESS_AVAILABLE:
        return []
    result: list[ConversationMessage] = []
    for msg in messages:
        role: Skill | None = msg.get("role", "user")
        content: Skill | None = msg.get("content", "")
        if role == "assistant":
            result.append(
                ConversationMessage(role="assistant", content=[TextBlock(text=str(content or ""))])
            )
        else:
            result.append(ConversationMessage.from_user_text(str(content or "")))
    return result


class OpenHarnessRuntime(AgentRuntime):
    """基于原生 OpenHarness QueryEngine 的 Agent 运行时。"""

    def __init__(self) -> None:
        """初始化 OpenHarness 运行时默认状态。

        设置运行时类型/版本、会话状态缓存、LLM 网关占位及
        默认推理参数（步数、温度、token 上限、模型名）。
        """
        self._runtime_type = "openharness"
        self._version = "1.0.0"
        self._config: AgentConfig | None = None
        self._mcp_servers: list[dict[str, Any]] = []
        self._session_states: dict[str, dict[str, Any]] = {}
        self._llm_gateway: LLMGateway | None = None
        self._max_steps = 20
        self._temperature = 0.7
        self._max_tokens = 4096
        self._system_prompt = ""
        self._model = "deepseek-v4-flash"
        self._native_mcp_manager: McpClientManager | None = None
        self._initialized = False

    @property
    def runtime_type(self) -> str:
        """返回运行时类型标识。"""
        return self._runtime_type

    @property
    def version(self) -> str:
        """返回运行时版本号。"""
        return self._version

    async def initialize(self, config: Any) -> None:
        """从 Agent 配置加载推理参数、系统提示词与模型名。

        Args:
            config: ``AgentConfig`` 或兼容对象；从中读取 ``runtime.params``、
                ``system_prompt``、``model.primary`` 等字段。

        Raises:
            RuntimeError: 未安装 ``openharness`` 包时抛出。
        """
        if not _OPENHARNESS_AVAILABLE:
            raise RuntimeError(
                "OpenHarness package is not installed. "
                "Install it with: pip install openharness-ai (or uv add openharness-ai)"
            )

        self._config = config

        if hasattr(config, "runtime") and config.runtime:
            params: Any = getattr(config.runtime, "params", {}) or {}
            self._max_steps = params.get("maxSteps", 20)
            self._temperature = params.get("temperature", 0.7)
            self._max_tokens = params.get("maxTokens", 4096)

        if hasattr(config, "system_prompt") and config.system_prompt:
            self._system_prompt = config.system_prompt
        elif hasattr(config, "runtime") and config.runtime:
            prompts: Any = getattr(config.runtime, "prompts", {}) or {}
            self._system_prompt = prompts.get("system_prompt", "")

        if hasattr(config, "model") and config.model:
            self._model = getattr(config.model, "primary", self._model)

        self._initialized = True
        logger.info(
            "OpenHarness runtime initialized",
            max_steps=self._max_steps,
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            model=self._model,
        )

    async def run(
        self,
        messages: list[dict[str, Any]],
        config: Any,
        session_id: str,
    ) -> AsyncIterator[AgentEvent]:
        """驱动原生 QueryEngine 执行一轮对话并映射为平台 AgentEvent。

        连接 MCP、构建 QueryEngine，将 OpenHarness 流式事件（文本增量、
        工具调用/结果、轮次完成、错误）转为 ``AgentEvent`` 下发；
        未配置 ``LLMGateway`` 时直接返回错误事件。

        Args:
            messages: 平台格式的会话消息列表。
            config: Agent 配置；若尚未初始化会触发 ``initialize``。
            session_id: 会话 ID，用于 MCP 连接与轨迹日志。

        Yields:
            文本增量、工具事件、错误及最终的 ``done`` 事件。
        """
        if not self._initialized:
            await self.initialize(config)

        if self._llm_gateway is None:
            yield AgentEvent.error(
                "RUNTIME_ERROR",
                "LLM Gateway is not configured. Call set_llm_gateway() before run().",
            )
            yield AgentEvent.done()
            return

        agent_config: AgentConfig = (
            config if isinstance(config, AgentConfig) else self._config  # type: ignore[assignment]
        )
        oh_messages: list[Any] = _platform_messages_to_conversation(messages)
        last_user_msg: Any = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )

        skill_dirs: list[str] = resolve_extra_skill_dirs(agent_config, Path(get_settings().CONFIG_BASE_PATH))
        _log_agent_trace(
            session_id,
            step=0,
            phase="run_start",
            user_message=last_user_msg,
            model=self._model,
            skill_dirs=skill_dirs,
            runtime="native_openharness",
        )

        total_usage: TokenUsage = TokenUsage()
        step: int = 0

        try:
            if self._native_mcp_manager is None:
                self._native_mcp_manager = await connect_mcp_manager(agent_config)

            engine: QueryEngine = await build_native_query_engine(
                agent_config,
                self._llm_gateway,
                self._native_mcp_manager,
                session_id=session_id,
            )

            if len(oh_messages) > 1:
                engine.load_messages(oh_messages[:-1])
                prompt: Any = oh_messages[-1]
            elif oh_messages:
                prompt: Any = oh_messages[-1]
            else:
                prompt: Any = ConversationMessage.from_user_text("")

            async for event in engine.submit_message(prompt):
                step += 1
                if isinstance(event, AssistantTextDelta):
                    yield AgentEvent.text_delta(event.text)
                    _log_agent_trace(
                        session_id, step=step, phase="text_delta", assistant_text=event.text
                    )
                elif isinstance(event, ToolExecutionStarted):
                    yield AgentEvent.tool_call(event.tool_name, event.tool_input)
                    _log_agent_trace(
                        session_id,
                        step=step,
                        phase="tool_call",
                        tool=event.tool_name,
                        args=event.tool_input,
                    )
                elif isinstance(event, ToolExecutionCompleted):
                    result: dict[str, Any] = {"output": event.output}
                    if event.is_error:
                        result["error"] = event.output
                    yield AgentEvent.tool_result(event.tool_name, result)
                    _log_agent_trace(
                        session_id,
                        step=step,
                        phase="tool_result",
                        tool=event.tool_name,
                        result=result,
                        error=result.get("error"),
                    )
                elif isinstance(event, AssistantTurnComplete):
                    usage: Any = event.usage
                    total_usage: TokenUsage = TokenUsage(
                        prompt=usage.input_tokens,
                        completion=usage.output_tokens,
                        total=usage.input_tokens + usage.output_tokens,
                    )
                    _log_agent_trace(
                        session_id,
                        step=step,
                        phase="llm_response",
                        assistant_text=event.message.text,
                        finish_reason="tool_calls" if event.message.tool_uses else "stop",
                        tokens=total_usage.total,
                    )
                elif isinstance(event, ErrorEvent):
                    yield AgentEvent.error("RUNTIME_ERROR", event.message)

            yield AgentEvent.done(total_usage)
            _log_agent_trace(
                session_id,
                step=step,
                phase="run_complete",
                total_steps=step,
                total_tokens=total_usage.total,
            )
            logger.info(
                "Agent run completed",
                session_id=session_id,
                steps=step,
                total_tokens=total_usage.total,
                runtime="native_openharness",
            )

        except Exception as exc:
            logger.error(
                "Agent run failed",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            yield AgentEvent.error("RUNTIME_ERROR", str(exc))
            yield AgentEvent.done()

    async def register_tools(self, skills: list[dict[str, Any]]) -> None:
        """空操作 — 原生 OpenHarness 通过 ``extra_skill_dirs`` 发现 skills。"""
        logger.debug("register_tools skipped (native OpenHarness)", skill_count=len(skills))

    async def register_mcp(self, server_config: dict[str, Any]) -> None:
        """记录 MCP 服务器配置，供健康检查与后续连接使用。

        Args:
            server_config: MCP 服务器描述（含 ``name`` 等字段）。
        """
        self._mcp_servers.append(server_config)
        logger.debug(
            "MCP server config recorded",
            name=server_config.get("name", "unknown"),
        )

    async def get_state(self, session_id: str) -> dict[str, Any]:
        """读取指定会话的运行时状态快照。

        Args:
            session_id: 会话 ID。

        Returns:
            已保存的状态字典；无记录时返回空 dict。
        """
        return self._session_states.get(session_id, {})

    async def set_state(self, session_id: str, state: dict[str, Any]) -> None:
        """写入指定会话的运行时状态。

        Args:
            session_id: 会话 ID。
            state: 要持久化到内存的状态字典。
        """
        self._session_states[session_id] = state

    async def health_check(self) -> HealthStatus:
        """检查运行时是否已初始化且 OpenHarness 依赖可用。

        Returns:
            含初始化状态、MCP 连接、活跃会话数等细节的 ``HealthStatus``。
        """
        return HealthStatus(
            healthy=self._initialized and _OPENHARNESS_AVAILABLE,
            details={
                "runtime_type": self._runtime_type,
                "version": self._version,
                "runtime_mode": "native_openharness",
                "openharness_available": _OPENHARNESS_AVAILABLE,
                "initialized": self._initialized,
                "native_mcp_connected": self._native_mcp_manager is not None,
                "mcp_servers": len(self._mcp_servers),
                "active_sessions": len(self._session_states),
                "llm_gateway_configured": self._llm_gateway is not None,
            },
        )

    async def shutdown(self) -> None:
        """清理会话状态、关闭原生 MCP 管理器并重置初始化标志。"""
        self._session_states.clear()
        if self._native_mcp_manager is not None:
            await self._native_mcp_manager.close()
            self._native_mcp_manager = None
        self._initialized = False
        logger.info("OpenHarness runtime shut down")

    def set_llm_gateway(self, gateway: LLMGateway) -> None:
        """注入平台 LLM 网关，供 QueryEngine 经 ``GatewayApiClient`` 调用。

        Args:
            gateway: 已配置的 ``LLMGateway`` 实例。
        """
        self._llm_gateway = gateway

    def set_native_mcp_manager(self, manager: McpClientManager) -> None:
        """注入已连接的原生 MCP 客户端管理器（测试或预热场景）。

        Args:
            manager: OpenHarness ``McpClientManager`` 实例。
        """
        self._native_mcp_manager = manager
