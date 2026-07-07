"""用户、角色、部门及凭据映射的 SQLAlchemy ORM 模型。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models.base import Base, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class DepartmentModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """从企业微信同步的组织部门。"""

    __tablename__ = "departments"

    dept_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # 此部门可访问的受约束 Skill 类别（空 = 全部）
    allowed_categories: Mapped[list] = mapped_column(JSONB, default=list)
    # 拒绝访问的 Skill 类别（优先级更高）
    denied_categories: Mapped[list] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dept_id": self.dept_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "allowed_categories": self.allowed_categories,
            "denied_categories": self.denied_categories,
            "is_active": self.is_active,
        }


class RoleModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """RBAC 角色定义。"""

    __tablename__ = "roles"

    role_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    # 此角色授予访问权限的 Skill 类别
    allowed_categories: Mapped[list] = mapped_column(JSONB, default=list)
    # Skill 级别的允许覆盖
    skill_allow_list: Mapped[list] = mapped_column(JSONB, default=list)
    # Skill 级别的拒绝覆盖（优先级高于允许）
    skill_deny_list: Mapped[list] = mapped_column(JSONB, default=list)
    # 此角色是否可以批准敏感操作
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role_id": self.role_id,
            "name": self.name,
            "description": self.description,
            "allowed_categories": self.allowed_categories,
            "skill_allow_list": self.skill_allow_list,
            "skill_deny_list": self.skill_deny_list,
            "can_approve": self.can_approve,
            "is_active": self.is_active,
        }


class UserModel(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """平台用户，从企业微信同步或为本地登录创建。"""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    department: Mapped[str] = mapped_column(String(64), default="", index=True)
    dept_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("departments.dept_id"), nullable=True
    )

    # 逗号分隔或 JSON 列表的 role_ids
    roles: Mapped[list] = mapped_column(JSONB, default=list)

    # 企业微信用户 ID（若已同步）
    wecom_user_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # 本地（非企业微信）登录的密码哈希
    password_hash: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # 首选渠道
    channel: Mapped[str] = mapped_column(String(32), default="wecom_h5")

    # 此特定用户的 Skill 级别覆盖
    skill_allow_list: Mapped[list] = mapped_column(JSONB, default=list)
    skill_deny_list: Mapped[list] = mapped_column(JSONB, default=list)

    # 个人资料元数据
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "username": self.username,
            "display_name": self.display_name,
            "email": self.email,
            "phone": self.phone,
            "department": self.department,
            "dept_id": self.dept_id,
            "roles": self.roles,
            "wecom_user_id": self.wecom_user_id,
            "channel": self.channel,
            "skill_allow_list": self.skill_allow_list,
            "skill_deny_list": self.skill_deny_list,
            "profile": self.profile,
            "is_active": self.is_active,
            "last_login_at": self.last_login_at.isoformat()
            if self.last_login_at
            else None,
        }


class CredentialMappingModel(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """将平台用户映射到业务系统账户，附带加密凭据。"""

    __tablename__ = "credential_mappings"

    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.user_id"), nullable=False, index=True
    )
    system_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )  # finance | retail | department_store | hr | property | crm | valuecard
    system_account: Mapped[str] = mapped_column(String(128), nullable=False)
    encrypted_credential: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "system_type": self.system_type,
            "system_account": self.system_account,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
