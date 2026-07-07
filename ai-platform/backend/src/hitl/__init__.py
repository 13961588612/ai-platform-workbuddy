"""HITL（Human-in-the-Loop，人机协同）—— 审批请求生命周期管理。

本包提供：
- ApprovalStore：内存（可选 Redis 后端）审批存储
- ApprovalManager：审批流程编排，含超时处理

审批生命周期：
1. Agent 触发 approval.request → ApprovalManager.create_approval()
2. Store 保存审批记录，status=pending
3. 用户通过 API 响应 → ApprovalManager.respond_to_approval()
4. 状态更新为 approved/rejected → Agent 收到通知继续/中止
5. 若在 HITL_APPROVAL_TIMEOUT_SECONDS 内无响应 → status=timeout
"""

from src.hitl.approval import ApprovalManager, get_approval_manager
from src.hitl.store import ApprovalRecord, ApprovalStatus, ApprovalStore

__all__ = [
    "ApprovalManager",
    "get_approval_manager",
    "ApprovalRecord",
    "ApprovalStatus",
    "ApprovalStore",
]
