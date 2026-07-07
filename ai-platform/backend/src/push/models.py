"""Push 消息模型 — 用于主动推送通知的 Pydantic schema。

定义以下数据结构：
- PushMessage：单条推送消息（text/markdown/news）
- WecomAppMessage：企业微信应用消息信封
- PushSchedule：定时推送任务定义（APScheduler cron）
- PushTask：用于后台处理的排队推送任务

这些模型与 Gateway 的 WecomAppMessage.ts（TypeScript）
以及 AgentConfig PushConfig 部分保持一致。
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PushMessageType(str, Enum):
    """推送消息内容的类型。"""

    TEXT = "text"
    MARKDOWN = "markdown"
    NEWS = "news"


class PushMessageStatus(str, Enum):
    """推送消息的生命周期状态。"""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WecomMessageType(str, Enum):
    """企业微信应用消息类型。"""

    TEXT = "text"
    MARKDOWN = "markdown"
    NEWS = "news"
    TEXT_CARD = "textcard"
    MINI_PROGRAM_NOTICE = "miniprogram_notice"
    TEMPLATE_CARD = "template_card"
    BUTTON_INTERACTION = "button_interaction"


class WecomAppMessage(BaseModel):
    """
    企业微信应用消息信封。

    对应 gateway/src/adapters/wecom/WecomAppMessage.ts — Python
    后端构造此消息并通过企业微信 API 发送。

    Attributes:
        msgtype: 消息类型（text/markdown/news/textcard/template_card）
        agentid: 企业微信应用 ID
        touser: 接收者用户 ID（管道分隔，如 "user1|user2"）
        toparty: 接收者部门 ID（管道分隔）
        totag: 接收者标签 ID（管道分隔）
        text: 文本消息体（用于 msgtype=text）
        markdown: Markdown 消息体（用于 msgtype=markdown）
        news: 图文消息体（用于 msgtype=news）
        text_card: 文本卡片消息体（用于 msgtype=textcard）
        template_card: 模板卡片消息体（用于 msgtype=template_card）
        safe: 是否作为安全消息发送（0 或 1）
        enable_id_transp: 启用 ID 转译（0 或 1）
        enable_duplicate_check: 启用重复检查（0 或 1）
        duplicate_check_interval: 重复检查间隔（秒）
    """

    msgtype: WecomMessageType = WecomMessageType.TEXT
    agentid: str = ""
    touser: str = "@all"
    toparty: str = ""
    totag: str = ""
    text: dict[str, str] | None = None
    markdown: dict[str, str] | None = None
    news: dict[str, Any] | None = None
    text_card: dict[str, Any] | None = None
    template_card: dict[str, Any] | None = None
    safe: int = 0
    enable_id_transp: int = 0
    enable_duplicate_check: int = 0
    duplicate_check_interval: int = 1800

    def to_api_dict(self) -> dict[str, Any]:
        """构建企业微信 send_message API 的 API 请求体。"""
        body: dict[str, Any] = {
            "msgtype": self.msgtype.value,
            "agentid": self.agentid,
            "touser": self.touser,
            "safe": self.safe,
            "enable_id_transp": self.enable_id_transp,
            "enable_duplicate_check": self.enable_duplicate_check,
            "duplicate_check_interval": self.duplicate_check_interval,
        }
        if self.toparty:
            body["toparty"] = self.toparty
        if self.totag:
            body["totag"] = self.totag
        if self.msgtype == WecomMessageType.TEXT and self.text:
            body["text"] = self.text
        elif self.msgtype == WecomMessageType.MARKDOWN and self.markdown:
            body["markdown"] = self.markdown
        elif self.msgtype == WecomMessageType.NEWS and self.news:
            body["news"] = self.news
        elif self.msgtype == WecomMessageType.TEXT_CARD and self.text_card:
            body["textcard"] = self.text_card
        elif self.msgtype == WecomMessageType.TEMPLATE_CARD and self.template_card:
            body["template_card"] = self.template_card
        return body


class PushMessage(BaseModel):
    """
    带元数据的单条推送消息。

    这是推送通知的内部表示。
    WecomPusher 将其转换为 WecomAppMessage 并通过
    企业微信 API 发送。
    """

    message_id: str = Field(default="", description="唯一消息 ID")
    agent_id: str = Field(default="", description="触发推送的 Agent")
    user_id: str = Field(default="", description="目标用户 ID")
    session_id: str = Field(default="", description="会话 ID（如适用）")
    msg_type: PushMessageType = Field(
        default=PushMessageType.TEXT, description="消息内容类型"
    )
    title: str = Field(default="", description="消息标题")
    content: str = Field(default="", description="消息内容")
    url: str = Field(default="", description="图文/卡片消息的可选 URL")
    status: PushMessageStatus = Field(
        default=PushMessageStatus.PENDING, description="当前状态"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    sent_at: datetime | None = None
    error: str | None = None
    trace_id: str = Field(default="", description="用于关联的 Trace ID")


class PushSchedule(BaseModel):
    """
    定时推送任务定义。

    使用 APScheduler CronTrigger 格式进行调度。
    与 AgentConfig PushConfig.schedules 条目保持一致。
    """

    schedule_id: str = Field(default="", description="唯一调度 ID")
    agent_id: str = Field(default="", description="此调度的 Agent ID")
    name: str = Field(default="", description="可读的调度名称")
    description: str = Field(default="")
    cron_expression: str = Field(
        default="0 9 * * *", description="Cron 表达式（5 个字段：分 时 日 月 星期）"
    )
    timezone: str = Field(default="Asia/Shanghai", description="调度时区")
    enabled: bool = Field(default=True)
    target_users: list[str] = Field(
        default_factory=list, description="目标用户 ID（空 = 全部）"
    )
    target_departments: list[str] = Field(
        default_factory=list, description="目标部门 ID"
    )
    msg_type: PushMessageType = Field(default=PushMessageType.TEXT)
    title_template: str = Field(default="", description="标题模板（Jinja2）")
    content_template: str = Field(default="", description="内容模板（Jinja2）")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count: int = 0


class PushTask(BaseModel):
    """
    用于后台处理的排队推送任务。

    推送任务被 enqueue 到 Redis Streams 中，由
    PushScheduler 的后台 worker 消费。
    """

    task_id: str = Field(default="", description="唯一任务 ID")
    schedule_id: str = Field(default="", description="源调度 ID")
    agent_id: str = Field(default="", description="Agent ID")
    user_id: str = Field(default="", description="目标用户 ID")
    msg_type: PushMessageType = Field(default=PushMessageType.TEXT)
    title: str = Field(default="")
    content: str = Field(default="")
    url: str = Field(default="")
    status: PushMessageStatus = Field(default=PushMessageStatus.PENDING)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    retry_count: int = 0
    max_retries: int = 3
