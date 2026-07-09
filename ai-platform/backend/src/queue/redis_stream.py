"""Redis Streams 生产/消费 — 与 Gateway redisStream.ts 字段对齐。"""

from __future__ import annotations
from typing import Any

import json
import os
from dataclasses import dataclass

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from src.config import get_settings
from src.runtime.events import AgentEvent
from src.utils.logging import get_logger

logger = get_logger("queue.redis_stream")

AGENT_EVENTS_STREAM = "stream:agent:events"
CONSUMER_GROUP = "agent-core-group"
MAX_STREAM_LENGTH = 10_000
BLOCK_MS = 5000

# Backend 会话渠道 → Gateway EventTransformer 渠道
GATEWAY_CHANNEL_MAP: dict[str, str] = {
    "web": "h5",
    "h5": "h5",
    "wecom_h5": "wecom-h5",
    "wecom-h5": "wecom-h5",
    "wecom_bot": "wecom-bot",
    "wecom-bot": "wecom-bot",
}

DEFAULT_INBOUND_CHANNELS = ("h5", "wecom-h5", "wecom-bot")


@dataclass
class InboundStreamMessage:
    """Gateway 写入 Redis 的入站消息。"""

    id: str
    session_id: str
    user_id: str
    channel: str
    content: str
    message_type: str
    trace_id: str
    timestamp: str
    agent_id: str | None = None
    metadata: dict[str, Any] | None = None


class StreamKeys:
    """Stream 键名规范（与 Gateway StreamProducer 一致）。"""

    @staticmethod
    def agent_inbound(agent_id: str) -> str:
        """返回指定 Agent 的入站 stream 键名。

        Args:
            agent_id: Agent 实例 ID。

        Returns:
            ``stream:agent:{agentId}`` 格式的键名。
        """
        return f"stream:agent:{agent_id}"

    @staticmethod
    def channel_inbound(channel: str) -> str:
        """返回指定渠道的入站 stream 键名。

        Args:
            channel: Gateway 渠道标识（如 ``h5``）。

        Returns:
            ``stream:inbound:{channel}`` 格式的键名。
        """
        return f"stream:inbound:{channel}"

    @staticmethod
    def agent_events() -> str:
        """返回 Agent 出站事件 stream 的全局键名。"""
        return AGENT_EVENTS_STREAM


def parse_inbound_fields(fields: dict[str, str]) -> InboundStreamMessage:
    """将 Redis Stream 字段解析为 InboundStreamMessage。"""
    metadata_raw: Skill | None = fields.get("metadata")
    metadata: Any = json.loads(metadata_raw) if metadata_raw else None
    return InboundStreamMessage(
        id=fields.get("id", ""),
        session_id=fields.get("sessionId", ""),
        user_id=fields.get("userId", ""),
        channel=fields.get("channel", "h5"),
        content=fields.get("content", ""),
        message_type=fields.get("messageType", "text"),
        trace_id=fields.get("traceId", ""),
        timestamp=fields.get("timestamp", ""),
        agent_id=fields.get("agentId"),
        metadata=metadata,
    )


def fields_to_dict(raw_fields: list[Any]) -> dict[str, str]:
    """Redis XREADGROUP flat list → dict。"""
    result: dict[str, str] = {}
    for index in range(0, len(raw_fields), 2):
        key: Any = raw_fields[index]
        value: Any = raw_fields[index + 1] if index + 1 < len(raw_fields) else ""
        if isinstance(key, bytes):
            key: str = key.decode()
        if isinstance(value, bytes):
            value: str = value.decode()
        result[str(key)] = str(value)
    return result


def normalize_stream_fields(raw_fields: Any) -> dict[str, str]:
    """兼容 redis-py 返回 dict 或 flat list。"""
    if isinstance(raw_fields, dict):
        return {str(k): str(v) for k, v in raw_fields.items()}
    return fields_to_dict(list(raw_fields))


def to_gateway_channel(channel: str) -> str:
    """将 Backend 会话渠道名映射为 Gateway EventTransformer 渠道名。

    Args:
        channel: Backend 侧渠道标识。

    Returns:
        Gateway 识别的渠道名；无映射时原样返回。
    """
    return GATEWAY_CHANNEL_MAP.get(channel, channel)


class StreamProducer:
    """将 AgentEvent 写入 stream:agent:events，供 Gateway 消费。"""

    def __init__(self, redis: aioredis.Redis) -> None:
        """绑定 Redis 客户端，用于向出站 stream 写入 Agent 事件。

        Args:
            redis: 已连接的 ``redis.asyncio.Redis`` 实例。
        """
        self._redis = redis

    async def publish_agent_event(
        self,
        *,
        session_id: str,
        user_id: str,
        channel: str,
        agent_id: str,
        trace_id: str,
        event: AgentEvent,
    ) -> str:
        """将 ``AgentEvent`` 序列化后 XADD 到 ``stream:agent:events``。

        Args:
            session_id: 会话 ID。
            user_id: 用户 ID。
            channel: Backend 渠道名（会经 ``to_gateway_channel`` 转换）。
            agent_id: Agent 实例 ID。
            trace_id: 分布式追踪 ID。
            event: 要发布的 Agent 事件。

        Returns:
            Redis 分配的 stream 消息 ID。
        """
        payload: dict[str, Any] = event.model_dump(mode="json", exclude_none=True)
        fields: dict[str, Any] = {
            "sessionId": session_id,
            "userId": user_id,
            "channel": to_gateway_channel(channel),
            "agentId": agent_id,
            "traceId": trace_id,
            "eventType": str(event.type.value),
            "event": json.dumps(payload, ensure_ascii=False),
        }
        message_id: Any = await self._redis.xadd(
            StreamKeys.agent_events(),
            fields,
            maxlen=MAX_STREAM_LENGTH,
            approximate=True,
        )
        logger.debug(
            "Agent event published",
            stream=StreamKeys.agent_events(),
            session_id=session_id,
            event_type=event.type.value,
            message_id=message_id,
        )
        return str(message_id)


async def ensure_consumer_group(redis: aioredis.Redis, stream_key: str) -> None:
    """确保消费者组存在。"""
    try:
        await redis.xgroup_create(stream_key, CONSUMER_GROUP, id="$", mkstream=True)
        logger.info("Consumer group created", stream_key=stream_key, group=CONSUMER_GROUP)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def build_consumer_name() -> str:
    """生成基于当前进程 ID 的 Redis 消费者名称。

    Returns:
        形如 ``agent-core-{pid}`` 的消费者名。
    """
    return f"agent-core-{os.getpid()}"
