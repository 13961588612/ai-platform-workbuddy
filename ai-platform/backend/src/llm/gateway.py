"""LLMGateway — 统一的 LLM API 入口点。

编排所有 LLM 操作：provider 选择、Key 轮换、
配额检查、出口代理路由、故障转移和 token 追踪。
Agent 运行时所有 LLM 调用都经过此 Gateway。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from src.config import get_settings
from src.llm.deepseek_adapter import DeepSeekAdapter
from src.llm.failover import FailoverManager, get_failover_manager
from src.llm.key_manager import APIKeyManager, get_key_manager
from src.llm.models import LLMChunk, LLMRequest, LLMResponse, TokenUsage
from src.llm.outbound_proxy import OutboundProxyManager, get_proxy_manager
from src.llm.qwen_adapter import QwenAdapter
from src.llm.quota_manager import QuotaManager, get_quota_manager
from src.llm.token_tracker import TokenTracker, get_token_tracker
from src.utils.exceptions import (
    FailoverExhaustedError,
    LLMProviderError,
    QuotaExceededError,
)
from src.utils.logging import get_logger

logger = get_logger("llm.gateway")


class LLMGateway:
    """
    统一 LLM API Gateway — 所有 LLM 调用的单一入口点。

    职责：
    - Provider 选择（deepseek 主，qwen 备用）
    - 通过 APIKeyManager 进行 API Key 池轮换
    - 通过 QuotaManager 执行 token 配额控制
    - 通过 OutboundProxyManager 进行出口代理路由
    - 通过 FailoverManager 实现自动故障转移
    - 通过 TokenTracker 追踪 token 用量

    用法：
        gateway = get_llm_gateway()
        response = await gateway.chat(request)
        # 或流式调用：
        async for chunk in gateway.chat_stream(request):
            ...
    """

    def __init__(self) -> None:
        """初始化 LLM Gateway 并挂载 Key、配额、代理、故障转移等子组件。"""
        self._settings = get_settings()
        self._key_manager: APIKeyManager = get_key_manager()
        self._quota_manager: QuotaManager = get_quota_manager()
        self._proxy_manager: OutboundProxyManager = get_proxy_manager()
        self._token_tracker: TokenTracker = get_token_tracker()
        self._failover_manager: FailoverManager = get_failover_manager()
        self._adapters: dict[str, Any] = {
            "deepseek": DeepSeekAdapter(),
            "qwen": QwenAdapter(),
        }
        self._initialized: bool = False

    def initialize(self) -> None:
        """初始化 Gateway，加载配置的 API Key。"""
        # 从配置中加载 API Key
        if self._settings.DEEPSEEK_API_KEY:
            self._key_manager.add_key(
                provider="deepseek",
                key=self._settings.DEEPSEEK_API_KEY,
                label="deepseek-default",
            )
        if self._settings.QWEN_API_KEY and not self._settings.QWEN_API_KEY.startswith("your-"):
            self._key_manager.add_key(
                provider="qwen",
                key=self._settings.QWEN_API_KEY,
                label="qwen-default",
            )

        self._initialized = True
        logger.info(
            "LLM Gateway initialized",
            deepseek_keys=self._key_manager.get_healthy_key_count("deepseek"),
            qwen_keys=self._key_manager.get_healthy_key_count("qwen"),
        )

    def _remap_request_for_provider(
        self, provider: str, request: LLMRequest
    ) -> LLMRequest:
        """跨 provider 故障转移时使用 provider 对应的模型。"""
        model = request.model
        if provider == "deepseek" and "deepseek" not in model.lower():
            model = self._settings.LLM_PRIMARY_MODEL
        elif provider == "qwen" and "qwen" not in model.lower():
            model = self._settings.LLM_FALLBACK_MODEL
        if model == request.model:
            return request
        return request.model_copy(update={"model": model})

    def _select_provider(self, model: str) -> str:
        """
        根据模型名称选择 LLM provider。

        Args:
            model: 模型名称（例如 "deepseek-v4-flash"、"qwen3.6-plus"）。

        Returns:
            Provider 名称（"deepseek" 或 "qwen"）。
        """
        if "deepseek" in model.lower():
            return "deepseek"
        if "qwen" in model.lower():
            return "qwen"
        # 默认使用 failover manager 的当前活跃 provider
        return self._failover_manager.get_active_provider()

    def _check_quota(self, request: LLMRequest) -> None:
        """
        在发起 LLM 调用前检查 token 配额（用于日志记录的同步包装）。

        实际的异步配额检查在 chat()/chat_stream() 中
        通过 `await self._quota_manager.check_quota(...)` 执行。
        """
        logger.debug(
            "Quota pre-check",
            user_id=request.user_id,
            dept=request.dept,
            estimated_tokens=request.max_tokens,
        )

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """
        发送非流式聊天补全请求。

        自动处理 provider 选择、配额检查、Key 轮换、
        故障转移和 token 追踪。

        Args:
            request: 包含消息、模型和参数的 LLMRequest。

        Returns:
            包含生成内容和用量信息的 LLMResponse。

        Raises:
            QuotaExceededError: token 配额超限时抛出。
            FailoverExhaustedError: 所有 provider 都失败时抛出。
            LLMProviderError: 发生不可恢复的 API 错误时抛出。
        """
        if not self._initialized:
            self.initialize()

        # 检查配额
        await self._quota_manager.check_quota(
            request.user_id,
            request.dept,
            estimated_tokens=request.max_tokens,
        )

        # 获取要尝试的 provider 有序列表（活跃 + 备用）
        providers = self._failover_manager.get_failover_providers()

        last_error: Exception | None = None
        for provider in providers:
            try:
                response = await self._call_provider(provider, request)
                # 成功 — 记录
                self._failover_manager.record_success(provider)

                # 追踪 token 用量
                await self._token_tracker.record(
                    session_id=request.session_id,
                    user_id=request.user_id,
                    dept=request.dept,
                    model=response.model or request.model,
                    provider=provider,
                    usage=response.usage,
                )

                # 记录配额的实际用量
                await self._quota_manager.record_usage(
                    request.user_id,
                    request.dept,
                    response.usage.total_tokens,
                )

                return response

            except LLMProviderError as exc:
                last_error = exc
                self._failover_manager.record_failure(provider, str(exc))

                # 处理 401/403 — 将 Key 标记为无效
                if "Authentication failed" in str(exc):
                    logger.warning(
                        "API key authentication failed, marking key invalid",
                        provider=provider,
                        error=str(exc),
                    )

                logger.warning(
                    "Provider call failed, trying next",
                    provider=provider,
                    error=str(exc),
                )
                continue

        # 所有 provider 均已尝试失败
        raise FailoverExhaustedError(
            f"All LLM providers failed. Last error: {last_error}",
        )

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[LLMChunk]:
        """
        发送流式聊天补全请求。

        从 provider 返回 LLMChunk 对象时逐个 yield。
        在初始连接失败时处理故障转移。

        Args:
            request: 设置 stream=True 的 LLMRequest。

        Yields:
            包含增量内容的 LLMChunk 对象。

        Raises:
            QuotaExceededError: token 配额超限时抛出。
            FailoverExhaustedError: 所有 provider 都失败时抛出。
        """
        if not self._initialized:
            self.initialize()

        # 检查配额
        await self._quota_manager.check_quota(
            request.user_id,
            request.dept,
            estimated_tokens=request.max_tokens,
        )

        providers = self._failover_manager.get_failover_providers()
        total_usage = TokenUsage()
        provider_used: str = ""
        success: bool = False

        for provider in providers:
            try:
                async for chunk in self._call_provider_stream(provider, request):
                    if chunk.usage is not None:
                        total_usage += chunk.usage
                    yield chunk

                success = True
                provider_used = provider
                self._failover_manager.record_success(provider)
                break

            except LLMProviderError as exc:
                self._failover_manager.record_failure(provider, str(exc))
                logger.warning(
                    "Provider stream failed, trying next",
                    provider=provider,
                    error=str(exc),
                )
                continue

        if not success:
            raise FailoverExhaustedError("All LLM providers failed during streaming")

        # 流式完成后追踪 token 用量
        if total_usage.total_tokens > 0:
            await self._token_tracker.record(
                session_id=request.session_id,
                user_id=request.user_id,
                dept=request.dept,
                model=request.model,
                provider=provider_used,
                usage=total_usage,
            )
            await self._quota_manager.record_usage(
                request.user_id,
                request.dept,
                total_usage.total_tokens,
            )

    async def _call_provider(
        self,
        provider: str,
        request: LLMRequest,
    ) -> LLMResponse:
        """通过 Key 和代理调用指定 provider 的适配器。"""
        adapter = self._adapters.get(provider)
        if adapter is None:
            raise LLMProviderError(provider, f"Unknown provider: {provider}")

        key = self._key_manager.get_key(provider)

        # 域名白名单检查
        endpoint = self._get_provider_endpoint(provider)
        if not self._proxy_manager.check_domain(endpoint):
            raise LLMProviderError(
                provider,
                f"Domain not in whitelist: {endpoint}",
            )

        try:
            provider_request = self._remap_request_for_provider(provider, request)
            response = await adapter.chat(
                request=provider_request,
                api_key=key.key,
                proxy_manager=self._proxy_manager,
            )
            # 记录 Key 成功
            self._key_manager.record_success(provider, key.key)
            return response
        except LLMProviderError as exc:
            # 记录 Key 错误
            self._key_manager.record_error(provider, key.key, str(exc))
            # 如果认证失败，将 Key 标记为无效
            if "Authentication failed" in str(exc):
                self._key_manager.mark_key_invalid(provider, key.key, str(exc))
            raise

    async def _call_provider_stream(
        self,
        provider: str,
        request: LLMRequest,
    ) -> AsyncIterator[LLMChunk]:
        """调用指定 provider 的流式适配器。"""
        adapter = self._adapters.get(provider)
        if adapter is None:
            raise LLMProviderError(provider, f"Unknown provider: {provider}")

        key = self._key_manager.get_key(provider)

        endpoint = self._get_provider_endpoint(provider)
        if not self._proxy_manager.check_domain(endpoint):
            raise LLMProviderError(
                provider,
                f"Domain not in whitelist: {endpoint}",
            )

        provider_request = self._remap_request_for_provider(provider, request)
        async for chunk in adapter.chat_stream(
            request=provider_request,
            api_key=key.key,
            proxy_manager=self._proxy_manager,
        ):
            yield chunk

    def _get_provider_endpoint(self, provider: str) -> str:
        """获取 provider 的 API 端点 URL。"""
        if provider == "deepseek":
            return self._settings.DEEPSEEK_API_ENDPOINT
        if provider == "qwen":
            return self._settings.QWEN_API_ENDPOINT
        return ""

    def get_status(self) -> dict[str, Any]:
        """获取 LLM Gateway 当前状态，用于监控。"""
        return {
            "initialized": self._initialized,
            "failover": self._failover_manager.get_status(),
            "proxy_pool": self._proxy_manager.get_pool_status(),
            "providers": {
                name: {
                    "healthy_keys": self._key_manager.get_healthy_key_count(name),
                    "key_stats": self._key_manager.get_key_stats(name),
                }
                for name in self._adapters
            },
        }


# Singleton 实例
_llm_gateway: LLMGateway | None = None


def get_llm_gateway() -> LLMGateway:
    """返回单例 LLMGateway 实例。"""
    global _llm_gateway
    if _llm_gateway is None:
        _llm_gateway = LLMGateway()
    return _llm_gateway
