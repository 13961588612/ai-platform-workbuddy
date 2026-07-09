"""
JWT Token 管理 — HS256 签名 / 验证 / 刷新。

Access token 有效期为 8 小时；refresh token 有效期为 7 天。
Token 使用 settings 中的 ``JWT_SECRET_KEY`` 进行签名。
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timedelta, timezone

import jwt
import structlog

from src.config import get_settings
from src.identity.models import TokenPayload, TokenSet

logger = structlog.get_logger(__name__)

_ALGORITHM = "HS256"
_ACCESS_TOKEN_TYPE = "access"
_REFRESH_TOKEN_TYPE = "refresh"


class TokenError(Exception):
    """当 token 无效、过期或类型不正确时抛出。"""


class TokenManager:
    """管理 JWT 创建、验证和刷新。"""

    def __init__(self) -> None:
        """从应用配置加载 JWT 密钥与过期时间。"""
        self._settings = get_settings()
        self._secret = self._settings.JWT_SECRET_KEY
        self._algorithm = _ALGORITHM
        self._access_expire = timedelta(
            minutes=self._settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        )
        self._refresh_expire = timedelta(
            days=self._settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
        )

    def create_token_set(
        self,
        user_id: str,
        username: str,
        department: str = "",
        roles: list[str] | None = None,
        channel: str = "wecom_h5",
        agent_id: str | None = None,
    ) -> TokenSet:
        """为用户创建新的 access + refresh token 对。"""
        now: Any = datetime.now(timezone.utc)
        roles: Any = roles or []

        access_payload: dict[str, Any] = {
            "user_id": user_id,
            "userId": user_id,
            "username": username,
            "department": department,
            "roles": roles,
            "channel": channel,
            "agent_id": agent_id,
            "iss": "ai-platform",
            "iat": int(now.timestamp()),
            "exp": int((now + self._access_expire).timestamp()),
            "type": _ACCESS_TOKEN_TYPE,
        }
        refresh_payload: dict[str, Any] = {
            "user_id": user_id,
            "username": username,
            "type": _REFRESH_TOKEN_TYPE,
            "iss": "ai-platform",
            "iat": int(now.timestamp()),
            "exp": int((now + self._refresh_expire).timestamp()),
        }

        access_token: bytes = jwt.encode(access_payload, self._secret, algorithm=self._algorithm)
        refresh_token: bytes = jwt.encode(refresh_payload, self._secret, algorithm=self._algorithm)

        logger.info("Token set created", user_id=user_id)
        return TokenSet(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=int(self._access_expire.total_seconds()),
        )

    def verify_access_token(self, token: str) -> TokenPayload:
        """验证 access token 并返回其声明。

        Raises:
            TokenError: 如果 token 无效、过期或不是 access token。
        """
        payload: dict[str, Any] = self._decode(token)
        if payload.get("type") != _ACCESS_TOKEN_TYPE:
            raise TokenError("Expected access token, got different type")
        return TokenPayload(
            user_id=payload["user_id"],
            username=payload["username"],
            department=payload.get("department", ""),
            roles=payload.get("roles", []),
            channel=payload.get("channel", "wecom_h5"),
            agent_id=payload.get("agent_id"),
            iss=payload.get("iss", "ai-platform"),
            exp=payload.get("exp", 0),
            iat=payload.get("iat", 0),
        )

    def verify_refresh_token(self, token: str) -> dict[str, Any]:
        """验证 refresh token 并返回其原始载荷。

        Raises:
            TokenError: 如果 token 无效、过期或不是 refresh token。
        """
        payload: dict[str, Any] = self._decode(token)
        if payload.get("type") != _REFRESH_TOKEN_TYPE:
            raise TokenError("Expected refresh token, got different type")
        return payload

    def refresh_token_set(self, refresh_token: str) -> TokenSet:
        """从有效的 refresh token 创建新的 TokenSet。"""
        payload: dict[str, Any] = self.verify_refresh_token(refresh_token)
        # 注意：新的 TokenSet 具有相同的用户信息但新的过期时间
        # 角色和部门不在 refresh token 中；如果需要，
        # 调用方必须重新获取它们。
        return self.create_token_set(
            user_id=payload["user_id"],
            username=payload["username"],
        )

    def _decode(self, token: str) -> dict[str, Any]:
        """解码并验证 JWT，失败时抛出 TokenError。"""
        try:
            return jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                issuer="ai-platform",
            )
        except jwt.ExpiredSignatureError as exc:
            raise TokenError("Token has expired") from exc
        except jwt.InvalidTokenError as exc:
            raise TokenError(f"Invalid token: {exc}") from exc
