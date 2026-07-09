"""Agent 记忆子系统的 Pydantic schema 和枚举。

定义了 MemoryManager、MemoryInjector 和 REST API 层共用的数据契约。
这些是纯数据模型——持久化由 ``src.models.agent_memory`` 中的
SQLAlchemy ORM 处理。
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """动态记忆条目的分类。

    - ``context``    — 对话中发现的上下文事实
    - ``preference`` — 用户偏好（语言、风格、格式等）
    - ``decision``   — 用户做出或确认的重要决策
    - ``summary``    — 对话/会话摘要
    - ``fact``       — 值得记住的独立事实知识
    """

    CONTEXT = "context"
    PREFERENCE = "preference"
    DECISION = "decision"
    SUMMARY = "summary"
    FACT = "fact"


class MemoryEntry(BaseModel):
    """单条动态记忆记录（对应 ``agent_memory`` 表）。"""

    id: str = Field(default="", description="UUID 主键（字符串形式）")
    agent_name: str = Field(..., description="Agent 标识符")
    session_id: str | None = Field(
        default=None,
        description="会话范围记忆的 session ID；None = 用户级",
    )
    user_id: str | None = Field(
        default=None,
        description="用户 ID；None = agent 级（跨用户）记忆",
    )
    memory_type: MemoryType = Field(
        default=MemoryType.CONTEXT,
        description="记忆分类",
    )
    content: str = Field(..., description="记忆内容文本")
    importance: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Importance 评分 0.0–1.0"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="额外元数据（JSONB）"
    )
    expires_at: datetime | None = Field(
        default=None, description="过期时间戳；None = 永不过期"
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def is_user_level(self) -> bool:
        """此记忆是否为用户级（session_id 为 None）。"""
        return self.session_id is None

    @property
    def scope(self) -> str:
        """Qdrant payload scope 标签：``user`` 或 ``session``。"""
        return "user" if self.is_user_level else "session"


class MemorySearchResult(BaseModel):
    """语义检索返回的记忆条目，附带相关性分数。"""

    entry: MemoryEntry = Field(..., description="记忆记录")
    similarity: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Qdrant 余弦相似度"
    )
    composite_score: float = Field(
        default=0.0, description="importance × similarity × recency 因子"
    )


class ExtractedMemory(BaseModel):
    """after_agent_run 期间由 LLM 提取的记忆点。

    只有 ``importance > 0.3`` 的条目会被持久化到动态记忆。
    """

    memory_type: MemoryType = Field(
        default=MemoryType.CONTEXT, description="提取的记忆分类"
    )
    content: str = Field(..., description="提取的记忆内容")
    importance: float = Field(
        default=0.5, ge=0.0, le=1.0, description="LLM 分配的 importance"
    )
