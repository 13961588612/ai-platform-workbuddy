"""OpenHarness 运行时 — 原生 QueryEngine 集成。

使用 OpenHarness 的 ``QueryEngine`` 驱动 agent 循环，``skill`` 工具搭配
``extra_skill_dirs`` 实现渐进式 skill 发现，``McpClientManager`` 用于
MCP 工具注册。LLM 调用通过 ``GatewayApiClient`` 路由到平台的 ``LLMGateway``。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

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
    return get_settings().AGENT_TRACE_LOG


def _clip_log_text(text: str, limit: int = _TRACE_LOG_LIMIT) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + "…"


def _log_agent_trace(session_id: str, step: int, phase: str, **fields: Any) -> None:
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
                serialized = json.dumps(value, ensure_ascii=False, default=str)
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
        role = msg.get("role", "user")
        content = msg.get("content", "")
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
        return self._runtime_type

    @property
    def version(self) -> str:
        return self._version

    async def initialize(self, config: Any) -> None:
        if not _OPENHARNESS_AVAILABLE:
            raise RuntimeError(
                "OpenHarness package is not installed. "
                "Install it with: pip install openharness-ai (or uv add openharness-ai)"
            )

        self._config = config

        if hasattr(config, "runtime") and config.runtime:
            params = getattr(config.runtime, "params", {}) or {}
            self._max_steps = params.get("maxSteps", 20)
            self._temperature = params.get("temperature", 0.7)
            self._max_tokens = params.get("maxTokens", 4096)

        if hasattr(config, "system_prompt") and config.system_prompt:
            self._system_prompt = config.system_prompt
        elif hasattr(config, "runtime") and config.runtime:
            prompts = getattr(config.runtime, "prompts", {}) or {}
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
        oh_messages = _platform_messages_to_conversation(messages)
        last_user_msg = next(
            (m.get("content", "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )

        skill_dirs = resolve_extra_skill_dirs(agent_config, Path(get_settings().CONFIG_BASE_PATH))
        _log_agent_trace(
            session_id,
            step=0,
            phase="run_start",
            user_message=last_user_msg,
            model=self._model,
            skill_dirs=skill_dirs,
            runtime="native_openharness",
        )

        total_usage = TokenUsage()
        step = 0

        try:
            if self._native_mcp_manager is None:
                self._native_mcp_manager = await connect_mcp_manager(agent_config)

            engine = await build_native_query_engine(
                agent_config,
                self._llm_gateway,
                self._native_mcp_manager,
                session_id=session_id,
            )

            if len(oh_messages) > 1:
                engine.load_messages(oh_messages[:-1])
                prompt = oh_messages[-1]
            elif oh_messages:
                prompt = oh_messages[-1]
            else:
                prompt = ConversationMessage.from_user_text("")

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
                    usage = event.usage
                    total_usage = TokenUsage(
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
        self._mcp_servers.append(server_config)
        logger.debug(
            "MCP server config recorded",
            name=server_config.get("name", "unknown"),
        )

    async def get_state(self, session_id: str) -> dict[str, Any]:
        return self._session_states.get(session_id, {})

    async def set_state(self, session_id: str, state: dict[str, Any]) -> None:
        self._session_states[session_id] = state

    async def health_check(self) -> HealthStatus:
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
        self._session_states.clear()
        if self._native_mcp_manager is not None:
            await self._native_mcp_manager.close()
            self._native_mcp_manager = None
        self._initialized = False
        logger.info("OpenHarness runtime shut down")

    def set_llm_gateway(self, gateway: LLMGateway) -> None:
        self._llm_gateway = gateway

    def set_native_mcp_manager(self, manager: McpClientManager) -> None:
        self._native_mcp_manager = manager
