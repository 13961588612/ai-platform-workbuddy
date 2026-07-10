"""
身份与访问管理子系统的 Pydantic 模型。

定义 UserContext（传递给 SkillRanker /
PermissionEngine 的运行时内存表示）、Role、Department 以及各种请求/响应 DTO。
"""

from __future__ import annotations
from typing import Any


from pydantic import BaseModel, Field


class UserContext(BaseModel):
    """权限引擎使用的轻量级运行时用户上下文。

    这不是数据库模型 — 它是一个非规范化的投影，
    仅包含权限检查和 Skill
    排序所需的字段。
    """

    user_id: str
    username: str
    display_name: str = ""
    department: str = ""
    dept_id: str | None = None
    roles: list[str] = Field(default_factory=list)  # role_ids
    channel: str = "wecom_h5"
    # 此用户可以访问的 Skill 分类（角色 + 部门的并集）
    allowed_categories: list[str] = Field(default_factory=list)
    # Skill 级别的覆盖
    skill_allow_list: list[str] = Field(default_factory=list)
    skill_deny_list: list[str] = Field(default_factory=list)
    # 用户是否可以批准敏感操作
    can_approve: bool = False
    profile: dict[str, Any] = Field(default_factory=dict)


class DepartmentInfo(BaseModel):
    """部门数据的 Pydantic schema。"""

    dept_id: str
    name: str
    parent_id: str | None = None
    allowed_categories: list[str] = Field(default_factory=list)
    denied_categories: list[str] = Field(default_factory=list)
    is_active: bool = True


class RoleInfo(BaseModel):
    """角色数据的 Pydantic schema。"""

    role_id: str
    name: str
    description: str = ""
    allowed_categories: list[str] = Field(default_factory=list)
    skill_allow_list: list[str] = Field(default_factory=list)
    skill_deny_list: list[str] = Field(default_factory=list)
    can_approve: bool = False
    is_active: bool = True


class TokenPayload(BaseModel):
    """JWT token 载荷（声明）。"""

    user_id: str
    username: str
    department: str = ""
    roles: list[str] = Field(default_factory=list)
    channel: str = "wecom_h5"
    agent_id: str | None = None
    iss: str = "ai-platform"
    exp: int = 0
    iat: int = 0


class TokenSet(BaseModel):
    """access + refresh token 对。"""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 28800  # 8 小时（秒）


class WeComOAuthRequest(BaseModel):
    """企业微信 OAuth2 回调的请求体。"""

    code: str
    state: str = ""


class PasswordLoginRequest(BaseModel):
    """本地密码登录的请求体。"""

    username: str
    password: str


class CredentialMapping(BaseModel):
    """将平台用户映射到业务系统账号。"""

    system_type: str  # finance | retail | department_store | hr | property | crm | valuecard
    system_account: str
    credential: dict[str, Any] = Field(default_factory=dict)  # 明文，加密前
    is_active: bool = True
