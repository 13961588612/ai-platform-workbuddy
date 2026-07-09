"""Auth API 路由 — 开发测试账号登录与 Token 刷新。"""

from __future__ import annotations
from typing import Any


from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from src.api.response import error_response, success
from src.identity.auth import AuthenticationError, AuthService
from src.identity.models import PasswordLoginRequest, WeComOAuthRequest
from src.identity.test_accounts import get_test_account_store
from src.identity.token import TokenError, TokenManager
from src.utils.logging import get_logger

logger = get_logger("api.routes.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求体。"""

    refresh_token: str = Field(..., description="Refresh token")


@router.post("/login")
async def login(req: PasswordLoginRequest) -> dict[str, Any]:
    """用户名密码登录；开发环境支持 test-accounts.yaml 中的测试账号。"""
    store: TestAccountStore = get_test_account_store()

    if not store.is_enabled():
        return error_response(
            1003,
            "Test account login is disabled. Set DEV_TEST_ACCOUNTS_ENABLED=true.",
            status.HTTP_403_FORBIDDEN,
        )

    account: TestAccount | None = store.authenticate(req.username, req.password)
    if account is None:
        logger.warning("Test login failed", username=req.username)
        return error_response(
            1001,
            "Invalid username or password",
            status.HTTP_401_UNAUTHORIZED,
        )

    token_manager: TokenManager = TokenManager()
    tokens: TokenSet = token_manager.create_token_set(
        user_id=account.user_id,
        username=account.username,
        department=account.department,
        roles=account.roles,
        channel=account.channel,
    )

    logger.info("Test account login", username=account.username, user_id=account.user_id)
    return success(
        data={
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": tokens.token_type,
            "expires_in": tokens.expires_in,
            "user": {
                "user_id": account.user_id,
                "username": account.username,
                "display_name": account.display_name or account.username,
                "department": account.department,
                "roles": account.roles,
                "channel": account.channel,
            },
        },
        message="Login successful",
    )


@router.post("/refresh")
async def refresh_token(req: RefreshTokenRequest) -> dict[str, Any]:
    """使用 refresh token 换取新的 access token。"""
    try:
        tokens: TokenSet = TokenManager().refresh_token_set(req.refresh_token)
        return success(
            data={
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": tokens.expires_in,
            },
            message="Token refreshed",
        )
    except TokenError as exc:
        return error_response(1002, str(exc), status.HTTP_401_UNAUTHORIZED)


@router.post("/wecom/callback")
async def wecom_callback(req: WeComOAuthRequest) -> dict[str, Any]:
    """企业微信 OAuth2 回调（需配置真实 WeCom 凭证）。"""
    auth_service: AuthService = AuthService()
    try:
        tokens: TokenSet = await auth_service.verify_wecom_user(req)
        return success(
            data={
                "access_token": tokens.access_token,
                "refresh_token": tokens.refresh_token,
                "token_type": tokens.token_type,
                "expires_in": tokens.expires_in,
            },
            message="WeCom login successful",
        )
    except AuthenticationError as exc:
        return error_response(1001, str(exc), status.HTTP_401_UNAUTHORIZED)
    except Exception as exc:
        logger.error("WeCom callback failed", error=str(exc))
        return error_response(5000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
