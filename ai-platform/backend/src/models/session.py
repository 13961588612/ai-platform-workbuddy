"""Session 和 Message 持久化的 SQLAlchemy ORM 模型。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SessionModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    聊天 Session 的数据库模型。

    Session 表示用户与 Agent 之间通过特定渠道（web、wecom_h5、wecom_bot）
    进行的对话。Session 状态存储在 Redis 中以实现快速访问，PostgreSQL 作为持久化备份。
    """

    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)

    # Session 状态：active、idle、closed
    state: Mapped[str] = mapped_column(String(32), default="active")

    # 此 Session 使用的运行时类型
    runtime_type: Mapped[str] = mapped_column(String(32), default="openharness")

    # Session 元数据（JSON）
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # 空闲追踪
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> dict:
        """返回模型的字典表示。"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "state": self.state,
            "runtime_type": self.runtime_type,
            "metadata": self.metadata_,
            "last_activity_at": self.last_activity_at.isoformat() if self.last_activity_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class MessageModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Session 中单条消息的数据库模型。"""

    __tablename__ = "messages"

    session_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("sessions.session_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)  # user、assistant、system、tool
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)

    # 此消息的 Token 用量（仅 assistant 消息）
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)

    def to_dict(self) -> dict:
        """返回模型的字典表示。"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata_,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class RouteLogModel(Base, UUIDPrimaryKeyMixin):
    """AgentRouter 路由决策日志的数据库模型。"""

    __tablename__ = "route_logs"

    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    matched_agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategy_used: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )


class TokenUsageModel(Base, UUIDPrimaryKeyMixin):
    """LLM Token 用量追踪的数据库模型。"""

    __tablename__ = "token_usage"

    session_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
