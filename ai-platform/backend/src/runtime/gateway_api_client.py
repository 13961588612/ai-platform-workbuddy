"""LLM Gateway 适配器，实现了 OpenHarness 的 SupportsStreamingMessages 接口。"""

from __future__ import annotations
from typing import Any

import json
from collections.abc import AsyncIterator

from openharness.api.client import (
    ApiMessageCompleteEvent,
    ApiMessageRequest,
    ApiStreamEvent,
    ApiTextDeltaEvent,
)
from openharness.api.openai_client import _convert_messages_to_openai, _convert_tools_to_openai
from openharness.api.usage import UsageSnapshot
from openharness.engine.messages import ConversationMessage, TextBlock, ToolUseBlock

from src.llm.gateway import LLMGateway
from src.llm.models import LLMMessage, LLMRequest, LLMRole, TokenUsage


def _openai_messages_to_llm(openai_messages: list[dict[str, Any]]) -> list[LLMMessage]:
    """将 OpenAI 格式的聊天消息转换为平台的 LLMMessage 列表。"""
    llm_messages: list[LLMMessage] = []
    for msg in openai_messages:
        role: Skill | None = msg.get("role", "user")
        if role == "system":
            llm_messages.append(LLMMessage(role=LLMRole.SYSTEM, content=msg.get("content", "") or ""))
            continue
        if role == "tool":
            llm_messages.append(
                LLMMessage(
                    role=LLMRole.TOOL,
                    content=msg.get("content", "") or "",
                    tool_call_id=msg.get("tool_call_id", ""),
                )
            )
            continue
        if role == "assistant":
            tool_calls: Any = msg.get("tool_calls") or []
            api_tool_calls: list[dict[str, Any]] = [
                {
                    "id": tc.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", "{}"),
                    },
                }
                for tc in tool_calls
            ]
            llm_messages.append(
                LLMMessage(
                    role=LLMRole.ASSISTANT,
                    content=msg.get("content") or "",
                    tool_calls=api_tool_calls,
                )
            )
            continue
        llm_messages.append(LLMMessage(role=LLMRole.USER, content=msg.get("content", "") or ""))
    return llm_messages


class GatewayApiClient:
    """将 OpenHarness QueryEngine 的 LLM 调用路由通过平台的 LLMGateway 发送。"""

    def __init__(
        self,
        gateway: LLMGateway,
        *,
        model: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        session_id: str = "",
        user_id: str = "",
        dept: str = "",
    ) -> None:
        """保存 LLM 网关与推理参数，供 OpenHarness API 请求路由使用。

        Args:
            gateway: 平台 ``LLMGateway`` 实例。
            model: 默认模型名。
            temperature: 采样温度。
            max_tokens: 单次补全 token 上限。
            session_id: 会话 ID，写入 ``LLMRequest`` 供计费/追踪。
            user_id: 用户 ID。
            dept: 部门标识。
        """
        self._gateway = gateway
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._session_id = session_id
        self._user_id = user_id
        self._dept = dept

    async def stream_message(self, request: ApiMessageRequest) -> AsyncIterator[ApiStreamEvent]:
        """将 OpenHarness ``ApiMessageRequest`` 转为平台 LLM 调用并流式返回 API 事件。

        有 tools 时走非流式 ``chat`` 再模拟文本增量；无 tools 时走
        ``chat_stream`` 逐块下发 ``ApiTextDeltaEvent``，末包为
        ``ApiMessageCompleteEvent``（含 usage 与 stop_reason）。

        Args:
            request: OpenHarness 消息请求（消息、系统提示、tools 等）。

        Yields:
            ``ApiTextDeltaEvent`` 与最终的 ``ApiMessageCompleteEvent``。
        """
        openai_messages: Any = _convert_messages_to_openai(request.messages, request.system_prompt)
        llm_messages: list[LLMMessage] = _openai_messages_to_llm(openai_messages)
        openai_tools: Any = _convert_tools_to_openai(request.tools) if request.tools else []
        has_tools: bool = bool(openai_tools)

        llm_request: LLMRequest = LLMRequest(
            messages=llm_messages,
            model=self._model,
            temperature=self._temperature,
            max_tokens=min(request.max_tokens, self._max_tokens),
            stream=not has_tools,
            tools=openai_tools,
            tool_choice="auto" if has_tools else "none",
            session_id=self._session_id,
            user_id=self._user_id,
            dept=self._dept,
        )

        if has_tools:
            response: LLMResponse = await self._gateway.chat(llm_request)
            if response.content:
                chunk_size: int = 40
                for i in range(0, len(response.content), chunk_size):
                    yield ApiTextDeltaEvent(text=response.content[i : i + chunk_size])

            content_blocks: list[Any] = []
            if response.content:
                content_blocks.append(TextBlock(text=response.content))
            for tc in response.tool_calls:
                function: Skill | None = tc.get("function", {})
                raw_args: Skill | None = function.get("arguments", "{}")
                try:
                    parsed_args: Any = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                except (json.JSONDecodeError, TypeError):
                    parsed_args: dict[str, Any] = {}
                content_blocks.append(
                    ToolUseBlock(
                        id=tc.get("id", ""),
                        name=function.get("name", ""),
                        input=parsed_args if isinstance(parsed_args, dict) else {},
                    )
                )

            yield ApiMessageCompleteEvent(
                message=ConversationMessage(role="assistant", content=content_blocks),
                usage=UsageSnapshot(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                ),
                stop_reason="tool_calls" if response.tool_calls else response.finish_reason,
            )
            return

        total_usage: TokenUsage = TokenUsage()
        collected: str = ""
        finish_reason: str = "stop"
        async for chunk in self._gateway.chat_stream(llm_request):
            if chunk.content:
                collected += chunk.content
                yield ApiTextDeltaEvent(text=chunk.content)
            if chunk.usage is not None:
                total_usage: Any = chunk.usage
            if chunk.finish_reason:
                finish_reason: Any = chunk.finish_reason

        content_blocks: list[TextBlock] | list[Any] = [TextBlock(text=collected)] if collected else []
        yield ApiMessageCompleteEvent(
            message=ConversationMessage(role="assistant", content=content_blocks),
            usage=UsageSnapshot(
                input_tokens=total_usage.prompt_tokens,
                output_tokens=total_usage.completion_tokens,
            ),
            stop_reason=finish_reason,
        )
