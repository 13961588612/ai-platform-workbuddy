"""APIKeyManager — 多 provider API Key 池管理。

维护每个 provider（deepseek、qwen）的 API Key 池，
支持轮询轮换、健康追踪和自动移除无效 Key（401/403 响应）。
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from src.llm.models import APIKey
from src.utils.exceptions import LLMProviderError
from src.utils.logging import get_logger

logger = get_logger("llm.key_manager")


class APIKeyManager:
    """
    管理每个 LLM provider 的 API Key 池。

    功能：
    - 每个 provider 的轮询 Key 轮换
    - 健康追踪（调用次数、错误率、最后使用时间）
    - 401/403（认证失败）时自动移除 Key
    - Key 恢复支持（管理员审核后重新添加）
    """

    def __init__(self) -> None:
        """初始化各 Provider 的 API Key 池与轮询索引。"""
        self._keys: dict[str, list[APIKey]] = {}
        self._rotation_index: dict[str, int] = {}
        self._lock = threading.Lock()

    def add_key(
        self,
        provider: str,
        key: str,
        label: str = "",
    ) -> None:
        """向 provider 的 Key 池中添加一个 API Key。"""
        with self._lock:
            if provider not in self._keys:
                self._keys[provider] = []
                self._rotation_index[provider] = 0

            api_key = APIKey(
                key=key,
                provider=provider,
                label=label or f"{provider}-key-{len(self._keys[provider]) + 1}",
            )
            self._keys[provider].append(api_key)
            logger.info("API key added", provider=provider, label=api_key.label)

    def set_keys(self, provider: str, keys: list[APIKey]) -> None:
        """替换某个 provider 的所有 Key。"""
        with self._lock:
            self._keys[provider] = list(keys)
            self._rotation_index[provider] = 0
            logger.info(
                "API keys set",
                provider=provider,
                count=len(keys),
            )

    def get_key(self, provider: str) -> APIKey:
        """
        使用轮询轮换获取下一个健康的 API Key。

        Args:
            provider: Provider 名称（deepseek、qwen）。

        Returns:
            下一个要使用的 APIKey。

        Raises:
            LLMProviderError: 没有可用的健康 Key 时抛出。
        """
        with self._lock:
            pool = self._keys.get(provider, [])
            healthy_keys = [k for k in pool if k.is_active and k.is_healthy]

            if not healthy_keys:
                logger.error("No healthy API keys available", provider=provider)
                raise LLMProviderError(
                    provider,
                    f"No healthy API keys available for provider '{provider}'",
                )

            idx = self._rotation_index.get(provider, 0) % len(healthy_keys)
            self._rotation_index[provider] = (idx + 1) % len(healthy_keys)

            selected = healthy_keys[idx]
            logger.debug(
                "API key selected",
                provider=provider,
                label=selected.label,
                index=idx,
            )
            return selected

    def mark_key_invalid(self, provider: str, key: str, error_message: str = "") -> None:
        """
        将某个 API Key 标记为无效（例如收到 401/403 后）。

        该 Key 被标记为不健康并从活跃轮换中移除。
        """
        with self._lock:
            pool = self._keys.get(provider, [])
            for api_key in pool:
                if api_key.key == key:
                    api_key.mark_unhealthy()
                    api_key.record_error(error_message)
                    logger.warning(
                        "API key marked invalid",
                        provider=provider,
                        label=api_key.label,
                        error=error_message,
                    )
                    break

    def record_success(self, provider: str, key: str) -> None:
        """记录某个 Key 的一次成功 API 调用。"""
        with self._lock:
            pool = self._keys.get(provider, [])
            for api_key in pool:
                if api_key.key == key:
                    api_key.record_success()
                    break

    def record_error(self, provider: str, key: str, error_message: str = "") -> None:
        """记录某个 Key 的一次失败 API 调用。"""
        with self._lock:
            pool = self._keys.get(provider, [])
            for api_key in pool:
                if api_key.key == key:
                    api_key.record_error(error_message)
                    break

    def get_key_stats(self, provider: str) -> list[dict]:
        """获取某个 provider 所有 Key 的统计信息。"""
        with self._lock:
            pool = self._keys.get(provider, [])
            return [
                {
                    "label": k.label,
                    "is_active": k.is_active,
                    "is_healthy": k.is_healthy,
                    "total_calls": k.total_calls,
                    "error_count": k.error_count,
                    "error_rate": round(k.error_rate, 4),
                    "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                }
                for k in pool
            ]

    def get_healthy_key_count(self, provider: str) -> int:
        """返回某个 provider 的健康 Key 数量。"""
        with self._lock:
            pool = self._keys.get(provider, [])
            return sum(1 for k in pool if k.is_active and k.is_healthy)

    def restore_key(self, provider: str, key: str) -> None:
        """将之前失效的 Key 恢复到活跃池中。"""
        with self._lock:
            pool = self._keys.get(provider, [])
            for api_key in pool:
                if api_key.key == key:
                    api_key.is_healthy = True
                    api_key.error_count = 0
                    logger.info(
                        "API key restored",
                        provider=provider,
                        label=api_key.label,
                    )
                    break


# Singleton 实例
_key_manager: APIKeyManager | None = None


def get_key_manager() -> APIKeyManager:
    """返回单例 APIKeyManager 实例。"""
    global _key_manager
    if _key_manager is None:
        _key_manager = APIKeyManager()
    return _key_manager
