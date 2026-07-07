"""会话管理 — 创建、恢复、持久化。

实现 session_id 命名规范（v1.4.1）：
  web-{uuid} / wecom-bot-{uuid} / wecom-h5-{uuid}

会话状态存储在 Redis（主要存储，TTL 24 小时）和 PostgreSQL（备份）中。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from src.config import get_settings
from src.utils.exceptions import SessionNotFoundError
from src.utils.logging import get_logger

logger = get_logger("agent.session")

# 渠道到 session_id 前缀的映射
CHANNEL_PREFIXES: dict[str, str] = {
    "web": "web-",
    "wecom_h5": "wecom-h5-",
    "wecom_bot": "wecom-bot-",
}


class Message:
    """会话中的单条消息。"""

    def __init__(
        self,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id: str = str(uuid.uuid4())
        self.role = role
        self.content = content
        self.metadata = metadata or {}
        self.timestamp = datetime.now(timezone.utc)

    def to_dict(self) -> dict[str, Any]:
        """将消息序列化为字典。"""
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        """从字典反序列化消息。"""
        msg = cls(
            role=data["role"],
            content=data["content"],
            metadata=data.get("metadata", {}),
        )
        msg.id = data.get("id", str(uuid.uuid4()))
        if data.get("timestamp"):
            msg.timestamp = datetime.fromisoformat(data["timestamp"])
        return msg


class Session:
    """表示用户与 Agent 之间的聊天会话。"""

    def __init__(
        self,
        session_id: str,
        agent_id: str,
        user_id: str,
        channel: str,
        runtime_type: str = "openharness",
    ) -> None:
        self.session_id = session_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.channel = channel
        self.runtime_type = runtime_type
        self.messages: list[Message] = []
        self.state: dict[str, Any] = {}
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def add_message(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> Message:
        """向会话中添加一条消息。"""
        msg = Message(role=role, content=content, metadata=metadata)
        self.messages.append(msg)
        self.updated_at = datetime.now(timezone.utc)
        return msg

    def get_messages(self) -> list[dict[str, Any]]:
        """以字典列表形式返回所有消息。"""
        return [msg.to_dict() for msg in self.messages]

    def to_dict(self) -> dict[str, Any]:
        """将会话序列化为字典。"""
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "channel": self.channel,
            "runtime_type": self.runtime_type,
            "messages": self.get_messages(),
            "state": self.state,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class SessionManager:
    """
    管理会话生命周期：创建、恢复、持久化。

    使用 Redis 作为主要存储（TTL 24 小时）以实现快速访问，
    将 PostgreSQL 作为持久化备份用于长期存储。
    """

    def __init__(self) -> None:
        self._redis: aioredis.Redis | None = None
        self._settings = get_settings()
        self._session_ttl = 86400  # 24 小时

    async def _get_redis(self) -> aioredis.Redis:
        """获取或创建 Redis 连接。"""
        if self._redis is None:
            self._redis = aioredis.from_url(
                self._settings.redis_url,
                max_connections=self._settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,
            )
        return self._redis

    def _session_key(self, session_id: str) -> str:
        """会话数据的 Redis key。"""
        return f"session:{session_id}"

    def _agent_binding_key(self, session_id: str) -> str:
        """会话→agent 绑定的 Redis key。"""
        return f"session:{session_id}:agent_binding"

    async def create_session(
        self,
        agent_id: str,
        user_id: str,
        channel: str,
        runtime_type: str = "openharness",
    ) -> Session:
        """
        使用渠道特定的 ID 命名规范创建一个新会话。

        会话 ID 格式：{channel_prefix}{uuid}
        示例：web-{uuid}、wecom-h5-{uuid}、wecom-bot-{uuid}
        """
        prefix = CHANNEL_PREFIXES.get(channel, f"{channel}-")
        session_id = f"{prefix}{uuid.uuid4()}"

        session = Session(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            channel=channel,
            runtime_type=runtime_type,
        )

        # 存储到 Redis
        redis = await self._get_redis()
        await redis.setex(
            self._session_key(session_id),
            self._session_ttl,
            json.dumps(session.to_dict()),
        )

        # 设置 agent 绑定
        await redis.setex(
            self._agent_binding_key(session_id),
            self._session_ttl,
            agent_id,
        )

        logger.info(
            "Session created",
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            channel=channel,
        )
        return session

    async def get_session(self, session_id: str) -> Session:
        """按 ID 从 Redis 中获取会话。"""
        redis = await self._get_redis()
        data = await redis.get(self._session_key(session_id))

        if data is None:
            raise SessionNotFoundError(session_id)

        session_data = json.loads(data)
        session = Session(
            session_id=session_data["session_id"],
            agent_id=session_data["agent_id"],
            user_id=session_data["user_id"],
            channel=session_data["channel"],
            runtime_type=session_data.get("runtime_type", "openharness"),
        )
        session.messages = [
            Message.from_dict(msg) for msg in session_data.get("messages", [])
        ]
        session.state = session_data.get("state", {})
        session.created_at = datetime.fromisoformat(session_data["created_at"])
        session.updated_at = datetime.fromisoformat(session_data["updated_at"])
        return session

    async def save_session(self, session: Session) -> None:
        """将会话持久化到 Redis。"""
        redis = await self._get_redis()
        session.updated_at = datetime.now(timezone.utc)
        await redis.setex(
            self._session_key(session.session_id),
            self._session_ttl,
            json.dumps(session.to_dict()),
        )

    async def get_agent_binding(self, session_id: str) -> str | None:
        """获取会话绑定的 agent ID（用于会话亲和路由）。"""
        redis = await self._get_redis()
        return await redis.get(self._agent_binding_key(session_id))

    async def set_agent_binding(self, session_id: str, agent_id: str) -> None:
        """将会话绑定到一个 agent（用于会话亲和路由）。"""
        redis = await self._get_redis()
        await redis.setex(
            self._agent_binding_key(session_id),
            self._session_ttl,
            agent_id,
        )

    async def close_session(self, session_id: str) -> None:
        """关闭一个会话（从 Redis 中移除）。"""
        redis = await self._get_redis()
        await redis.delete(self._session_key(session_id))
        await redis.delete(self._agent_binding_key(session_id))
        logger.info("Session closed", session_id=session_id)

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> Message:
        """向现有会话添加一条消息并持久化。"""
        session = await self.get_session(session_id)
        msg = session.add_message(role, content, metadata)
        await self.save_session(session)
        return msg


# Singleton instance
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:
    """返回单例 SessionManager 实例。"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
