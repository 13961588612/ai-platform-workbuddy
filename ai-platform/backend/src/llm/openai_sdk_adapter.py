"""基于 OpenAI Python SDK 的 LLM Provider 适配器基类。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, AuthenticationError
from openai import APIStatusError
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from src.llm.models import LLMChunk, LLMRequest, LLMResponse, TokenUsage
from src.utils.exceptions import LLMProviderError


def _get_proxy_url(proxy_manager: Any) -> str | None:
    if hasattr(proxy_manager, "get_proxy_url"):
        return proxy_manager.get_proxy_url()
    return None


def _extract_reasoning(message: Any) -> str:
    """从 OpenAI SDK 消息对象中提取 reasoning 字段（DeepSeek 等扩展字段）。"""
    reasoning = getattr(message, "reasoning_content", None)
    if reasoning:
        return reasoning if isinstance(reasoning, str) else str(reasoning)

    model_extra = getattr(message, "model_extra", None) or {}
    if isinstance(model_extra, dict):
        raw = model_extra.get("reasoning_content") or model_extra.get("reasoning") or ""
        return raw if isinstance(raw, str) else str(raw)
    return ""


def _serialize_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    if not tool_calls:
        return []
    result: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        function = getattr(tool_call, "function", None)
        result.append(
            {
                "id": tool_call.id,
                "type": tool_call.type or "function",
                "function": {
                    "name": function.name if function else "",
                    "arguments": function.arguments if function else "{}",
                },
            }
        )
    return result


def _build_create_kwargs(request: LLMRequest, *, stream: bool) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": request.model,
        "messages": [msg.to_api_dict() for msg in request.messages],
        "temperature": request.temperature,
        "max_tokens": request.max_tokens,
        "top_p": request.top_p,
        "stream": stream,
    }
    if request.tools:
        kwargs["tools"] = request.tools
        if request.tool_choice and request.tool_choice != "none":
            kwargs["tool_choice"] = request.tool_choice
    if stream:
        kwargs["stream_options"] = {"include_usage": True}
    kwargs.update(request.extra)
    kwargs["stream"] = stream
    return kwargs


def _parse_completion(response: ChatCompletion) -> LLMResponse:
    choice = response.choices[0]
    message = choice.message
    usage = response.usage
    raw = response.model_dump() if hasattr(response, "model_dump") else {}

    return LLMResponse(
        content=message.content or "",
        reasoning_content=_extract_reasoning(message),
        role=message.role or "assistant",
        model=response.model or "",
        usage=TokenUsage(
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
        ),
        finish_reason=choice.finish_reason or "stop",
        tool_calls=_serialize_tool_calls(message.tool_calls),
        raw=raw,
    )


def _parse_stream_chunk(chunk: ChatCompletionChunk) -> LLMChunk | None:
    if not chunk.choices:
        usage = chunk.usage
        if usage is None:
            return None
        return LLMChunk(
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
                total_tokens=usage.total_tokens or 0,
            ),
        )

    choice = chunk.choices[0]
    delta = choice.delta
    usage = chunk.usage

    llm_chunk = LLMChunk(
        content=delta.content or "",
        reasoning_content=_extract_reasoning(delta),
        role=delta.role or "",
        finish_reason=choice.finish_reason or "",
    )
    if usage is not None:
        llm_chunk.usage = TokenUsage(
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
        )
    return llm_chunk


class OpenAISDKAdapter:
    """使用 OpenAI 兼容 API 的 Provider 适配器基类。"""

    PROVIDER_NAME: str = ""

    def __init__(self, base_url: str, timeout: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def chat(
        self,
        request: LLMRequest,
        api_key: str,
        proxy_manager: Any,
    ) -> LLMResponse:
        proxy_url = _get_proxy_url(proxy_manager)
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=self._timeout) as http_client:
                client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=self._base_url,
                    http_client=http_client,
                    max_retries=0,
                )
                response = await client.chat.completions.create(
                    **_build_create_kwargs(request, stream=False),
                )
        except AuthenticationError as exc:
            raise LLMProviderError(self.PROVIDER_NAME, f"Authentication failed: {exc}") from exc
        except APIStatusError as exc:
            if exc.status_code in {401, 403}:
                raise LLMProviderError(
                    self.PROVIDER_NAME,
                    f"Authentication failed ({exc.status_code})",
                ) from exc
            raise LLMProviderError(
                self.PROVIDER_NAME,
                f"API returned {exc.status_code}: {exc.message}",
            ) from exc
        except APITimeoutError as exc:
            raise LLMProviderError(self.PROVIDER_NAME, "Request timed out") from exc
        except APIConnectionError as exc:
            raise LLMProviderError(
                self.PROVIDER_NAME,
                "Connection failed (proxy may be down)",
            ) from exc
        except Exception as exc:
            if _is_auth_error(exc):
                raise LLMProviderError(
                    self.PROVIDER_NAME,
                    f"Authentication failed: {exc}",
                ) from exc
            raise LLMProviderError(self.PROVIDER_NAME, str(exc)) from exc

        return _parse_completion(response)

    async def chat_stream(
        self,
        request: LLMRequest,
        api_key: str,
        proxy_manager: Any,
    ) -> AsyncIterator[LLMChunk]:
        proxy_url = _get_proxy_url(proxy_manager)
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=self._timeout) as http_client:
                client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=self._base_url,
                    http_client=http_client,
                    max_retries=0,
                )
                stream = await client.chat.completions.create(
                    **_build_create_kwargs(request, stream=True),
                )
                async for chunk in stream:
                    parsed = _parse_stream_chunk(chunk)
                    if parsed is not None:
                        yield parsed
        except AuthenticationError as exc:
            raise LLMProviderError(self.PROVIDER_NAME, f"Authentication failed: {exc}") from exc
        except APIStatusError as exc:
            if exc.status_code in {401, 403}:
                raise LLMProviderError(
                    self.PROVIDER_NAME,
                    f"Authentication failed ({exc.status_code})",
                ) from exc
            raise LLMProviderError(
                self.PROVIDER_NAME,
                f"API returned {exc.status_code}: {exc.message}",
            ) from exc
        except APITimeoutError as exc:
            raise LLMProviderError(self.PROVIDER_NAME, "Streaming request timed out") from exc
        except APIConnectionError as exc:
            raise LLMProviderError(
                self.PROVIDER_NAME,
                "Connection failed during streaming",
            ) from exc
        except Exception as exc:
            if _is_auth_error(exc):
                raise LLMProviderError(
                    self.PROVIDER_NAME,
                    f"Authentication failed: {exc}",
                ) from exc
            raise LLMProviderError(self.PROVIDER_NAME, str(exc)) from exc


def _is_auth_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    return status_code in {401, 403}
