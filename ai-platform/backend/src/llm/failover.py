"""FailoverManager — LLM 调用的自动 provider 故障转移。

监控 LLM provider 的健康状态，并在主 provider（deepseek）
连续出现故障时自动切换到备用 provider（qwen）。
当主 provider 恢复后，流量会自动切回。
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any

from src.config import get_settings
from src.llm.models import FailoverConfig
from src.utils.exceptions import FailoverExhaustedError
from src.utils.logging import get_logger

logger = get_logger("llm.failover")


class FailoverManager:
    """
    LLM provider 故障转移管理器。

    状态机：
    - NORMAL：主 provider 活跃且健康。
    - FAILOVER：主 provider 已故障，正在使用备用 provider。
    - RECOVERING：正在探测主 provider 是否恢复。

    管理器追踪每个 provider 的连续故障次数，
    并在达到故障阈值时切换到备用 provider。
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._config = FailoverConfig(
            primary=self._settings.LLM_PRIMARY_PROVIDER,
            fallback=self._settings.LLM_FALLBACK_PROVIDER,
            auto_switch=self._settings.LLM_FAILOVER_AUTO_SWITCH,
            max_retries=self._settings.LLM_MAX_RETRIES,
        )
        self._failure_counts: dict[str, int] = {self._config.primary: 0, self._config.fallback: 0}
        self._active_provider: str = self._config.primary
        self._last_failure_at: dict[str, datetime | None] = {
            self._config.primary: None,
            self._config.fallback: None,
        }
        self._last_recovery_check: float = 0.0
        self._lock = threading.Lock()

    @property
    def active_provider(self) -> str:
        """返回当前活跃的 provider 名称。"""
        return self._active_provider

    @property
    def is_failover_active(self) -> bool:
        """当前是否正在使用备用 provider。"""
        return self._active_provider == self._config.fallback

    def get_active_provider(self) -> str:
        """获取当前活跃的 provider，同时检查是否需要恢复。"""
        with self._lock:
            # 如果处于故障转移模式，定期检查主 provider 是否已恢复
            if self._active_provider == self._config.fallback and self._config.auto_switch:
                self._maybe_try_recovery()
            return self._active_provider

    def get_fallback_provider(self) -> str:
        """返回备用 provider 名称。"""
        return self._config.fallback

    def record_success(self, provider: str) -> None:
        """记录一次成功的调用 — 重置故障计数器。"""
        with self._lock:
            self._failure_counts[provider] = 0
            logger.debug(
                "Provider success recorded",
                provider=provider,
                active=self._active_provider,
            )

    def record_failure(self, provider: str, error: str = "") -> None:
        """
        记录一次 provider 的失败调用。

        如果主 provider 的故障次数达到阈值，
        则切换到备用 provider。
        """
        with self._lock:
            self._failure_counts[provider] = self._failure_counts.get(provider, 0) + 1
            self._last_failure_at[provider] = datetime.now(timezone.utc)

            failures = self._failure_counts[provider]
            logger.warning(
                "Provider failure recorded",
                provider=provider,
                failures=failures,
                threshold=self._config.failure_threshold,
                error=error,
            )

            # 如果主 provider 故障太多则切换到备用
            if (
                provider == self._config.primary
                and self._active_provider == self._config.primary
                and failures >= self._config.failure_threshold
                and self._config.auto_switch
            ):
                self._active_provider = self._config.fallback
                logger.error(
                    "Failover triggered — switching to fallback provider",
                    from_provider=self._config.primary,
                    to_provider=self._config.fallback,
                    failures=failures,
                )

    def get_failover_providers(self) -> list[str]:
        """
        获取要依次尝试的 provider 有序列表。

        活跃 provider 排在第一位，备用排在第二位。
        """
        with self._lock:
            if self._active_provider == self._config.primary:
                return [self._config.primary, self._config.fallback]
            return [self._config.fallback, self._config.primary]

    def _maybe_try_recovery(self) -> None:
        """检查是否已过足够时间以尝试恢复到主 provider。"""
        now = time.monotonic()
        if now - self._last_recovery_check < self._config.recovery_check_interval:
            return

        self._last_recovery_check = now

        # 如果主 provider 上次故障时间已过很久，尝试切回
        last_failure = self._last_failure_at.get(self._config.primary)
        if last_failure is not None:
            elapsed = (datetime.now(timezone.utc) - last_failure).total_seconds()
            if elapsed >= self._config.recovery_check_interval:
                self._active_provider = self._config.primary
                self._failure_counts[self._config.primary] = 0
                logger.info(
                    "Recovery attempt — switching back to primary provider",
                    provider=self._config.primary,
                )

    def get_status(self) -> dict[str, Any]:
        """获取当前故障转移状态，用于监控。"""
        with self._lock:
            return {
                "active_provider": self._active_provider,
                "is_failover_active": self.is_failover_active,
                "primary": self._config.primary,
                "fallback": self._config.fallback,
                "failure_counts": dict(self._failure_counts),
                "last_failure_at": {
                    k: v.isoformat() if v else None
                    for k, v in self._last_failure_at.items()
                },
            }

    def reset(self) -> None:
        """重置所有故障计数并恢复到主 provider。"""
        with self._lock:
            self._failure_counts = {self._config.primary: 0, self._config.fallback: 0}
            self._active_provider = self._config.primary
            self._last_failure_at = {
                self._config.primary: None,
                self._config.fallback: None,
            }
            logger.info("Failover manager reset to primary provider")


# Singleton 实例
_failover_manager: FailoverManager | None = None


def get_failover_manager() -> FailoverManager:
    """返回单例 FailoverManager 实例。"""
    global _failover_manager
    if _failover_manager is None:
        _failover_manager = FailoverManager()
    return _failover_manager
