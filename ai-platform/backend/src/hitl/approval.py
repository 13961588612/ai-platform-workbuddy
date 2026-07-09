"""ApprovalManager — HITL 审批流程编排。

管理 HITL（人机协同）审批请求的完整生命周期：
1. create_approval()：Agent 请求审批 → 创建记录（pending）
2. respond_to_approval()：用户响应 → 更新记录 → 通知 Agent
3. check_timeouts()：后台任务将超时的审批标记为 timeout
4. send_approval_notification()：通过 WecomPusher 推送审批卡片

Manager 协调以下组件：
- ApprovalStore（持久化层）
- WecomPusher（企业微信通知）
- Agent 运行时（通过 Gateway WebSocket 回调）
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timezone

from src.config import get_settings
from src.hitl.store import ApprovalRecord, ApprovalStatus, ApprovalStore
from src.push.wecom_pusher import WecomPusher, get_wecom_pusher
from src.utils.logging import get_logger

logger = get_logger("hitl.approval")


class ApprovalManager:
    """
    HITL 审批流程管理器。

    编排审批生命周期：
    - 创建来自 Agent 的审批请求
    - 通过企业微信通知用户
    - 处理用户响应（批准/拒绝）
    - 检查超时并标记
    - 将决策结果通知 Agent 运行时

    使用示例：
        manager = get_approval_manager()
        record = await manager.create_approval(
            session_id="sess-123",
            agent_id="finance-agent",
            skill_id="payment.execute",
            user_id="user-456",
            detail={"title": "付款审批", "description": "付款金额: ¥10,000"},
        )
        # 用户通过 API 响应
        await manager.respond_to_approval(
            approval_id=record.approval_id,
            decision="approved",
            comment="同意付款",
            user_id="user-456",
        )
    """

    def __init__(self) -> None:
        """初始化 ApprovalManager。"""
        settings: Settings = get_settings()
        self._store: ApprovalStore = ApprovalStore()
        self._wecom_pusher: WecomPusher = get_wecom_pusher()
        self._default_timeout: int = settings.HITL_APPROVAL_TIMEOUT_SECONDS
        self._max_pending_per_user: int = settings.HITL_MAX_PENDING_PER_USER

    # ===== 创建审批 =====

    async def create_approval(
        self,
        session_id: str,
        agent_id: str,
        skill_id: str,
        user_id: str,
        detail: dict[str, Any],
        timeout_seconds: int | None = None,
        send_notification: bool = True,
    ) -> ApprovalRecord:
        """
        创建一个新的审批请求。

        参数：
            session_id: 触发审批的 Session ID。
            agent_id: Agent ID。
            skill_id: 需要审批的 Skill ID。
            user_id: 需要审批的用户 ID。
            detail: 审批详情字典（标题、描述等）。
            timeout_seconds: 超时秒数（默认：来自配置）。
            send_notification: 是否发送企业微信通知。

        返回：
            创建的 ApprovalRecord。

        抛出：
            RuntimeError：如果用户待审批数量过多。
        """
        # 检查每个用户的最大待审批数量
        pending: list[ApprovalRecord] = await self._store.list_by_user(user_id, ApprovalStatus.PENDING)
        if len(pending) >= self._max_pending_per_user:
            logger.warning(
                "User has too many pending approvals",
                user_id=user_id,
                pending_count=len(pending),
                max=self._max_pending_per_user,
            )
            raise RuntimeError(
                f"User {user_id} has {len(pending)} pending approvals "
                f"(max: {self._max_pending_per_user})"
            )

        timeout: Any = timeout_seconds or self._default_timeout

        record: AgentRuntime = await self._store.create(
            session_id=session_id,
            agent_id=agent_id,
            skill_id=skill_id,
            user_id=user_id,
            detail=detail,
            timeout_seconds=timeout,
        )

        logger.info(
            "Approval request created",
            approval_id=record.approval_id,
            session_id=session_id,
            agent_id=agent_id,
            skill_id=skill_id,
            user_id=user_id,
            timeout=timeout,
        )

        # 通过企业微信发送通知
        if send_notification:
            try:
                await self._send_notification(record)
            except Exception as exc:
                logger.error(
                    "Failed to send approval notification",
                    approval_id=record.approval_id,
                    error=str(exc),
                )
                # 通知失败不影响审批创建

        return record

    # ===== 响应审批 =====

    async def respond_to_approval(
        self,
        approval_id: str,
        decision: str,
        user_id: str,
        comment: str | None = None,
    ) -> ApprovalRecord | None:
        """
        响应一个审批请求。

        参数：
            approval_id: 要响应的审批 ID。
            decision: "approved" 或 "rejected"。
            user_id: 做出决策的用户 ID（用于验证）。
            comment: 可选评论。

        返回：
            更新后的 ApprovalRecord，若未找到则返回 None。

        抛出：
            ValueError：如果决策无效或用户未授权。
            RuntimeError：如果审批已处理完毕。
        """
        if decision not in ("approved", "rejected"):
            raise ValueError(
                f"Invalid decision: {decision}. Must be 'approved' or 'rejected'."
            )

        record: Skill | None = await self._store.get(approval_id)
        if not record:
            return None

        # 验证用户是否有权响应
        if record.user_id != user_id:
            raise ValueError(
                f"User {user_id} is not authorized to respond to approval {approval_id}"
            )

        if record.status != ApprovalStatus.PENDING:
            logger.warning(
                "Approval already resolved",
                approval_id=approval_id,
                current_status=record.status.value,
            )
            return record

        status: Any = (
            ApprovalStatus.APPROVED if decision == "approved" else ApprovalStatus.REJECTED
        )

        updated: ApprovalRecord | None = await self._store.update_status(approval_id, status, comment)
        if not updated:
            return None

        logger.info(
            "Approval responded",
            approval_id=approval_id,
            decision=decision,
            user_id=user_id,
            comment=comment,
        )

        # 通知 Agent 运行时（通过 Gateway WebSocket）
        # 此操作由 push.py API 路由处理，该路由发送 WebSocket
        # 消息回 Gateway，由其转发给 Agent。

        return updated

    # ===== 检查超时 =====

    async def check_timeouts(self) -> int:
        """
        检查过期的待审批记录并标记为超时。

        此方法应由后台任务定期调用（如每 30 秒一次）。

        返回：
            被标记为超时的审批数量。
        """
        timed_out: int = await self._store.cleanup_expired()
        if timed_out > 0:
            logger.info("Approval timeout check completed", timed_out=timed_out)
        return timed_out

    # ===== 查询方法 =====

    async def get_approval(self, approval_id: str) -> ApprovalRecord | None:
        """按 ID 获取审批记录。"""
        return await self._store.get(approval_id)

    async def list_approvals(
        self,
        user_id: str | None = None,
        status: ApprovalStatus | None = None,
        limit: int = 100,
    ) -> list[ApprovalRecord]:
        """列出审批，可按用户和/或状态筛选。"""
        if user_id:
            return await self._store.list_by_user(user_id, status)
        return await self._store.list_all(status, limit)

    async def get_stats(self) -> dict[str, int]:
        """获取审批统计摘要。"""
        return await self._store.get_stats()

    # ===== 通知 =====

    async def _send_notification(self, record: ApprovalRecord) -> None:
        """
        通过企业微信向用户发送审批通知。

        使用 WecomPusher 发送带批准/拒绝按钮的 button_interaction 模板卡片。
        这与 Gateway 的 BotEventMapper approval_card 映射保持一致。
        """
        title: Skill | None = record.detail.get("title", "审批请求")
        description: Skill | None = record.detail.get("description", "请审批此操作")

        await self._wecom_pusher.send_approval_notification(
            user_id=record.user_id,
            title=title,
            description=description,
            approval_id=record.approval_id,
            skill_id=record.skill_id,
            agent_id=record.agent_id,
        )

        logger.info(
            "Approval notification sent",
            approval_id=record.approval_id,
            user_id=record.user_id,
        )

    # ===== 构建审批详情 =====

    @staticmethod
    def build_approval_detail(
        title: str,
        description: str,
        skill_id: str,
        **extra: Any,
    ) -> dict[str, Any]:
        """
        构建审批详情字典。

        此结构与 Gateway 的 BotEventMapper ApprovalDetail
        接口（title、description、skillId、approvalId）保持一致。

        参数：
            title: 卡片标题。
            description: 卡片描述。
            skill_id: Skill ID。
            **extra: 额外的上下文字段。

        返回：
            审批详情字典。
        """
        detail: dict[str, Any] = {
            "title": title,
            "description": description,
            "skill_id": skill_id,
        }
        detail.update(extra)
        return detail


# ===== 单例 =====

_approval_manager: ApprovalManager | None = None


def get_approval_manager() -> ApprovalManager:
    """获取 ApprovalManager 单例实例。"""
    global _approval_manager
    if _approval_manager is None:
        _approval_manager = ApprovalManager()
    return _approval_manager
