"""QuotaManager — token 配额控制、速率限制和告警。

在 Redis 中按用户和部门追踪每日 token 用量。
当配额超限时阻止请求，并在用量达到
配置的阈值（默认 80%）时触发告警。
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis

from src.config import get_settings
from src.llm.models import QuotaInfo
from src.utils.exceptions import QuotaExceededError
from src.utils.logging import get_logger

logger = get_logger("llm.quota_manager")

# Redis key 前缀
USER_QUOTA_PREFIX = "quota:user"
DEPT_QUOTA_PREFIX = "quota:dept"
# 当前日期后缀的 Redis key（每日重置）
DATE_FORMAT = "%Y%m%d"


class QuotaManager:
    """
    按用户和部门管理 token 配额。

    每次 LLM 调用前都会进行配额检查：
    1. 查询 Redis 获取今日已用 token 数（用户 + 部门）
    2. 对比每日限额进行预检查
    3. 调用完成后更新实际用量

    默认值：
    - 每用户每日：100,000 tokens
    - 每部门每日：1,000,000 tokens
    - 告警阈值：80%
    - 超限行为：抛出 QuotaExceededError（429）
    """

    def __init__(self) -> None:
        """初始化 token 配额管理器（Redis 连接懒创建）。"""
        self._settings = get_settings()
        self._redis: aioredis.Redis | None = None
        self._default_user_limit = 100_000
        self._default_dept_limit = 1_000_000
        self._alert_threshold = 0.8

    async def _get_redis(self) -> aioredis.Redis:
        """获取或创建 Redis 连接。"""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._settings.redis_url,
                max_connections=self._settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,
            )
        return self._redis

    def _date_suffix(self) -> str:
        """获取 Redis key 的今日日期后缀（YYYYMMDD）。"""
        return datetime.now(timezone.utc).strftime(DATE_FORMAT)

    def _user_key(self, user_id: str) -> str:
        """用户每日配额的 Redis key。"""
        return f"{USER_QUOTA_PREFIX}:{user_id}:{self._date_suffix()}"

    def _dept_key(self, dept: str) -> str:
        """部门每日配额的 Redis key。"""
        return f"{DEPT_QUOTA_PREFIX}:{dept}:{self._date_suffix()}"

    async def check_quota(
        self,
        user_id: str,
        dept: str,
        estimated_tokens: int = 4096,
    ) -> bool:
        """
        检查用户/部门是否还有足够的剩余配额。

        Args:
            user_id: 用户标识符。
            dept: 部门标识符。
            estimated_tokens: 本次请求预估的 token 数。

        Returns:
            配额充足时返回 True。

        Raises:
            QuotaExceededError: 用户或部门配额超限时抛出。
        """
        if not user_id:
            return True

        redis = await self._get_redis()

        # 检查用户配额
        user_used = int(await redis.get(self._user_key(user_id)) or 0)
        if user_used + estimated_tokens > self._default_user_limit:
            logger.warning(
                "User quota exceeded",
                user_id=user_id,
                used=user_used,
                limit=self._default_user_limit,
                estimated=estimated_tokens,
            )
            raise QuotaExceededError(
                f"User {user_id} daily token quota exceeded "
                f"(used: {user_used}, limit: {self._default_user_limit})",
            )

        # 检查部门配额
        if dept:
            dept_used = int(await redis.get(self._dept_key(dept)) or 0)
            if dept_used + estimated_tokens > self._default_dept_limit:
                logger.warning(
                    "Department quota exceeded",
                    dept=dept,
                    used=dept_used,
                    limit=self._default_dept_limit,
                )
                raise QuotaExceededError(
                    f"Department {dept} daily token quota exceeded "
                    f"(used: {dept_used}, limit: {self._default_dept_limit})",
                )

        return True

    async def record_usage(
        self,
        user_id: str,
        dept: str,
        tokens: int,
    ) -> None:
        """
        LLM 调用后记录实际 token 用量。

        在 Redis 中更新用户和部门的计数器，
        设置 25 小时 TTL（覆盖时区差异以实现每日重置）。
        """
        if not user_id or tokens <= 0:
            return

        redis = await self._get_redis()
        ttl_seconds = 25 * 3600  # 25 小时

        # 更新用户配额
        user_key = self._user_key(user_id)
        await redis.incrby(user_key, tokens)
        await redis.expire(user_key, ttl_seconds)

        # 更新部门配额
        if dept:
            dept_key = self._dept_key(dept)
            await redis.incrby(dept_key, tokens)
            await redis.expire(dept_key, ttl_seconds)

        # 检查告警阈值
        user_used = int(await redis.get(user_key) or 0)
        if user_used >= int(self._default_user_limit * self._alert_threshold):
            logger.warning(
                "User quota alert threshold reached",
                user_id=user_id,
                used=user_used,
                limit=self._default_user_limit,
                threshold_pct=self._alert_threshold,
            )

    async def get_quota_info(
        self,
        user_id: str,
        dept: str = "",
    ) -> QuotaInfo:
        """获取用户当前的配额信息。"""
        redis = await self._get_redis()
        user_used = int(await redis.get(self._user_key(user_id)) or 0)
        return QuotaInfo(
            user_id=user_id,
            department=dept,
            daily_limit=self._default_user_limit,
            used_today=user_used,
            alert_threshold=self._alert_threshold,
        )

    async def reset_quota(self, user_id: str) -> None:
        """重置用户的每日配额（管理员覆盖）。"""
        redis = await self._get_redis()
        await redis.delete(self._user_key(user_id))
        logger.info("User quota reset", user_id=user_id)


# Singleton 实例
_quota_manager: QuotaManager | None = None


def get_quota_manager() -> QuotaManager:
    """返回单例 QuotaManager 实例。"""
    global _quota_manager
    if _quota_manager is None:
        _quota_manager = QuotaManager()
    return _quota_manager
