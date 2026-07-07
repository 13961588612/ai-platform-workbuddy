"""TokenTracker — 将 LLM token 用量持久化到 PostgreSQL 用于可观测性。

每次 LLM 调用（chat 和 chat_stream）都会将其 token 消耗
记录到 token_usage 表中，使管理后台能够按会话、用户、
部门、模型和时间范围显示用量。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import db_session_context
from src.llm.models import TokenUsage
from src.models.session import TokenUsageModel
from src.utils.logging import get_logger

logger = get_logger("llm.token_tracker")


class TokenTracker:
    """
    将每次 LLM 调用的 token 用量记录到 PostgreSQL。

    提供写入（record）和读取（query_usage、get_summary）
    两种操作，用于 token 消耗追踪和报告。
    """

    async def record(
        self,
        session_id: str,
        user_id: str,
        dept: str,
        model: str,
        provider: str,
        usage: TokenUsage,
    ) -> None:
        """
        将单次 LLM 调用的 token 用量记录到数据库。

        Args:
            session_id: 与调用关联的 Session ID。
            user_id: 发起调用的用户。
            dept: 用户所属部门。
            model: 模型名称（例如 deepseek-v4-flash）。
            provider: Provider 名称（deepseek、qwen）。
            usage: 包含 prompt/completion/total 计数的 TokenUsage。
        """
        entry = TokenUsageModel(
            session_id=session_id or "unknown",
            user_id=user_id or "unknown",
            department=dept or "unknown",
            model=model,
            provider=provider,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            total_tokens=usage.total_tokens,
            timestamp=datetime.now(timezone.utc),
        )

        try:
            async with db_session_context() as session:
                session.add(entry)
                await session.commit()
            logger.debug(
                "Token usage recorded",
                session_id=session_id,
                user_id=user_id,
                model=model,
                total_tokens=usage.total_tokens,
            )
        except Exception as exc:
            logger.error(
                "Failed to record token usage",
                error=str(exc),
                session_id=session_id,
            )

    async def query_usage(
        self,
        user_id: str | None = None,
        dept: str | None = None,
        model: str | None = None,
        session_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        带过滤条件查询 token 用量记录。

        Returns:
            Usage 记录列表，以字典形式返回。
        """
        async with db_session_context() as session:
            stmt = select(TokenUsageModel).order_by(
                TokenUsageModel.timestamp.desc()
            )

            if user_id:
                stmt = stmt.where(TokenUsageModel.user_id == user_id)
            if dept:
                stmt = stmt.where(TokenUsageModel.department == dept)
            if model:
                stmt = stmt.where(TokenUsageModel.model == model)
            if session_id:
                stmt = stmt.where(TokenUsageModel.session_id == session_id)
            if start_time:
                stmt = stmt.where(TokenUsageModel.timestamp >= start_time)
            if end_time:
                stmt = stmt.where(TokenUsageModel.timestamp <= end_time)

            stmt = stmt.limit(limit).offset(offset)
            result = await session.execute(stmt)
            rows = result.scalars().all()

        return [
            {
                "id": str(row.id),
                "session_id": row.session_id,
                "user_id": row.user_id,
                "department": row.department,
                "model": row.model,
                "provider": row.provider,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                "total_tokens": row.total_tokens,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
            }
            for row in rows
        ]

    async def get_summary(
        self,
        user_id: str | None = None,
        dept: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> dict[str, Any]:
        """
        获取聚合 token 用量摘要。

        Returns:
            包含 total_tokens、by_model、by_provider 分解的字典。
        """
        async with db_session_context() as session:
            stmt = select(TokenUsageModel)

            if user_id:
                stmt = stmt.where(TokenUsageModel.user_id == user_id)
            if dept:
                stmt = stmt.where(TokenUsageModel.department == dept)
            if start_time:
                stmt = stmt.where(TokenUsageModel.timestamp >= start_time)
            if end_time:
                stmt = stmt.where(TokenUsageModel.timestamp <= end_time)

            result = await session.execute(stmt)
            rows = result.scalars().all()

        if not rows:
            return {
                "total_calls": 0,
                "total_tokens": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "by_model": {},
                "by_provider": {},
            }

        by_model: dict[str, int] = {}
        by_provider: dict[str, int] = {}
        total_prompt = 0
        total_completion = 0
        total_tokens = 0

        for row in rows:
            by_model[row.model] = by_model.get(row.model, 0) + row.total_tokens
            by_provider[row.provider] = by_provider.get(row.provider, 0) + row.total_tokens
            total_prompt += row.prompt_tokens
            total_completion += row.completion_tokens
            total_tokens += row.total_tokens

        return {
            "total_calls": len(rows),
            "total_tokens": total_tokens,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "by_model": by_model,
            "by_provider": by_provider,
        }


# Singleton 实例
_token_tracker: TokenTracker | None = None


def get_token_tracker() -> TokenTracker:
    """返回单例 TokenTracker 实例。"""
    global _token_tracker
    if _token_tracker is None:
        _token_tracker = TokenTracker()
    return _token_tracker
