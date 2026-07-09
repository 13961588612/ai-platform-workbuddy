"""ApprovalStore — 内存审批请求存储。

提供线程安全（兼容 asyncio）的 HITL 审批记录存储。支持：
- 创建 pending 状态的审批
- 更新审批状态（approved/rejected/timeout）
- 按 approval_id、user_id、session_id 或 status 查询
- 自动超时检测

生产环境中可替换为 Redis 后端以支持分布式部署。
当前使用内存字典配合 asyncio.Lock 进行并发控制。
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from src.utils.logging import get_logger

logger = get_logger("hitl.store")


class ApprovalStatus(str, Enum):
    """审批生命周期状态。"""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    TIMEOUT = "timeout"
    EXPIRED = "expired"


class ApprovalRecord(BaseModel):
    """
    HITL 审批请求记录。

    表示从 Agent 向人类用户发起的单个审批请求。
    Agent 暂停执行直到用户响应（或发生超时）。

    属性：
        approval_id: 唯一审批请求 ID
        session_id: 触发审批的 Session
        agent_id: 触发审批的 Agent
        skill_id: 需要审批的 Skill
        user_id: 需要批准的用户
        status: 当前审批状态
        detail: 审批详情（标题、描述等）
        created_at: 创建时间 ISO 时间戳
        resolved_at: 解决时间 ISO 时间戳（pending 时为 null）
        comment: 用户响应时的评论
        timeout_seconds: 超时秒数
    """

    approval_id: str = Field(default="", description="唯一审批 ID")
    session_id: str = Field(default="", description="Session ID")
    agent_id: str = Field(default="", description="Agent ID")
    skill_id: str = Field(default="", description="需要审批的 Skill ID")
    user_id: str = Field(default="", description="需要审批的用户 ID")
    status: ApprovalStatus = Field(
        default=ApprovalStatus.PENDING, description="审批状态"
    )
    detail: dict[str, Any] = Field(
        default_factory=dict, description="审批详情（标题、描述等）"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    resolved_at: datetime | None = None
    comment: str | None = None
    timeout_seconds: int = Field(default=300, description="超时秒数")

    def is_expired(self) -> bool:
        """检查此审批是否已超时。"""
        if self.status != ApprovalStatus.PENDING:
            return False
        expiry: Any = self.created_at + timedelta(seconds=self.timeout_seconds)
        return datetime.now(timezone.utc) > expiry


class ApprovalStore:
    """
    内存审批请求存储。

    提供异步方法用于创建、查询和更新审批记录。
    使用 asyncio.Lock 进行并发控制。

    生产环境中将内部字典替换为 Redis 操作以支持分布式部署。
    """

    def __init__(self) -> None:
        """初始化 ApprovalStore。"""
        self._records: dict[str, ApprovalRecord] = {}
        self._lock = asyncio_lock()

    async def create(
        self,
        session_id: str,
        agent_id: str,
        skill_id: str,
        user_id: str,
        detail: dict[str, Any],
        timeout_seconds: int = 300,
    ) -> ApprovalRecord:
        """
        创建一个新的审批请求。

        参数：
            session_id: 触发审批的 Session ID。
            agent_id: Agent ID。
            skill_id: 需要审批的 Skill ID。
            user_id: 需要审批的用户 ID。
            detail: 审批详情字典（标题、描述等）。
            timeout_seconds: 超时秒数（默认：300 = 5 分钟）。

        返回：
            创建的 ApprovalRecord。
        """
        record: ApprovalRecord = ApprovalRecord(
            approval_id=f"approval-{uuid4().hex[:16]}",
            session_id=session_id,
            agent_id=agent_id,
            skill_id=skill_id,
            user_id=user_id,
            status=ApprovalStatus.PENDING,
            detail=detail,
            timeout_seconds=timeout_seconds,
        )
        async with self._lock:
            self._records[record.approval_id] = record
        logger.info(
            "Approval created",
            approval_id=record.approval_id,
            session_id=session_id,
            agent_id=agent_id,
            skill_id=skill_id,
            user_id=user_id,
        )
        return record

    async def get(self, approval_id: str) -> ApprovalRecord | None:
        """按 ID 获取审批记录。"""
        async with self._lock:
            return self._records.get(approval_id)

    async def update_status(
        self,
        approval_id: str,
        status: ApprovalStatus,
        comment: str | None = None,
    ) -> ApprovalRecord | None:
        """
        更新审批状态。

        参数：
            approval_id: 要更新的审批 ID。
            status: 新状态。
            comment: 可选的用户评论。

        返回：
            更新后的 ApprovalRecord，若未找到则返回 None。
        """
        async with self._lock:
            record: Skill | None = self._records.get(approval_id)
            if not record:
                return None
            if record.status != ApprovalStatus.PENDING:
                logger.warning(
                    "Approval already resolved",
                    approval_id=approval_id,
                    current_status=record.status.value,
                    new_status=status.value,
                )
                return record

            record.status = status
            record.resolved_at = datetime.now(timezone.utc)
            record.comment = comment
            logger.info(
                "Approval status updated",
                approval_id=approval_id,
                status=status.value,
                comment=comment,
            )
            return record

    async def list_by_user(
        self,
        user_id: str,
        status: ApprovalStatus | None = None,
    ) -> list[ApprovalRecord]:
        """列出某用户的审批，可按状态筛选。"""
        async with self._lock:
            results: list[Any] = [
                record
                for record in self._records.values()
                if record.user_id == user_id
                and (status is None or record.status == status)
            ]
        # 按创建时间降序排列
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    async def list_by_session(
        self,
        session_id: str,
        status: ApprovalStatus | None = None,
    ) -> list[ApprovalRecord]:
        """列出某 Session 的审批，可按状态筛选。"""
        async with self._lock:
            results: list[Any] = [
                record
                for record in self._records.values()
                if record.session_id == session_id
                and (status is None or record.status == status)
            ]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results

    async def list_all(
        self,
        status: ApprovalStatus | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        """列出所有审批，可按状态筛选。"""
        async with self._lock:
            results: list[Any] = [
                record
                for record in self._records.values()
                if status is None or record.status == status
            ]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    async def list_pending(self) -> list[ApprovalRecord]:
        """列出所有待审批记录（用于超时检查）。"""
        async with self._lock:
            return [
                record
                for record in self._records.values()
                if record.status == ApprovalStatus.PENDING
            ]

    async def get_stats(self) -> dict[str, int]:
        """获取审批统计摘要。"""
        async with self._lock:
            total: Any = len(self._records)
            pending: Any = sum(
                1 for r in self._records.values()
                if r.status == ApprovalStatus.PENDING
            )
            approved: Any = sum(
                1 for r in self._records.values()
                if r.status == ApprovalStatus.APPROVED
            )
            rejected: Any = sum(
                1 for r in self._records.values()
                if r.status == ApprovalStatus.REJECTED
            )
            timeout: Any = sum(
                1 for r in self._records.values()
                if r.status == ApprovalStatus.TIMEOUT
            )
        return {
            "total": total,
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
            "timeout": timeout,
        }

    async def delete(self, approval_id: str) -> bool:
        """删除一条审批记录。"""
        async with self._lock:
            if approval_id in self._records:
                del self._records[approval_id]
                logger.info("Approval deleted", approval_id=approval_id)
                return True
            return False

    async def cleanup_expired(self) -> int:
        """
        将过期的待审批记录标记为超时。

        返回被标记为超时的审批数量。
        """
        timed_out: int = 0
        async with self._lock:
            for record in self._records.values():
                if record.is_expired():
                    record.status = ApprovalStatus.TIMEOUT
                    record.resolved_at = datetime.now(timezone.utc)
                    timed_out += 1
                    logger.info(
                        "Approval timed out",
                        approval_id=record.approval_id,
                        session_id=record.session_id,
                    )
        return timed_out


# ===== 辅助函数 =====

def asyncio_lock():
    """创建 asyncio.Lock（延迟导入以提高可测试性）。"""
    import asyncio

    return asyncio.Lock()
