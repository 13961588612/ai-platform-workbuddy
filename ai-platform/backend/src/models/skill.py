"""Skill 持久化的 SQLAlchemy ORM 模型。"""

from __future__ import annotations

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SkillModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    Skills 注册表的数据库模型。

    既存储自定义 Skills（由运营人员注册），也存储 MCP 发现的已提升为 Skill 的工具。
    Qdrant 向量索引以 ``skill_id`` 为键，单独存储嵌入向量。
    """

    __tablename__ = "skills"

    # 唯一业务标识符（如 "skill-leave-query"）
    skill_id: Mapped[str] = mapped_column(
        String(128), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # 标签 JSON 数组
    tags: Mapped[list] = mapped_column(JSONB, default=list)

    # Skill 接受的参数的 JSON Schema 描述
    parameters: Mapped[dict] = mapped_column(JSONB, default=dict)

    # 调用此 Skill 所需的权限字符串列表
    required_permissions: Mapped[list] = mapped_column(JSONB, default=list)

    # 处理器引用："mcp:{server}:{tool}" 或 "builtin:{name}" 或 "custom:{module}.{func}"
    handler: Mapped[str] = mapped_column(String(512), nullable=False)

    # 执行超时秒数
    timeout: Mapped[int] = mapped_column(Integer, default=30)

    # 版本号
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")

    # 状态：active | inactive | deprecated
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)

    # 来源：custom | mcp | builtin
    source: Mapped[str] = mapped_column(String(32), default="custom")

    # 排序优先级权重（越大越重要）
    priority: Mapped[float] = mapped_column(Float, default=1.0)

    # 此 Skill 执行前是否需要 HITL 审批
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)

    # 若 source == "mcp" 则为 MCP 服务器名称
    mcp_server: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # 使用统计（由 SkillRanker 更新）
    call_count: Mapped[int] = mapped_column(Integer, default=0)
    last_called_at: Mapped[str | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_dict(self) -> dict:
        """返回可序列化的字典表示。"""
        return {
            "id": self.id,
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": self.tags,
            "parameters": self.parameters,
            "required_permissions": self.required_permissions,
            "handler": self.handler,
            "timeout": self.timeout,
            "version": self.version,
            "status": self.status,
            "source": self.source,
            "priority": self.priority,
            "requires_approval": self.requires_approval,
            "mcp_server": self.mcp_server,
            "call_count": self.call_count,
            "last_called_at": self.last_called_at.isoformat()
            if self.last_called_at
            else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
