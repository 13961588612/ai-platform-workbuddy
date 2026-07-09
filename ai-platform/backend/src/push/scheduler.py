"""PushScheduler — 基于 APScheduler 的主动推送调度。

使用 APScheduler 的 AsyncIOScheduler 配合 CronTrigger 管理定时推送任务。
支持：
- 从 AgentConfig PushConfig 添加/移除推送调度
- 通过 WecomPusher 执行定时推送
- 从 Redis Streams 处理推送任务（如果可用）
- Agent 配置变更时的调度热重载

与 AgentConfig.push.schedules 条目和
config.py 中的 SCHEDULER_TIMEZONE 设置保持一致。
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timezone
from uuid import uuid4

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import get_settings
from src.push.models import (
    PushMessage,
    PushMessageStatus,
    PushMessageType,
    PushSchedule,
    PushTask,
)
from src.push.wecom_pusher import WecomPusher, get_wecom_pusher
from src.utils.logging import get_logger

logger = get_logger("push.scheduler")


class PushScheduler:
    """
    基于 APScheduler 的推送调度管理器。

    管理定时推送任务的生命周期：
    - start()：启动 APScheduler
    - stop()：停止 APScheduler 并清理
    - add_schedule(schedule)：添加新的推送调度
    - remove_schedule(schedule_id)：移除推送调度
    - list_schedules()：列出所有活跃调度
    - execute_push(schedule_id)：手动触发推送

    定时推送的执行流程：
    1. 渲染标题/内容模板
    2. 创建 PushMessage
    3. 通过 WecomPusher 发送
    4. 记录结果
    """

    def __init__(self) -> None:
        """初始化 PushScheduler。"""
        settings: Settings = get_settings()
        self._scheduler: AsyncIOScheduler = AsyncIOScheduler(
            timezone=settings.SCHEDULER_TIMEZONE,
        )
        self._wecom_pusher: WecomPusher = get_wecom_pusher()
        self._schedules: dict[str, PushSchedule] = {}
        self._is_started: bool = False

    # ===== 生命周期 =====

    async def start(self) -> None:
        """启动 APScheduler。"""
        if self._is_started:
            logger.warning("PushScheduler is already started")
            return

        self._scheduler.start()
        self._is_started = True
        logger.info(
            "PushScheduler started",
            timezone=get_settings().SCHEDULER_TIMEZONE,
        )

    async def stop(self) -> None:
        """停止 APScheduler 并清理资源。"""
        if not self._is_started:
            return

        self._scheduler.shutdown(wait=False)
        self._is_started = False
        await self._wecom_pusher.close()
        logger.info("PushScheduler stopped")

    # ===== 调度管理 =====

    def add_schedule(self, schedule: PushSchedule) -> str:
        """
        添加新的推送调度。

        Args:
            schedule: PushSchedule 定义。

        Returns:
            调度 ID。
        """
        if not schedule.schedule_id:
            schedule.schedule_id = f"push-{uuid4().hex[:12]}"

        if schedule.schedule_id in self._schedules:
            logger.warning(
                "Schedule already exists, updating",
                schedule_id=schedule.schedule_id,
            )
            self.remove_schedule(schedule.schedule_id)

        if not schedule.enabled:
            logger.info(
                "Schedule is disabled, skipping APScheduler registration",
                schedule_id=schedule.schedule_id,
            )
            self._schedules[schedule.schedule_id] = schedule
            return schedule.schedule_id

        # 解析 cron 表达式（5 个字段：分 时 日 月 星期）
        cron_parts: Any = schedule.cron_expression.split()
        if len(cron_parts) != 5:
            logger.error(
                "Invalid cron expression",
                schedule_id=schedule.schedule_id,
                cron=schedule.cron_expression,
            )
            return schedule.schedule_id

        trigger: CronTrigger = CronTrigger(
            minute=cron_parts[0],
            hour=cron_parts[1],
            day=cron_parts[2],
            month=cron_parts[3],
            day_of_week=cron_parts[4],
            timezone=schedule.timezone,
        )

        job: Any = self._scheduler.add_job(
            self._execute_scheduled_push,
            trigger=trigger,
            args=[schedule.schedule_id],
            id=schedule.schedule_id,
            name=schedule.name or schedule.schedule_id,
            replace_existing=True,
        )

        schedule.next_run_at = (
            job.next_run_time.replace(tzinfo=timezone.utc)
            if job.next_run_time
            else None
        )
        self._schedules[schedule.schedule_id] = schedule

        logger.info(
            "Push schedule added",
            schedule_id=schedule.schedule_id,
            name=schedule.name,
            cron=schedule.cron_expression,
            next_run=schedule.next_run_at.isoformat() if schedule.next_run_at else None,
        )
        return schedule.schedule_id

    def remove_schedule(self, schedule_id: str) -> bool:
        """
        移除推送调度。

        Args:
            schedule_id: 要移除的调度 ID。

        Returns:
            如果调度被移除则返回 True，未找到则返回 False。
        """
        if schedule_id not in self._schedules:
            return False

        schedule: Any = self._schedules.pop(schedule_id)
        if schedule.enabled:
            try:
                self._scheduler.remove_job(schedule_id)
            except Exception:
                pass

        logger.info("Push schedule removed", schedule_id=schedule_id)
        return True

    def list_schedules(self) -> list[PushSchedule]:
        """列出所有已注册的调度。"""
        return list(self._schedules.values())

    def get_schedule(self, schedule_id: str) -> PushSchedule | None:
        """按 ID 获取调度。"""
        return self._schedules.get(schedule_id)

    def update_schedule_status(self, schedule_id: str, enabled: bool) -> bool:
        """启用或禁用一个调度。"""
        schedule: Skill | None = self._schedules.get(schedule_id)
        if not schedule:
            return False

        schedule.enabled = enabled
        schedule.updated_at = datetime.now(timezone.utc)

        if enabled:
            self.add_schedule(schedule)
        else:
            try:
                self._scheduler.remove_job(schedule_id)
            except Exception:
                pass

        logger.info(
            "Schedule status updated",
            schedule_id=schedule_id,
            enabled=enabled,
        )
        return True

    # ===== 执行 =====

    async def _execute_scheduled_push(self, schedule_id: str) -> None:
        """
        执行定时推送。

        由 APScheduler 在 cron 触发器触发时调用。
        渲染模板并向目标用户发送推送消息。
        """
        schedule: Skill | None = self._schedules.get(schedule_id)
        if not schedule or not schedule.enabled:
            logger.warning(
                "Scheduled push skipped — schedule not found or disabled",
                schedule_id=schedule_id,
            )
            return

        logger.info(
            "Executing scheduled push",
            schedule_id=schedule_id,
            name=schedule.name,
        )

        # 更新上次运行时间
        schedule.last_run_at = datetime.now(timezone.utc)
        schedule.run_count += 1

        # 确定目标用户
        target_users: Any = schedule.target_users if schedule.target_users else ["@all"]

        # 渲染模板（简单的字符串替换 — 不依赖 Jinja2）
        title: str = self._render_template(schedule.title_template, schedule)
        content: str = self._render_template(schedule.content_template, schedule)

        # 向每个目标用户发送推送
        for user_id in target_users:
            push_msg: PushMessage = PushMessage(
                message_id=f"msg-{uuid4().hex[:12]}",
                agent_id=schedule.agent_id,
                user_id=user_id,
                msg_type=schedule.msg_type,
                title=title,
                content=content,
                status=PushMessageStatus.PENDING,
            )

            try:
                await self._wecom_pusher.send_push_message(push_msg)
                logger.info(
                    "Scheduled push sent",
                    schedule_id=schedule_id,
                    user_id=user_id,
                    status=push_msg.status.value,
                )
            except Exception as exc:
                logger.error(
                    "Scheduled push failed",
                    schedule_id=schedule_id,
                    user_id=user_id,
                    error=str(exc),
                )

    def _render_template(self, template: str, schedule: PushSchedule) -> str:
        """
        使用调度上下文渲染模板字符串。

        简单的变量替换：{agent_id}、{schedule_name}、{date}、{time}
        """
        if not template:
            return ""
        now: Any = datetime.now(timezone.utc)
        return template.format(
            agent_id=schedule.agent_id,
            schedule_name=schedule.name,
            schedule_id=schedule.schedule_id,
            date=now.strftime("%Y-%m-%d"),
            time=now.strftime("%H:%M"),
        )

    # ===== 手动执行 =====

    async def execute_push(self, schedule_id: str) -> dict[str, Any]:
        """
        手动触发定时推送。

        Args:
            schedule_id: 要执行的调度 ID。

        Returns:
            包含状态和详情的结果字典。
        """
        schedule: Skill | None = self._schedules.get(schedule_id)
        if not schedule:
            return {"status": "error", "message": "Schedule not found"}

        await self._execute_scheduled_push(schedule_id)
        return {
            "status": "ok",
            "schedule_id": schedule_id,
            "executed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ===== Agent 配置同步 =====

    def sync_from_agent_config(
        self,
        agent_id: str,
        push_config: dict[str, Any],
    ) -> list[str]:
        """
        从 Agent 的 PushConfig 同步推送调度。

        先移除该 Agent 的现有调度，再从 PushConfig.schedules
        列表中添加新的。

        Args:
            agent_id: Agent ID。
            push_config: PushConfig 字典（来自 AgentConfig.push）。

        Returns:
            已创建的调度 ID 列表。
        """
        # 移除此 Agent 的现有调度
        existing_ids: list[Any] = [
            sid
            for sid, sched in self._schedules.items()
            if sched.agent_id == agent_id
        ]
        for sid in existing_ids:
            self.remove_schedule(sid)

        if not push_config.get("enabled", False):
            return []

        schedules_data: Skill | None = push_config.get("schedules", [])
        created_ids: list[str] = []

        for sched_data in schedules_data:
            schedule: PushSchedule = PushSchedule(
                agent_id=agent_id,
                name=sched_data.get("name", f"Push-{agent_id}"),
                description=sched_data.get("description", ""),
                cron_expression=sched_data.get("cron", "0 9 * * *"),
                timezone=sched_data.get("timezone", get_settings().SCHEDULER_TIMEZONE),
                enabled=sched_data.get("enabled", True),
                target_users=sched_data.get("target_users", []),
                target_departments=sched_data.get("target_departments", []),
                msg_type=PushMessageType(
                    sched_data.get("msg_type", "text")
                ),
                title_template=sched_data.get("title_template", ""),
                content_template=sched_data.get("content_template", ""),
            )
            sid: str = self.add_schedule(schedule)
            created_ids.append(sid)

        return created_ids


# ===== 单例 =====

_push_scheduler: PushScheduler | None = None


def get_push_scheduler() -> PushScheduler:
    """获取单例 PushScheduler 实例。"""
    global _push_scheduler
    if _push_scheduler is None:
        _push_scheduler = PushScheduler()
    return _push_scheduler
