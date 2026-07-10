"""Agent 配置持久化的 SQLAlchemy ORM 模型。"""

from __future__ import annotations


from sqlalchemy import Boolean, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class AgentConfigModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    Agent 配置存储的数据库模型。

    在 DATABASE 和 DUAL 配置模式下使用。在 FILE_SYSTEM 模式下，
    此表通过 ConfigSync 保持同步，但不作为数据源。
    """

    __tablename__ = "agent_configs"

    agent_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[str] = mapped_column(String(32), default="1.0.0")

    # 完整的 YAML 配置，序列化为 JSON 文本
    config_yaml: Mapped[str] = mapped_column(Text, nullable=False)

    # AgentRouter 语义搜索用的元数据
    metadata_yaml: Mapped[str] = mapped_column(Text, default="")

    # 路由配置
    routing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    routing_priority: Mapped[int] = mapped_column(Integer, default=10)
    routing_keywords: Mapped[str] = mapped_column(Text, default="[]")  # JSON 数组

    # 运行时类型
    runtime_type: Mapped[str] = mapped_column(String(32), default="openharness")

    # Agent 状态
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_dict(self) -> dict:
        """返回模型的字典表示。"""
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "display_name": self.display_name,
            "description": self.description,
            "version": self.version,
            "config_yaml": self.config_yaml,
            "metadata_yaml": self.metadata_yaml,
            "routing_enabled": self.routing_enabled,
            "routing_priority": self.routing_priority,
            "routing_keywords": self.routing_keywords,
            "runtime_type": self.runtime_type,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
