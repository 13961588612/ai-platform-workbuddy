"""
认证服务 — 企业微信 OAuth2 直连 + 本地 JWT。

流程：
  1. 前端重定向到企业微信 OAuth2 授权 URL。
  2. 企业微信回调提供 ``code``。
  3. 后端通过企业微信 API 用 code 换取 ``userid``：
     a. corpid + corpsecret → access_token（企业微信）
     b. code + access_token → userid
  4. 后端在本地数据库中按 wecom_user_id 查找用户。
  5. 签名并返回 JWT TokenSet。

同时支持独立 H5 渠道的密码登录。
"""

from __future__ import annotations

from typing import Any

import bcrypt
import httpx
import structlog

from src.config import get_settings
from src.identity.models import (
    PasswordLoginRequest,
    TokenSet,
    UserContext,
    WeComOAuthRequest,
)
from src.identity.token import TokenManager

logger = structlog.get_logger(__name__)


class AuthenticationError(Exception):
    """认证失败时抛出。"""


class WeComClient:
    """用于 OAuth2 和组织架构同步的极简企业微信 API 客户端。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._corp_id = self._settings.WECOM_CORP_ID
        self._secret = self._settings.WECOM_SECRET
        self._base_url = "https://qyapi.weixin.qq.com/cgi-bin"
        self._cached_access_token: str = ""
        self._token_expires_at: float = 0.0

    async def get_access_token(self) -> str:
        """使用 corpid + corpsecret 获取企业微信 access_token。

        缓存 token 直到临近过期（过期前 5 分钟）。
        """
        import time

        if self._cached_access_token and time.time() < self._token_expires_at - 300:
            return self._cached_access_token

        url = f"{self._base_url}/gettoken"
        params = {"corpid": self._corp_id, "corpsecret": self._secret}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("errcode", 0) != 0:
            raise AuthenticationError(
                f"WeCom gettoken failed: {data.get('errmsg', 'unknown')}"
            )

        self._cached_access_token = data["access_token"]
        self._token_expires_at = time.time() + data.get("expires_in", 7200)
        return self._cached_access_token

    async def code_to_userid(self, code: str) -> str:
        """将 OAuth2 *code* 兑换为企业微信 userid。"""
        access_token = await self.get_access_token()
        url = f"{self._base_url}/auth/getuserinfo"
        params = {"access_token": access_token, "code": code}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("errcode", 0) != 0:
            raise AuthenticationError(
                f"WeCom getuserinfo failed: {data.get('errmsg', 'unknown')}"
            )

        userid = data.get("userid") or data.get("UserId")
        if not userid:
            raise AuthenticationError("WeCom did not return a userid")
        return userid

    async def get_user_info(self, userid: str) -> dict[str, Any]:
        """从企业微信获取详细的用户信息。"""
        access_token = await self.get_access_token()
        url = f"{self._base_url}/user/get"
        params = {"access_token": access_token, "userid": userid}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("errcode", 0) != 0:
            logger.warning("WeCom get_user_info failed", userid=userid, error=data.get("errmsg"))
            return {}
        return data

    async def get_department_list(self) -> list[dict[str, Any]]:
        """从企业微信获取所有部门列表。"""
        access_token = await self.get_access_token()
        url = f"{self._base_url}/department/list"
        params = {"access_token": access_token}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("errcode", 0) != 0:
            return []
        return data.get("department", [])

    async def get_department_users(self, dept_id: int) -> list[dict[str, Any]]:
        """获取企业微信部门中的所有用户。"""
        access_token = await self.get_access_token()
        url = f"{self._base_url}/user/list"
        params = {"access_token": access_token, "department_id": dept_id, "fetch_child": 0}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        if data.get("errcode", 0) != 0:
            return []
        return data.get("userlist", [])


class AuthService:
    """高级认证门面。"""

    def __init__(
        self,
        token_manager: TokenManager | None = None,
        wecom_client: WeComClient | None = None,
    ) -> None:
        self._token_manager = token_manager or TokenManager()
        self._wecom = wecom_client or WeComClient()
        self._settings = get_settings()

    async def verify_wecom_user(
        self,
        request: WeComOAuthRequest,
        user_lookup: Any | None = None,
    ) -> TokenSet:
        """验证企业微信 OAuth2 回调并签发 JWT TokenSet。

        Args:
            request: 包含 ``code`` 和 ``state`` 的 OAuth2 回调。
            user_lookup: 一个异步可调用对象 ``(wecom_user_id: str) -> UserContext | None``，
                         将企业微信 userid 解析为本地用户。

        Returns:
            包含 access token 和 refresh token 的 :class:`TokenSet`。
        """
        # 1. 用 code 兑换 userid
        wecom_user_id = await self._wecom.code_to_userid(request.code)
        logger.info("WeCom OAuth2 code verified", wecom_user_id=wecom_user_id)

        # 2. 查找本地用户
        if user_lookup:
            user_ctx = await user_lookup(wecom_user_id)
            if user_ctx is None:
                raise AuthenticationError(
                    f"User not found in local database: wecom_user_id={wecom_user_id}"
                )
        else:
            # 回退：创建最小上下文
            user_ctx = UserContext(
                user_id=wecom_user_id,
                username=wecom_user_id,
                display_name=wecom_user_id,
                channel="wecom_h5",
            )

        # 3. 签发 JWT
        return self._token_manager.create_token_set(
            user_id=user_ctx.user_id,
            username=user_ctx.username,
            department=user_ctx.department,
            roles=user_ctx.roles,
            channel=user_ctx.channel,
        )

    async def verify_password(
        self,
        request: PasswordLoginRequest,
        user_lookup: Any | None = None,
    ) -> TokenSet:
        """验证用户名/密码并签发 JWT TokenSet。

        Args:
            request: 用户名和密码。
            user_lookup: 一个异步可调用对象 ``(username: str) -> tuple[UserContext, str] | None``，
                         返回用户上下文和密码哈希。

        Raises:
            AuthenticationError: 如果用户未找到或密码错误。
        """
        if user_lookup is None:
            raise AuthenticationError("No user_lookup provided for password login")

        result = await user_lookup(request.username)
        if result is None:
            raise AuthenticationError("Invalid username or password")

        user_ctx, password_hash = result

        # 验证密码
        if not password_hash:
            raise AuthenticationError("User has no password set")
        if not bcrypt.checkpw(
            request.password.encode("utf-8"),
            password_hash.encode("utf-8") if isinstance(password_hash, str) else password_hash,
        ):
            raise AuthenticationError("Invalid username or password")

        logger.info("Password login successful", username=request.username)
        return self._token_manager.create_token_set(
            user_id=user_ctx.user_id,
            username=user_ctx.username,
            department=user_ctx.department,
            roles=user_ctx.roles,
            channel="h5",
        )

    def verify_token(self, token: str) -> Any:
        """验证 access token 并返回其声明。"""
        return self._token_manager.verify_access_token(token)

    def refresh_tokens(self, refresh_token: str) -> TokenSet:
        """从 refresh token 创建新的 TokenSet。"""
        return self._token_manager.refresh_token_set(refresh_token)

    @staticmethod
    def hash_password(password: str) -> str:
        """使用 bcrypt 对密码进行哈希。"""
        return bcrypt.hashpw(
            password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")
