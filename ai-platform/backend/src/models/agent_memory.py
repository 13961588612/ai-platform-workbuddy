"""``agent_memory`` 表的 SQLAlchemy ORM 模型。

存储动态 Agent 记忆，支持两种作用域：
- **用户级**（``session_id IS NULL``）：对给定 agent + user 的所有渠道/Session 共享。
- **Session 级**（``session_id`` 已填充）：严格隔离到单个 Session。

Qdrant 的 ``agent_memory_index`` 集合存储嵌入向量，
以相同的 UUID ``id`` 作为键，payload 镜像可筛选的列。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class AgentMemory(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    动态 Agent 记忆的 ORM 模型。

    列说明：
        id          — UUID 主键（来自 UUIDPrimaryKeyMixin）
        agent_name  — Agent 标识符（如 ``hr-assistant``）
        session_id  — Session ID 或 NULL（用户级记忆）
        user_id     — User ID 或 NULL（Agent 级记忆）
        memory_type — context | preference | decision | summary | fact
        content     — 记忆文本内容
        importance  — 重要性评分 0.0–1.0
        metadata    — 额外的 JSONB 元数据
        expires_at  — 过期时间戳（NULL = 永不过期）
        created_at  — 创建时间戳（来自 TimestampMixin）
        updated_at  — 最后更新时间戳（来自 TimestampMixin）
    """

    __tablename__ = "agent_memory"

    agent_name: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    session_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    memory_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[float] = mapped_column(
        Float, default=0.5, nullable=False
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ----- 索引 -----
    # 用户级检索的复合索引：(agent_name, user_id, session_id IS NULL)
    __table_args__ = (
        Index(
            "ix_agent_memory_user_level",
            "agent_name",
            "user_id",
            postgresql_where="session_id IS NULL",
        ),
        Index(
            "ix_agent_memory_session_level",
            "agent_name",
            "user_id",
            "session_id",
        ),
        Index("ix_agent_memory_expires_at", "expires_at"),
    )

    def to_dict(self) -> dict:
        """返回可序列化的字典表示。"""
        return {
            "id": self.id,
            "agent_name": self.agent_name,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "memory_type": self.memory_type,
            "content": self.content,
            "importance": self.importance,
            "metadata": self.metadata_,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
