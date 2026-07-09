"""基于 OpenAI Python SDK 的 LLM Provider 适配器基类。

DeepSeek / Qwen 等 OpenAI 兼容厂家共用本模块的请求组装、响应解析与错误映射。
子类（如 ``DeepSeekAdapter``）只需设置 ``PROVIDER_NAME`` 与 ``base_url``。
"""

from __future__ import annotations
from typing import Any

from collections.abc import AsyncIterator

import httpx
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI, AuthenticationError
from openai import APIStatusError
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from src.llm.models import LLMChunk, LLMRequest, LLMResponse, TokenUsage
from src.utils.exceptions import LLMProviderError


def _get_proxy_url(proxy_manager: Any) -> str | None:
    """从出站代理管理器解析当前可用的 HTTP(S) 代理 URL。

    Args:
        proxy_manager: 通常为 ``OutboundProxyManager``；若实现了 ``get_proxy_url``
            则调用之，否则视为直连。

    Returns:
        代理地址字符串，或 ``None``（不走代理）。
    """
    if hasattr(proxy_manager, "get_proxy_url"):
        return proxy_manager.get_proxy_url()
    return None


def _extract_reasoning(message: Any) -> str:
    """从 OpenAI SDK 消息 / delta 对象中提取 reasoning 文本。

    DeepSeek 等厂商在标准 ``content`` 之外可能返回 ``reasoning_content``
    （或放在 ``model_extra`` 里的 ``reasoning``）。流式与非流式共用本函数。

    Args:
        message: ``ChatCompletionMessage`` 或流式 ``ChoiceDelta``。

    Returns:
        reasoning 字符串；没有则返回空串。
    """
    reasoning: Any = getattr(message, "reasoning_content", None)
    if reasoning:
        return reasoning if isinstance(reasoning, str) else str(reasoning)

    model_extra: Any = getattr(message, "model_extra", None) or {}
    if isinstance(model_extra, dict):
        raw: Any = model_extra.get("reasoning_content") or model_extra.get("reasoning") or ""
        return raw if isinstance(raw, str) else str(raw)
    return ""


def _serialize_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """将 SDK 的 tool_calls 对象列表转为平台统一的 dict 结构。

    输出格式与 OpenAI function calling 一致，便于 ``LLMResponse`` /
    Agent 运行时继续解析。

    Args:
        tool_calls: SDK 返回的 tool_calls 可迭代对象；为空则返回 ``[]``。

    Returns:
        形如 ``[{"id", "type", "function": {"name", "arguments"}}]`` 的列表。
    """
    if not tool_calls:
        return []
    result: list[dict[str, Any]] = []
    for tool_call in tool_calls:
        function: Any = getattr(tool_call, "function", None)
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
    """把平台 ``LLMRequest`` 转成 ``chat.completions.create`` 的关键字参数。

    处理模型名、消息、采样参数、tools / tool_choice；流式时额外打开
    ``stream_options.include_usage`` 以便末包带回 token 用量。
    ``request.extra`` 会合并进结果，但最终强制 ``stream`` 与入参一致，
    避免被 extra 覆盖。

    Args:
        request: 平台统一的 LLM 请求。
        stream: ``True`` 走流式，``False`` 走一次性补全。

    Returns:
        可直接 ``**`` 解包传给 OpenAI SDK 的 dict。
    """
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
    """将非流式 ``ChatCompletion`` 解析为平台 ``LLMResponse``。

    取 ``choices[0]`` 的正文、reasoning、finish_reason、tool_calls，
    以及 ``usage`` 中的 token 统计；``raw`` 保留 SDK 原始 dump 便于排障。

    Args:
        response: OpenAI SDK 非流式补全结果。

    Returns:
        平台统一的 ``LLMResponse``。
    """
    choice: Any = response.choices[0]
    message: Any = choice.message
    usage: Any = response.usage
    raw: dict[str, Any] = response.model_dump() if hasattr(response, "model_dump") else {}

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
    """将单个流式 ``ChatCompletionChunk`` 解析为 ``LLMChunk``。

    - 无 ``choices`` 但带 ``usage``：视为末包用量事件，只填 ``usage``。
    - 无 ``choices`` 且无 ``usage``：返回 ``None``（调用方应跳过）。
    - 有 ``choices``：从 ``delta`` 取 content / reasoning / role / finish_reason，
      若同包带 usage 则一并挂上。

    Args:
        chunk: SDK 流式迭代中的一块。

    Returns:
        可下发的 ``LLMChunk``，或 ``None`` 表示忽略该块。
    """
    if not chunk.choices:
        usage: Any = chunk.usage
        if usage is None:
            return None
        return LLMChunk(
            usage=TokenUsage(
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
                total_tokens=usage.total_tokens or 0,
            ),
        )

    choice: Any = chunk.choices[0]
    delta: Any = choice.delta
    usage: Any = chunk.usage

    llm_chunk: LLMChunk = LLMChunk(
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
    """使用 OpenAI 兼容 API 的 Provider 适配器基类。

    子类设置 ``PROVIDER_NAME``，并在 ``__init__`` 中传入厂家 ``base_url``
    与超时。``LLMGateway`` 通过 ``chat`` / ``chat_stream`` 调用本类，
    由本类负责代理、SDK 客户端创建与错误统一映射为 ``LLMProviderError``。
    """

    PROVIDER_NAME: str = ""

    def __init__(self, base_url: str, timeout: int) -> None:
        """保存厂家 API 根地址与请求超时。

        Args:
            base_url: OpenAI 兼容端点，如 ``https://api.deepseek.com``；
                末尾 ``/`` 会被去掉。
            timeout: 单次 HTTP 请求超时秒数（传给 httpx）。
        """
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def chat(
        self,
        request: LLMRequest,
        api_key: str,
        proxy_manager: Any,
    ) -> LLMResponse:
        """非流式调用厂家 chat completions，返回完整 ``LLMResponse``。

        流程：解析代理 → 建 httpx + AsyncOpenAI 客户端 → ``create(stream=False)``
        → ``_parse_completion``。认证 / 超时 / 连接失败等统一转为
        ``LLMProviderError``，供上层 Failover 判断是否切换厂家。

        Args:
            request: 平台 LLM 请求（模型、消息、tools 等）。
            api_key: 当前选用的厂家 API Key。
            proxy_manager: 出站代理管理器；无代理时直连。

        Returns:
            解析后的完整补全结果。

        Raises:
            LLMProviderError: 鉴权失败、HTTP 错误、超时、连接失败或其他异常。
        """
        proxy_url: str | None = _get_proxy_url(proxy_manager)
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=self._timeout) as http_client:
                client: AsyncOpenAI = AsyncOpenAI(
                    api_key=api_key,
                    base_url=self._base_url,
                    http_client=http_client,
                    max_retries=0,
                )
                response: AgentRuntime = await client.chat.completions.create(
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
        """流式调用厂家 chat completions，逐块 yield ``LLMChunk``。

        与 ``chat`` 相同的客户端与错误映射；``create(stream=True)`` 后
        异步迭代 SDK stream，经 ``_parse_stream_chunk`` 过滤空块后下发。
        客户端在整段流结束（或异常）后随 ``async with`` 关闭。

        Args:
            request: 平台 LLM 请求。
            api_key: 厂家 API Key。
            proxy_manager: 出站代理管理器。

        Yields:
            文本 / reasoning / usage 等增量块。

        Raises:
            LLMProviderError: 鉴权、HTTP、超时、连接或其他失败。
        """
        proxy_url: str | None = _get_proxy_url(proxy_manager)
        try:
            async with httpx.AsyncClient(proxy=proxy_url, timeout=self._timeout) as http_client:
                client: AsyncOpenAI = AsyncOpenAI(
                    api_key=api_key,
                    base_url=self._base_url,
                    http_client=http_client,
                    max_retries=0,
                )
                stream: AgentRuntime = await client.chat.completions.create(
                    **_build_create_kwargs(request, stream=True),
                )
                async for chunk in stream:
                    parsed: LLMChunk | None = _parse_stream_chunk(chunk)
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
    """判断异常是否像 HTTP 401/403 鉴权失败。

    用于兜底 ``except Exception``：部分包装异常未继承 SDK 的
    ``AuthenticationError`` / ``APIStatusError``，但仍带 ``status_code``。

    Args:
        exc: 任意捕获到的异常。

    Returns:
        ``True`` 表示应按鉴权失败处理（触发 Key 轮换 / Failover）。
    """
    status_code: Any = getattr(exc, "status_code", None)
    return status_code in {401, 403}
