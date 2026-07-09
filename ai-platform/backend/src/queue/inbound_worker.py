"""入站 Redis Stream 消费者 — 消费 Gateway 消息并回写 AgentEvent 流。"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.agent.manager import get_agent_manager
from src.agent.session import Message, get_session_manager
from src.config import get_settings
from src.queue.redis_stream import (
    BLOCK_MS,
    CONSUMER_GROUP,
    DEFAULT_INBOUND_CHANNELS,
    InboundStreamMessage,
    StreamKeys,
    StreamProducer,
    ensure_consumer_group,
    normalize_stream_fields,
    parse_inbound_fields,
)
from src.runtime.events import AgentEventType
from src.utils.exceptions import AgentNotFoundError, SessionNotFoundError
from src.utils.logging import get_logger

logger = get_logger("queue.inbound_worker")

_worker: InboundStreamWorker | None = None


class InboundStreamWorker:
    """消费 stream:agent:{agentId} 与 stream:inbound:{channel}。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._redis: aioredis.Redis | None = None
        self._producer: StreamProducer | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._stream_keys: list[str] = []
        self._consumer_name = f"agent-core-{os.getpid()}"

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            # socket_timeout 须大于 XREADGROUP block，否则空闲等待会被误判为读超时
            self._redis = aioredis.from_url(
                self._settings.redis_url,
                max_connections=self._settings.REDIS_MAX_CONNECTIONS,
                decode_responses=True,
                socket_timeout=(BLOCK_MS / 1000) + 10,
                socket_connect_timeout=5,
            )
        return self._redis

    def _resolve_stream_keys(self, agent_ids: list[str]) -> list[str]:
        keys: list[str] = []
        for agent_id in agent_ids:
            keys.append(StreamKeys.agent_inbound(agent_id))
        for channel in DEFAULT_INBOUND_CHANNELS:
            keys.append(StreamKeys.channel_inbound(channel))
        return sorted(set(keys))

    async def start(self, agent_ids: list[str] | None = None) -> None:
        if self._running:
            return

        manager = get_agent_manager()
        ids = agent_ids or [inst.id for inst in manager.list_agents()]
        self._stream_keys = self._resolve_stream_keys(ids)
        if not self._stream_keys:
            logger.warning("No inbound streams to consume; waiting for agent sync")
            self._stream_keys = [
                StreamKeys.channel_inbound("h5"),
            ]

        redis = await self._get_redis()
        self._producer = StreamProducer(redis)

        for stream_key in self._stream_keys:
            await ensure_consumer_group(redis, stream_key)
        await ensure_consumer_group(redis, StreamKeys.agent_events())

        self._running = True
        self._task = asyncio.create_task(self._consume_loop(), name="inbound-stream-worker")
        logger.info(
            "Inbound stream worker started",
            consumer=self._consumer_name,
            streams=self._stream_keys,
        )

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None
        logger.info("Inbound stream worker stopped")

    async def refresh_streams(self, agent_ids: list[str]) -> None:
        """Agent 同步后更新订阅的 stream 列表。"""
        new_keys = self._resolve_stream_keys(agent_ids)
        redis = await self._get_redis()
        for stream_key in new_keys:
            if stream_key not in self._stream_keys:
                await ensure_consumer_group(redis, stream_key)
        self._stream_keys = new_keys
        logger.info("Inbound stream subscriptions updated", streams=self._stream_keys)

    async def _consume_loop(self) -> None:
        redis = await self._get_redis()
        while self._running:
            try:
                if not self._stream_keys:
                    await asyncio.sleep(1)
                    continue

                streams = {key: ">" for key in self._stream_keys}
                result = await redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=self._consumer_name,
                    streams=streams,
                    count=1,
                    block=BLOCK_MS,
                )
                if not result:
                    continue

                for stream_key, messages in result:
                    for message_id, raw_fields in messages:
                        fields = normalize_stream_fields(raw_fields)
                        inbound = parse_inbound_fields(fields)
                        try:
                            await self._process_inbound(inbound, stream_key)
                            await redis.xack(stream_key, CONSUMER_GROUP, message_id)
                        except Exception as exc:
                            logger.error(
                                "Failed to process inbound stream message",
                                stream_key=stream_key,
                                message_id=message_id,
                                session_id=inbound.session_id,
                                error=str(exc),
                            )
            except asyncio.CancelledError:
                raise
            except (RedisTimeoutError, asyncio.TimeoutError):
                # XREADGROUP 阻塞超时 = 暂无新消息，属正常空闲
                continue
            except Exception as exc:
                logger.error("Inbound stream consume loop error", error=str(exc))
                await asyncio.sleep(1)

    async def _process_inbound(
        self,
        inbound: InboundStreamMessage,
        stream_key: str,
    ) -> None:
        if not inbound.content.strip():
            logger.debug("Skip empty inbound message", session_id=inbound.session_id)
            return

        agent_id = inbound.agent_id
        if not agent_id and stream_key.startswith("stream:agent:"):
            agent_id = stream_key.removeprefix("stream:agent:")

        session_manager = get_session_manager()
        agent_manager = get_agent_manager()
        producer = self._producer
        if producer is None:
            raise RuntimeError("Stream producer not initialized")

        try:
            session = await session_manager.get_session(inbound.session_id)
        except SessionNotFoundError:
            logger.warning(
                "Session not found for inbound message",
                session_id=inbound.session_id,
                user_id=inbound.user_id,
            )
            await self._publish_error(
                producer,
                inbound,
                agent_id or "unknown",
                "session_not_found",
                f"Session not found: {inbound.session_id}",
            )
            return

        resolved_agent_id = agent_id or session.agent_id
        user_msg = await session_manager.add_message(
            session_id=session.session_id,
            role="user",
            content=inbound.content,
            metadata=inbound.metadata,
        )

        try:
            instance = await agent_manager.ensure_agent_ready(resolved_agent_id)
        except AgentNotFoundError as exc:
            await self._publish_error(
                producer,
                inbound,
                resolved_agent_id,
                "agent_not_found",
                str(exc),
            )
            return

        response_parts: list[str] = []
        runtime_error: str | None = None
        timeout_sec = self._settings.AGENT_MESSAGE_TIMEOUT

        try:
            async with asyncio.timeout(timeout_sec):
                async for event in instance.process_message(
                    session=session,
                    message=user_msg,
                ):
                    await producer.publish_agent_event(
                        session_id=session.session_id,
                        user_id=inbound.user_id,
                        channel=session.channel,
                        agent_id=resolved_agent_id,
                        trace_id=inbound.trace_id,
                        event=event,
                    )
                    if event.type == AgentEventType.TEXT_DELTA and event.content:
                        response_parts.append(event.content)
                    elif event.type == AgentEventType.ERROR:
                        runtime_error = event.message or "Agent runtime error"
        except TimeoutError:
            logger.error(
                "Agent message processing timed out",
                session_id=session.session_id,
                agent_id=resolved_agent_id,
                timeout_sec=timeout_sec,
            )
            await self._publish_error(
                producer,
                inbound,
                resolved_agent_id,
                "agent_timeout",
                f"处理超时（{timeout_sec}s），请稍后重试",
            )
            return
        except Exception as exc:
            logger.error(
                "Agent message processing failed",
                session_id=session.session_id,
                agent_id=resolved_agent_id,
                error=str(exc),
                exc_info=True,
            )
            await self._publish_error(
                producer,
                inbound,
                resolved_agent_id,
                "agent_processing_error",
                str(exc) or "Agent processing failed",
            )
            return

        response_text = "".join(response_parts)
        if response_text.strip():
            await session_manager.add_message(
                session_id=session.session_id,
                role="assistant",
                content=response_text,
            )
        elif runtime_error:
            logger.warning(
                "Agent completed without text response",
                session_id=session.session_id,
                error=runtime_error,
            )

        logger.info(
            "Inbound message processed",
            session_id=session.session_id,
            agent_id=resolved_agent_id,
            response_length=len(response_text),
        )

    async def _publish_error(
        self,
        producer: StreamProducer,
        inbound: InboundStreamMessage,
        agent_id: str,
        error_code: str,
        message: str,
    ) -> None:
        from src.runtime.events import AgentEvent

        await producer.publish_agent_event(
            session_id=inbound.session_id,
            user_id=inbound.user_id,
            channel=inbound.channel,
            agent_id=agent_id,
            trace_id=inbound.trace_id,
            event=AgentEvent.error(error_code, message),
        )
        await producer.publish_agent_event(
            session_id=inbound.session_id,
            user_id=inbound.user_id,
            channel=inbound.channel,
            agent_id=agent_id,
            trace_id=inbound.trace_id,
            event=AgentEvent.done(),
        )


def get_inbound_stream_worker() -> InboundStreamWorker:
    global _worker
    if _worker is None:
        _worker = InboundStreamWorker()
    return _worker


async def start_inbound_stream_worker(agent_ids: list[str] | None = None) -> None:
    settings = get_settings()
    if not settings.STREAM_CONSUMER_ENABLED:
        logger.info("Inbound stream worker disabled by config")
        return
    await get_inbound_stream_worker().start(agent_ids)


async def stop_inbound_stream_worker() -> None:
    if _worker is not None:
        await _worker.stop()
