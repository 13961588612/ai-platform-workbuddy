"""WecomPusher — 企业微信应用消息推送器。

通过企业微信应用消息 API 向用户发送主动推送通知。
支持 text、markdown 和 news 消息类型。

此模块对应 Gateway 的 WecomAppMessage.ts（TypeScript）
实现，为后端主动发起的推送提供 Python 侧等效实现。

API 参考：
- POST https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=ACCESS_TOKEN
- GET  https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=CORPID&corpsecret=SECRET
"""

from __future__ import annotations
from typing import Any

import asyncio
from datetime import datetime, timezone

import httpx
from pydantic import BaseModel

from src.config import get_settings
from src.push.models import (
    PushMessage,
    PushMessageStatus,
    PushMessageType,
    WecomAppMessage,
    WecomMessageType,
)
from src.utils.logging import get_logger

logger = get_logger("push.wecom_pusher")

# ===== 常量 =====

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
TOKEN_CACHE_TTL_SECONDS = 7200  # 企业微信 access token 有效期为 7200 秒


class WecomTokenCache(BaseModel):
    """缓存的企业微信 access token。"""

    access_token: str = ""
    expires_at: datetime = datetime.min.replace(tzinfo=timezone.utc)


class WecomPusher:
    """
    企业微信应用消息推送器。

    通过企业微信 API 向用户发送主动推送通知。
    缓存 access token 并在过期时刷新。

    用法:
        pusher = get_wecom_pusher()
        await pusher.send_text_message("user123", "Hello, World!")
        await pusher.send_markdown_message("user123", "**标题**\n内容")
        await pusher.send_approval_notification(
            "user123", "审批请求", "请审批此操作", "approval-123"
        )
    """

    def __init__(self) -> None:
        """使用 config 中的设置初始化 WecomPusher。"""
        settings: Settings = get_settings()
        self._corp_id: str = settings.WECOM_CORP_ID
        self._agent_id: str = settings.WECOM_AGENT_ID
        self._secret: str = settings.WECOM_SECRET
        self._token_cache: WecomTokenCache = WecomTokenCache()
        self._http_client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    # ===== HTTP 客户端 =====

    def _get_http_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端。"""
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=30.0,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._http_client

    # ===== Access Token =====

    async def _get_access_token(self) -> str:
        """
        获取有效的企业微信 access token。

        缓存 token 并在过期时刷新。
        通过 asyncio.Lock 实现线程安全。
        """
        async with self._lock:
            now: Any = datetime.now(timezone.utc)
            if (
                self._token_cache.access_token
                and self._token_cache.expires_at > now
            ):
                return self._token_cache.access_token

            if not self._corp_id or not self._secret:
                logger.error(
                    "WeChat Work credentials not configured",
                    corp_id=bool(self._corp_id),
                    secret=bool(self._secret),
                )
                raise RuntimeError("WeChat Work credentials not configured")

            url: str = (
                f"{WECOM_API_BASE}/gettoken"
                f"?corpid={self._corp_id}&corpsecret={self._secret}"
            )
            client: httpx.AsyncClient = self._get_http_client()
            try:
                response: Skill | None = await client.get(url)
                response.raise_for_status()
                data: Any = response.json()
            except httpx.HTTPError as exc:
                logger.error("Failed to get WeChat Work access token", error=str(exc))
                raise RuntimeError(f"Failed to get access token: {exc}") from exc

            if data.get("errcode", 0) != 0:
                logger.error(
                    "WeChat Work API returned error",
                    errcode=data.get("errcode"),
                    errmsg=data.get("errmsg"),
                )
                raise RuntimeError(
                    f"WeChat Work API error: {data.get('errcode')} - {data.get('errmsg')}"
                )

            token: Skill | None = data.get("access_token", "")
            expires_in: Skill | None = data.get("expires_in", TOKEN_CACHE_TTL_SECONDS)
            self._token_cache = WecomTokenCache(
                access_token=token,
                expires_at=datetime.now(timezone.utc)
                + timedelta_seconds(expires_in - 300),
            )
            logger.info("WeChat Work access token refreshed", expires_in=expires_in)
            return token

    # ===== 发送消息 =====

    async def _send_message(self, message: WecomAppMessage) -> dict[str, Any]:
        """
        发送企业微信应用消息。

        返回 API 响应字典。
        在 API 错误时抛出 RuntimeError。
        """
        token: str = await self._get_access_token()
        url: str = f"{WECOM_API_BASE}/message/send?access_token={token}"
        body: dict[str, Any] = message.to_api_dict()

        client: httpx.AsyncClient = self._get_http_client()
        try:
            response: Any = await client.post(url, json=body)
            response.raise_for_status()
            data: Any = response.json()
        except httpx.HTTPError as exc:
            logger.error(
                "Failed to send WeChat Work message",
                error=str(exc),
                msgtype=message.msgtype.value,
            )
            raise RuntimeError(f"Failed to send message: {exc}") from exc

        if data.get("errcode", 0) != 0:
            logger.error(
                "WeChat Work message send failed",
                errcode=data.get("errcode"),
                errmsg=data.get("errmsg"),
                msgtype=message.msgtype.value,
            )
            raise RuntimeError(
                f"WeChat Work send error: {data.get('errcode')} - {data.get('errmsg')}"
            )

        logger.info(
            "WeChat Work message sent",
            msgtype=message.msgtype.value,
            touser=message.touser,
        )
        return data

    # ===== 公开 API：文本 =====

    async def send_text_message(
        self,
        user_id: str,
        content: str,
        agent_id: str = "",
    ) -> dict[str, Any]:
        """
        向用户发送文本消息。

        Args:
            user_id: 企业微信用户 ID（或 "@all" 表示所有用户）。
            content: 消息文本内容。
            agent_id: 可选的 Agent ID，用于追踪。

        Returns:
            企业微信 API 响应字典。
        """
        message: WecomAppMessage = WecomAppMessage(
            msgtype=WecomMessageType.TEXT,
            agentid=self._agent_id,
            touser=user_id,
            text={"content": content},
        )
        return await self._send_message(message)

    # ===== 公开 API：Markdown =====

    async def send_markdown_message(
        self,
        user_id: str,
        content: str,
        agent_id: str = "",
    ) -> dict[str, Any]:
        """
        向用户发送 Markdown 消息。

        Args:
            user_id: 企业微信用户 ID（或 "@all" 表示所有用户）。
            content: Markdown 内容。
            agent_id: 可选的 Agent ID，用于追踪。

        Returns:
            企业微信 API 响应字典。
        """
        message: WecomAppMessage = WecomAppMessage(
            msgtype=WecomMessageType.MARKDOWN,
            agentid=self._agent_id,
            touser=user_id,
            markdown={"content": content},
        )
        return await self._send_message(message)

    # ===== 公开 API：图文 =====

    async def send_news_message(
        self,
        user_id: str,
        title: str,
        description: str,
        url: str,
        pic_url: str = "",
        agent_id: str = "",
    ) -> dict[str, Any]:
        """
        向用户发送图文（文章）消息。

        Args:
            user_id: 企业微信用户 ID（或 "@all" 表示所有用户）。
            title: 文章标题。
            description: 文章描述。
            url: 文章 URL。
            pic_url: 可选的缩略图 URL。
            agent_id: 可选的 Agent ID，用于追踪。

        Returns:
            企业微信 API 响应字典。
        """
        article: dict[str, str] = {
            "title": title,
            "description": description,
            "url": url,
        }
        if pic_url:
            article["picurl"] = pic_url

        message: WecomAppMessage = WecomAppMessage(
            msgtype=WecomMessageType.NEWS,
            agentid=self._agent_id,
            touser=user_id,
            news={"articles": [article]},
        )
        return await self._send_message(message)

    # ===== 公开 API：审批通知 =====

    async def send_approval_notification(
        self,
        user_id: str,
        title: str,
        description: str,
        approval_id: str,
        skill_id: str = "",
        agent_id: str = "",
    ) -> dict[str, Any]:
        """
        以模板卡片（button_interaction）形式发送审批通知。

        这对应 Gateway 的 BotEventMapper approval_card 映射，
        将 approval.request 事件映射到 button_interaction 卡片。

        卡片包含两个按钮："同意"（approve）和 "拒绝"（reject）。
        按钮 key 包含 approval_id 和 decision，用于回调处理。

        Args:
            user_id: 企业微信用户 ID。
            title: 卡片标题。
            description: 卡片描述。
            approval_id: 唯一审批请求 ID。
            skill_id: 触发审批的 Skill ID。
            agent_id: 用于追踪的 Agent ID。

        Returns:
            企业微信 API 响应字典。
        """
        template_card: dict[str, Any] = {
            "card_type": "button_interaction",
            "source": {
                "icon_url": "",
                "desc": f"Agent: {agent_id}" if agent_id else "AI 平台",
            },
            "main_title": {"title": title},
            "sub_title_text": description,
            "task_id": approval_id,
            "button_list": [
                {
                    "text": "同意",
                    "style": 1,
                    "key": f"approve:{approval_id}",
                },
                {
                    "text": "拒绝",
                    "style": 2,
                    "key": f"reject:{approval_id}",
                },
            ],
            "task_create_time": int(datetime.now(timezone.utc).timestamp()),
        }
        if skill_id:
            template_card["card_image"] = {
                "url": "",
                "aspect_ratio": "1.0",
            }

        message: WecomAppMessage = WecomAppMessage(
            msgtype=WecomMessageType.BUTTON_INTERACTION,
            agentid=self._agent_id,
            touser=user_id,
            template_card=template_card,
        )
        return await self._send_message(message)

    # ===== 公开 API：推送消息 =====

    async def send_push_message(self, push_msg: PushMessage) -> PushMessage:
        """
        通过适当的企业微信消息类型发送 PushMessage。

        Args:
            push_msg: 要发送的 PushMessage。

        Returns:
            更新后的 PushMessage，包含状态和时间戳。
        """
        push_msg.status = PushMessageStatus.SENDING
        try:
            if push_msg.msg_type == PushMessageType.TEXT:
                await self.send_text_message(
                    push_msg.user_id, push_msg.content, push_msg.agent_id
                )
            elif push_msg.msg_type == PushMessageType.MARKDOWN:
                await self.send_markdown_message(
                    push_msg.user_id, push_msg.content, push_msg.agent_id
                )
            elif push_msg.msg_type == PushMessageType.NEWS:
                await self.send_news_message(
                    push_msg.user_id,
                    push_msg.title,
                    push_msg.content,
                    push_msg.url,
                    agent_id=push_msg.agent_id,
                )
            push_msg.status = PushMessageStatus.SENT
            push_msg.sent_at = datetime.now(timezone.utc)
        except Exception as exc:
            push_msg.status = PushMessageStatus.FAILED
            push_msg.error = str(exc)
            logger.error(
                "Push message failed",
                message_id=push_msg.message_id,
                user_id=push_msg.user_id,
                error=str(exc),
            )
        return push_msg

    # ===== 清理 =====

    async def close(self) -> None:
        """关闭 HTTP 客户端并释放资源。"""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None


# ===== 辅助函数 =====

def timedelta_seconds(seconds: int) -> "datetime":
    """创建指定秒数的 timedelta 并返回 now + delta。"""
    from datetime import timedelta

    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


# ===== 单例 =====

_wecom_pusher: WecomPusher | None = None


def get_wecom_pusher() -> WecomPusher:
    """获取单例 WecomPusher 实例。"""
    global _wecom_pusher
    if _wecom_pusher is None:
        _wecom_pusher = WecomPusher()
    return _wecom_pusher
