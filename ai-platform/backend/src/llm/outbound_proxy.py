"""OutboundProxyManager — 管理 LLM API 调用的内部出口代理池。

所有 LLM API 请求都通过内部出口代理（Squid）路由，
该代理强制执行域名白名单，确保只有授权的
LLM provider 端点（api.deepseek.com、dashscope.aliyuncs.com）
可以从内部网络访问。

功能：
- 健康代理节点之间的轮询负载均衡
- 健康检查（每 30 秒一次，连续 3 次失败 = 不健康）
- 域名白名单强制执行
- 请求审计日志
"""

from __future__ import annotations
from typing import Any

import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from src.config import get_settings
from src.llm.models import ProxyNode
from src.utils.exceptions import ProxyUnavailableError
from src.utils.logging import get_logger

logger = get_logger("llm.outbound_proxy")

# 健康检查配置
HEALTH_CHECK_INTERVAL_SECONDS = 30
MAX_CONSECUTIVE_FAILURES = 3


class OutboundProxyManager:
    """
    管理用于 LLM API 请求的出口代理节点池。

    代理池通过系统设置进行配置。每个节点都会定期
    进行健康检查，只有健康的节点才会用于负载均衡。
    """

    # 域名白名单 — 仅允许这些 LLM provider 域名
    ALLOWED_DOMAINS: list[str] = [
        "api.deepseek.com",
        "dashscope.aliyuncs.com",
    ]

    def __init__(self) -> None:
        """从应用配置初始化出口代理池（Squid 节点与健康检查）。"""
        self._settings = get_settings()
        self._proxy_pool: list[ProxyNode] = []
        self._current_index: int = 0
        self._lock = threading.Lock()
        self._audit_log_enabled: bool = True
        self._initialize_pool()

    def _initialize_pool(self) -> None:
        """从设置中初始化代理池。"""
        if self._settings.OUTBOUND_PROXY_ENABLED:
            node: ProxyNode = ProxyNode(
                host=self._settings.OUTBOUND_PROXY_HOST,
                port=self._settings.OUTBOUND_PROXY_PORT,
                protocol="http",
            )
            self._proxy_pool.append(node)
            logger.info(
                "Proxy node initialized",
                host=node.host,
                port=node.port,
            )

    def add_proxy_node(self, host: str, port: int, protocol: str = "http") -> None:
        """向池中添加一个代理节点。"""
        with self._lock:
            node: ProxyNode = ProxyNode(host=host, port=port, protocol=protocol)
            self._proxy_pool.append(node)
            logger.info("Proxy node added", host=host, port=port)

    def get_proxy(self) -> ProxyNode:
        """
        获取下一个健康的代理节点（轮询）。

        Returns:
            一个健康的 ProxyNode。

        Raises:
            ProxyUnavailableError: 所有代理节点都不健康时抛出。
        """
        with self._lock:
            healthy_nodes: list[Any] = [n for n in self._proxy_pool if n.is_healthy]

            if not healthy_nodes:
                logger.error("All outbound proxy nodes unavailable")
                raise ProxyUnavailableError()

            idx: Any = self._current_index % len(healthy_nodes)
            self._current_index = (idx + 1) % len(healthy_nodes)

            selected: Any = healthy_nodes[idx]
            selected.total_requests += 1

            logger.debug(
                "Proxy node selected",
                host=selected.host,
                port=selected.port,
                index=idx,
            )
            return selected

    def get_proxy_url(self) -> str | None:
        """获取代理 URL 字符串，如果代理被禁用则返回 None。"""
        if not self._settings.OUTBOUND_PROXY_ENABLED:
            return None
        try:
            node: ProxyNode = self.get_proxy()
            return node.url
        except ProxyUnavailableError:
            return None

    def is_allowed(self, domain: str) -> bool:
        """
        检查域名是否在白名单中。

        Args:
            domain: 要检查的域名（例如 "api.deepseek.com"）。

        Returns:
            域名是否被允许。
        """
        # 合并配置的允许域名与默认值
        allowed: set[Any] = set(
            self.ALLOWED_DOMAINS + self._settings.OUTBOUND_PROXY_ALLOWED_DOMAINS
        )
        return any(domain.endswith(d) for d in allowed)

    def check_domain(self, url: str) -> bool:
        """检查 URL 的域名是否被允许通过代理。"""
        parsed: Any = urlparse(url)
        domain: Any = parsed.hostname or ""
        return self.is_allowed(domain)

    def log_request(
        self,
        request_info: dict[str, Any],
        response_info: dict[str, Any],
    ) -> None:
        """
        为代理请求写入审计日志条目。

        Args:
            request_info: 包含 proxy_node、domain、method 等字段的字典。
            response_info: 包含 status_code、latency_ms、token_usage 等字段的字典。
        """
        if not self._audit_log_enabled:
            return

        audit_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "proxy_node": request_info.get("proxy_node"),
            "target_domain": request_info.get("domain"),
            "method": request_info.get("method", "POST"),
            "status_code": response_info.get("status_code"),
            "latency_ms": response_info.get("latency_ms"),
            "token_usage": response_info.get("token_usage"),
        }
        logger.info("Proxy audit log", **audit_entry)

    async def health_check_all(self) -> dict[str, bool]:
        """
        检查所有代理节点的健康状态。

        节点在连续 MAX_CONSECUTIVE_FAILURES 次检查失败后
        会被标记为不健康。

        Returns:
            映射代理 URL 到健康状态的字典。
        """
        results: dict[str, bool] = {}
        for node in self._proxy_pool:
            is_healthy: bool = await self._check_node(node)
            results[node.url] = is_healthy
        return results

    async def _check_node(self, node: ProxyNode) -> bool:
        """对单个代理节点执行健康检查。"""
        try:
            async with httpx.AsyncClient(
                proxy=node.url,
                timeout=10,
            ) as client:
                # 通过代理进行简单的连通性检查
                response: httpx.Response = await client.get("https://httpbin.org/status/200")
                is_ok: bool = response.status_code == 200
        except Exception as exc:
            logger.warning(
                "Proxy health check failed",
                host=node.host,
                port=node.port,
                error=str(exc),
            )
            is_ok: bool = False

        with self._lock:
            node.last_check_at = datetime.now(timezone.utc)
            if is_ok:
                node.consecutive_failures = 0
                node.is_healthy = True
            else:
                node.consecutive_failures += 1
                if node.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    node.is_healthy = False
                    logger.warning(
                        "Proxy node marked unhealthy",
                        host=node.host,
                        port=node.port,
                        consecutive_failures=node.consecutive_failures,
                    )

        return node.is_healthy

    def get_pool_status(self) -> list[dict[str, Any]]:
        """获取所有代理节点的状态。"""
        return [
            {
                "host": n.host,
                "port": n.port,
                "url": n.url,
                "is_healthy": n.is_healthy,
                "consecutive_failures": n.consecutive_failures,
                "total_requests": n.total_requests,
                "last_check_at": n.last_check_at.isoformat() if n.last_check_at else None,
            }
            for n in self._proxy_pool
        ]


# Singleton 实例
_proxy_manager: OutboundProxyManager | None = None


def get_proxy_manager() -> OutboundProxyManager:
    """返回单例 OutboundProxyManager 实例。"""
    global _proxy_manager
    if _proxy_manager is None:
        _proxy_manager = OutboundProxyManager()
    return _proxy_manager
