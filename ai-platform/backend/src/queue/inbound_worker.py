"""入站 Redis Stream 消费者 — 消费 Gateway 消息并回写 AgentEvent 流。

进程内有界并发：不同 session 可并行处理；同一 session 严格串行。
"""

from __future__ import annotations

import asyncio
import os

import redis.asyncio as aioredis
from redis.exceptions import TimeoutError as RedisTimeoutError

from src.agent.manager import get_agent_manager
from src.agent.session import get_session_manager
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
        """初始化 Redis 连接占位、并发控制与 session 级串行锁。"""
        self._settings = get_settings()
        self._redis: aioredis.Redis | None = None
        self._producer: StreamProducer | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._stream_keys: list[str] = []
        self._consumer_name = f"agent-core-{os.getpid()}"
        self._max_concurrency = max(1, self._settings.INBOUND_MAX_CONCURRENCY)
        self._read_count = max(1, self._settings.INBOUND_READ_COUNT)
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._session_locks: dict[str, asyncio.Lock] = {}
        self._session_locks_guard = asyncio.Lock()
        self._inflight: set[asyncio.Task[None]] = set()

    async def _get_redis(self) -> aioredis.Redis:
        """懒创建 Redis 异步客户端；``socket_timeout`` 须大于 XREADGROUP 阻塞时长。

        Returns:
            已配置的 ``redis.asyncio.Redis`` 实例。
        """
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
        """根据 Agent ID 与默认渠道拼接入站 stream 键名列表。

        Args:
            agent_ids: 需订阅的 Agent 实例 ID 列表。

        Returns:
            去重并排序后的 stream key 列表。
        """
        keys: list[str] = []
        for agent_id in agent_ids:
            keys.append(StreamKeys.agent_inbound(agent_id))
        for channel in DEFAULT_INBOUND_CHANNELS:
            keys.append(StreamKeys.channel_inbound(channel))
        return sorted(set(keys))

    async def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """获取或创建指定 session 的互斥锁，保证同会话消息串行处理。

        Args:
            session_id: 会话 ID。

        Returns:
            该 session 专用的 ``asyncio.Lock``。
        """
        async with self._session_locks_guard:
            lock = self._session_locks.get(session_id)
            if lock is None:
                lock = asyncio.Lock()
                self._session_locks[session_id] = lock
            return lock

    async def start(self, agent_ids: list[str] | None = None) -> None:
        """创建消费者组、启动 XREADGROUP 消费循环。

        Args:
            agent_ids: 要订阅的 Agent ID；为 ``None`` 时使用当前已注册的全部 Agent。
        """
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
            max_concurrency=self._max_concurrency,
            read_count=self._read_count,
        )

    async def stop(self) -> None:
        """停止消费循环、取消在飞任务并关闭 Redis 连接。"""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        inflight = list(self._inflight)
        for task in inflight:
            task.cancel()
        if inflight:
            await asyncio.gather(*inflight, return_exceptions=True)
        self._inflight.clear()
        self._session_locks.clear()

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

    def _spawn_handler(
        self,
        stream_key: str,
        message_id: str,
        inbound: InboundStreamMessage,
    ) -> None:
        """为单条入站消息创建异步处理任务并注册完成回调。

        Args:
            stream_key: Redis stream 键名。
            message_id: Redis 消息 ID。
            inbound: 解析后的入站消息体。
        """
        task = asyncio.create_task(
            self._handle_message(stream_key, message_id, inbound),
            name=f"inbound-{inbound.session_id}-{message_id}",
        )
        self._inflight.add(task)

        def _on_done(done: asyncio.Task[None]) -> None:
            """任务结束时从在飞集合移除，并记录未捕获异常。"""
            self._inflight.discard(done)
            if done.cancelled():
                return
            exc = done.exception()
            if exc is not None:
                logger.error(
                    "Inbound handler task failed",
                    session_id=inbound.session_id,
                    message_id=message_id,
                    error=str(exc),
                    exc_info=exc,
                )

        task.add_done_callback(_on_done)

    async def _consume_loop(self) -> None:
        """主消费循环：背压控制下 XREADGROUP 拉取并分发入站消息。"""
        redis = await self._get_redis()
        while self._running:
            try:
                if not self._stream_keys:
                    await asyncio.sleep(1)
                    continue

                # 背压：在飞任务已达上限时暂停拉取，避免无界 create_task
                while self._running and len(self._inflight) >= self._max_concurrency:
                    await asyncio.sleep(0.05)

                if not self._running:
                    break

                streams = {key: ">" for key in self._stream_keys}
                result = await redis.xreadgroup(
                    groupname=CONSUMER_GROUP,
                    consumername=self._consumer_name,
                    streams=streams,
                    count=self._read_count,
                    block=BLOCK_MS,
                )
                if not result:
                    continue

                for stream_key, messages in result:
                    for message_id, raw_fields in messages:
                        fields = normalize_stream_fields(raw_fields)
                        inbound = parse_inbound_fields(fields)
                        self._spawn_handler(str(stream_key), str(message_id), inbound)
            except asyncio.CancelledError:
                raise
            except (RedisTimeoutError, asyncio.TimeoutError):
                # XREADGROUP 阻塞超时 = 暂无新消息，属正常空闲
                continue
            except Exception as exc:
                logger.error("Inbound stream consume loop error", error=str(exc))
                await asyncio.sleep(1)

    async def _handle_message(
        self,
        stream_key: str,
        message_id: str,
        inbound: InboundStreamMessage,
    ) -> None:
        """有界并发 + 同 session 串行；成功后 ACK。"""
        redis = await self._get_redis()
        async with self._semaphore:
            lock = await self._get_session_lock(inbound.session_id)
            async with lock:
                try:
                    await self._process_inbound(inbound, stream_key)
                    await redis.xack(stream_key, CONSUMER_GROUP, message_id)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.error(
                        "Failed to process inbound stream message",
                        stream_key=stream_key,
                        message_id=message_id,
                        session_id=inbound.session_id,
                        error=str(exc),
                        exc_info=True,
                    )
                    # 暂不 ACK，留给后续 Phase 3 claim/重试

    async def _process_inbound(
        self,
        inbound: InboundStreamMessage,
        stream_key: str,
    ) -> None:
        """解析入站消息、写入会话、驱动 Agent 并将事件发布到出站 stream。

        处理会话/Agent 不存在、超时及运行时错误，必要时通过
        ``_publish_error`` 下发错误事件。

        Args:
            inbound: Gateway 写入的入站消息。
            stream_key: 消息来源 stream 键名（用于推断 ``agent_id``）。
        """
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
        """向出站 stream 发布错误事件并紧跟 ``done`` 事件。

        Args:
            producer: 出站 ``StreamProducer``。
            inbound: 原始入站消息（用于 session/user/channel/trace）。
            agent_id: 关联的 Agent ID。
            error_code: 平台错误码。
            message: 用户可见错误说明。
        """
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
    """返回进程内单例 ``InboundStreamWorker``。"""
    global _worker
    if _worker is None:
        _worker = InboundStreamWorker()
    return _worker


async def start_inbound_stream_worker(agent_ids: list[str] | None = None) -> None:
    """按配置启动入站 stream 消费者；``STREAM_CONSUMER_ENABLED=False`` 时跳过。

    Args:
        agent_ids: 要订阅的 Agent ID 列表；为 ``None`` 时使用全部已注册 Agent。
    """
    settings = get_settings()
    if not settings.STREAM_CONSUMER_ENABLED:
        logger.info("Inbound stream worker disabled by config")
        return
    await get_inbound_stream_worker().start(agent_ids)


async def stop_inbound_stream_worker() -> None:
    """停止已创建的入站 stream 消费者（若存在）。"""
    if _worker is not None:
        await _worker.stop()
