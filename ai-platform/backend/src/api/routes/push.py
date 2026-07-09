"""Push & HITL API 路由 — 主动推送管理和审批端点。

端点：
- GET    /api/v1/push/approvals               — 列出审批
- GET    /api/v1/push/approvals/{id}           — 获取审批详情
- POST   /api/v1/push/approvals/{id}/respond   — 响应审批
- GET    /api/v1/push/approvals/stats          — 审批统计
- GET    /api/v1/push/schedules                — 列出推送计划
- POST   /api/v1/push/schedules/{id}/execute   — 手动触发推送
- POST   /api/v1/push/send                     — 发送直接推送消息
- GET    /api/v1/push/health                   — 推送服务健康检查
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.api.deps import get_current_user, get_trace_id
from src.api.response import error_response, success, success_response
from src.config import get_settings
from src.hitl.approval import get_approval_manager
from src.hitl.store import ApprovalStatus
from src.push.models import PushMessage, PushMessageStatus, PushMessageType
from src.push.scheduler import get_push_scheduler
from src.push.wecom_pusher import get_wecom_pusher
from src.utils.logging import get_logger

logger = get_logger("api.routes.push")

router = APIRouter(prefix="/push", tags=["push"])


# ===== 请求模型 =====


class RespondApprovalRequest(BaseModel):
    """响应审批的请求体。"""

    decision: str = Field(..., description="决策：'approved' 或 'rejected'")
    comment: str = Field(default="", description="可选备注")


class SendPushRequest(BaseModel):
    """发送直接推送消息的请求体。"""

    user_id: str = Field(..., description="目标用户 ID")
    msg_type: str = Field(default="text", description="消息类型：text/markdown/news")
    title: str = Field(default="", description="消息标题")
    content: str = Field(..., description="消息内容")
    url: str = Field(default="", description="图文消息的可选 URL")
    agent_id: str = Field(default="", description="用于追踪的 Agent ID")


class CreateScheduleRequest(BaseModel):
    """创建推送计划的请求体。"""

    agent_id: str = Field(..., description="Agent ID")
    name: str = Field(..., description="计划名称")
    description: str = Field(default="")
    cron_expression: str = Field(default="0 9 * * *", description="Cron 表达式（5 字段）")
    timezone: str = Field(default="Asia/Shanghai")
    enabled: bool = Field(default=True)
    target_users: list[str] = Field(default_factory=list)
    msg_type: str = Field(default="text")
    title_template: str = Field(default="")
    content_template: str = Field(default="")


# ===== 响应模型 =====


class ApprovalResponse(BaseModel):
    """API 响应中的审批记录（前端使用 camelCase）。"""

    approvalId: str
    sessionId: str
    agentId: str
    skillId: str
    userId: str
    status: str
    detail: dict[str, Any]
    createdAt: str
    resolvedAt: str | None = None
    comment: str | None = None
    timeoutSeconds: int = 300


# ===== 辅助函数 =====


def _to_approval_response(record: Any) -> dict[str, Any]:
    """将 ApprovalRecord 转换为 camelCase 的 API 响应字典。"""
    return {
        "approvalId": record.approval_id,
        "sessionId": record.session_id,
        "agentId": record.agent_id,
        "skillId": record.skill_id,
        "userId": record.user_id,
        "status": record.status.value if hasattr(record.status, "value") else str(record.status),
        "detail": record.detail,
        "createdAt": record.created_at.isoformat() if record.created_at else "",
        "resolvedAt": record.resolved_at.isoformat() if record.resolved_at else None,
        "comment": record.comment,
        "timeoutSeconds": record.timeout_seconds,
    }


# ===== 审批端点 =====


@router.get("/approvals")
async def list_approvals(
    status_filter: str | None = Query(None, alias="status"),
    user_id: str | None = Query(None, alias="user_id"),
    limit: int = Query(100, ge=1, le=500),
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """列出审批请求，可按状态和/或用户筛选。"""
    try:
        manager: ApprovalManager = get_approval_manager()
        approval_status: ApprovalStatus | None = None
        if status_filter:
            try:
                approval_status: ApprovalStatus = ApprovalStatus(status_filter)
            except ValueError:
                return error_response(
                    code=400,
                    message=f"Invalid status: {status_filter}",
                    trace_id=trace_id,
                )

        # 如果未指定 user_id，使用当前用户（适用于非管理员用户）
        target_user_id: Any = user_id or user.get("user_id", "")

        records: dict[str, Any] = await manager.list_approvals(
            user_id=target_user_id if target_user_id else None,
            status=approval_status,
            limit=limit,
        )

        data: list[Any] = [_to_approval_response(r) for r in records]
        return success(data, trace_id=trace_id)
    except Exception as exc:
        logger.error("Failed to list approvals", error=str(exc))
        return error_response(
            code=500,
            message=f"Failed to list approvals: {exc}",
            trace_id=trace_id,
        )


@router.get("/approvals/stats")
async def get_approval_stats(
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """获取审批统计摘要。"""
    try:
        manager: ApprovalManager = get_approval_manager()
        stats: RouteStats = await manager.get_stats()
        return success(stats, trace_id=trace_id)
    except Exception as exc:
        logger.error("Failed to get approval stats", error=str(exc))
        return error_response(
            code=500,
            message=f"Failed to get stats: {exc}",
            trace_id=trace_id,
        )


@router.get("/approvals/{approval_id}")
async def get_approval(
    approval_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """按 ID 获取单个审批。"""
    try:
        manager: ApprovalManager = get_approval_manager()
        record: dict[str, Any] = await manager.get_approval(approval_id)
        if not record:
            return error_response(
                code=404,
                message=f"Approval not found: {approval_id}",
                trace_id=trace_id,
            )
        return success(_to_approval_response(record), trace_id=trace_id)
    except Exception as exc:
        logger.error("Failed to get approval", error=str(exc), approval_id=approval_id)
        return error_response(
            code=500,
            message=f"Failed to get approval: {exc}",
            trace_id=trace_id,
        )


@router.post("/approvals/{approval_id}/respond")
async def respond_to_approval(
    approval_id: str,
    req: RespondApprovalRequest,
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """响应审批请求（批准/拒绝）。"""
    try:
        manager: ApprovalManager = get_approval_manager()
        current_user_id: Skill | None = user.get("user_id", "")

        record: dict[str, Any] = await manager.respond_to_approval(
            approval_id=approval_id,
            decision=req.decision,
            user_id=current_user_id,
            comment=req.comment or None,
        )

        if not record:
            return error_response(
                code=404,
                message=f"Approval not found: {approval_id}",
                trace_id=trace_id,
            )

        logger.info(
            "Approval response received",
            approval_id=approval_id,
            decision=req.decision,
            user_id=current_user_id,
        )

        return success(_to_approval_response(record), trace_id=trace_id)
    except ValueError as exc:
        return error_response(
            code=400,
            message=str(exc),
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error(
            "Failed to respond to approval",
            error=str(exc),
            approval_id=approval_id,
        )
        return error_response(
            code=500,
            message=f"Failed to respond: {exc}",
            trace_id=trace_id,
        )


# ===== 推送计划端点 =====


@router.get("/schedules")
async def list_schedules(
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """列出所有推送计划。"""
    try:
        scheduler: PushScheduler = get_push_scheduler()
        schedules: dict[str, Any] = scheduler.list_schedules()
        data: list[dict[str, Any]] = [
            {
                "scheduleId": s.schedule_id,
                "agentId": s.agent_id,
                "name": s.name,
                "description": s.description,
                "cronExpression": s.cron_expression,
                "timezone": s.timezone,
                "enabled": s.enabled,
                "targetUsers": s.target_users,
                "msgType": s.msg_type.value,
                "lastRunAt": s.last_run_at.isoformat() if s.last_run_at else None,
                "nextRunAt": s.next_run_at.isoformat() if s.next_run_at else None,
                "runCount": s.run_count,
            }
            for s in schedules
        ]
        return success(data, trace_id=trace_id)
    except Exception as exc:
        logger.error("Failed to list push schedules", error=str(exc))
        return error_response(
            code=500,
            message=f"Failed to list schedules: {exc}",
            trace_id=trace_id,
        )


@router.post("/schedules")
async def create_schedule(
    req: CreateScheduleRequest,
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """创建新的推送计划。"""
    try:
        from src.push.models import PushSchedule

        scheduler: PushScheduler = get_push_scheduler()
        schedule: PushSchedule = PushSchedule(
            agent_id=req.agent_id,
            name=req.name,
            description=req.description,
            cron_expression=req.cron_expression,
            timezone=req.timezone,
            enabled=req.enabled,
            target_users=req.target_users,
            msg_type=PushMessageType(req.msg_type),
            title_template=req.title_template,
            content_template=req.content_template,
        )
        schedule_id: str = scheduler.add_schedule(schedule)
        return success(
            {"scheduleId": schedule_id, "status": "created"},
            message="Schedule created successfully",
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("Failed to create push schedule", error=str(exc))
        return error_response(
            code=500,
            message=f"Failed to create schedule: {exc}",
            trace_id=trace_id,
        )


@router.delete("/schedules/{schedule_id}")
async def delete_schedule(
    schedule_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """删除推送计划。"""
    try:
        scheduler: PushScheduler = get_push_scheduler()
        removed: bool = scheduler.remove_schedule(schedule_id)
        if not removed:
            return error_response(
                code=404,
                message=f"Schedule not found: {schedule_id}",
                trace_id=trace_id,
            )
        return success(
            {"scheduleId": schedule_id, "status": "deleted"},
            message="Schedule deleted successfully",
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("Failed to delete push schedule", error=str(exc))
        return error_response(
            code=500,
            message=f"Failed to delete schedule: {exc}",
            trace_id=trace_id,
        )


@router.post("/schedules/{schedule_id}/execute")
async def execute_schedule(
    schedule_id: str,
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """手动触发定时推送。"""
    try:
        scheduler: PushScheduler = get_push_scheduler()
        result: dict[str, Any] = await scheduler.execute_push(schedule_id)
        return success(result, trace_id=trace_id)
    except Exception as exc:
        logger.error("Failed to execute push schedule", error=str(exc))
        return error_response(
            code=500,
            message=f"Failed to execute schedule: {exc}",
            trace_id=trace_id,
        )


# ===== 直接推送端点 =====


@router.post("/send")
async def send_push_message(
    req: SendPushRequest,
    user: dict[str, Any] = Depends(get_current_user),
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """通过企业微信向用户发送直接推送消息。"""
    try:
        pusher: WecomPusher = get_wecom_pusher()
        push_msg: PushMessage = PushMessage(
            agent_id=req.agent_id,
            user_id=req.user_id,
            msg_type=PushMessageType(req.msg_type),
            title=req.title,
            content=req.content,
            url=req.url,
            status=PushMessageStatus.PENDING,
            trace_id=trace_id,
        )
        result: dict[str, Any] = await pusher.send_push_message(push_msg)
        return success(
            {
                "status": result.status.value,
                "sentAt": result.sent_at.isoformat() if result.sent_at else None,
                "error": result.error,
            },
            message="Push message sent" if result.status == PushMessageStatus.SENT else "Push message failed",
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("Failed to send push message", error=str(exc))
        return error_response(
            code=500,
            message=f"Failed to send push: {exc}",
            trace_id=trace_id,
        )


# ===== 健康检查 =====


@router.get("/health")
async def push_health_check(
    trace_id: str = Depends(get_trace_id),
) -> dict[str, Any]:
    """推送服务健康检查。"""
    try:
        scheduler: PushScheduler = get_push_scheduler()
        schedules: dict[str, Any] = scheduler.list_schedules()
        manager: ApprovalManager = get_approval_manager()
        stats: RouteStats = await manager.get_stats()

        return success(
            {
                "status": "ok",
                "scheduler_started": scheduler._is_started,
                "active_schedules": len(schedules),
                "pending_approvals": stats.get("pending", 0),
                "total_approvals": stats.get("total", 0),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("Push health check failed", error=str(exc))
        return error_response(
            code=500,
            message=f"Health check failed: {exc}",
            trace_id=trace_id,
        )
