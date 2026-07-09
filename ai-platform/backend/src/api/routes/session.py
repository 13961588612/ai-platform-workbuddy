"""Session API 路由 — 会话生命周期和消息处理。

端点：
- POST   /api/v1/sessions                 — 创建新会话
- GET    /api/v1/sessions/{session_id}    — 获取会话详情
- DELETE /api/v1/sessions/{session_id}    — 关闭会话
- POST   /api/v1/sessions/{session_id}/messages — 发送消息（非流式）
- GET    /api/v1/sessions/{session_id}/messages — 获取会话消息
- POST   /api/v1/sessions/route           — 路由请求（AgentRouter）
"""

from __future__ import annotations
from typing import Any


from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from src.agent.session import SessionManager
from src.api.deps import (
    get_agent_manager_dep,
    get_agent_router_dep,
    get_session_manager_dep,
)
from src.api.response import error_response, success
from src.router.agent_router import AgentRouter
from src.router.models import RouteResult, UserRequest
from src.utils.exceptions import AgentNotFoundError, SessionNotFoundError
from src.utils.logging import get_logger

logger = get_logger("api.routes.session")

router = APIRouter(prefix="/sessions", tags=["sessions"])


# ===== 请求/响应模型 =====


class CreateSessionRequest(BaseModel):
    """创建新会话的请求体。"""

    agent_id: str = Field(..., description="绑定到此会话的 Agent ID")
    user_id: str = Field(..., description="用户标识符")
    channel: str = Field(default="web", description="来源渠道：web | wecom_h5 | wecom_bot")
    runtime_type: str = Field(default="openharness")


class SendMessageRequest(BaseModel):
    """在会话中发送消息的请求体。"""

    content: str = Field(..., description="消息内容")
    role: str = Field(default="user", description="消息角色：user | system")
    metadata: dict[str, Any] = Field(default_factory=dict)


class RouteRequest(BaseModel):
    """通过 AgentRouter 路由用户请求的请求体。"""

    text: str = Field(..., description="用户输入文本")
    user_id: str = Field(..., description="用户标识符")
    session_id: str = Field(..., description="会话标识符")
    channel: str = Field(default="web")
    department: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionResponse(BaseModel):
    """会话详情响应。"""

    session_id: str
    agent_id: str
    user_id: str
    channel: str
    runtime_type: str
    message_count: int
    created_at: str
    updated_at: str


class MessageResponse(BaseModel):
    """会话中的一条消息。"""

    id: str
    role: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    timestamp: str


# ===== 端点 =====


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_session(
    req: CreateSessionRequest,
    session_manager: SessionManager = Depends(get_session_manager_dep),
) -> dict[str, Any]:
    """创建带有渠道特定 ID 命名的新聊天会话。"""
    try:
        session: dict[str, Any] = await session_manager.create_session(
            agent_id=req.agent_id,
            user_id=req.user_id,
            channel=req.channel,
            runtime_type=req.runtime_type,
        )
        return success(
            data={
                "session_id": session.session_id,
                "agent_id": session.agent_id,
                "user_id": session.user_id,
                "channel": session.channel,
                "runtime_type": session.runtime_type,
            },
            message="Session created",
        )
    except Exception as exc:
        logger.error("Failed to create session", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{session_id}")
async def get_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager_dep),
) -> dict[str, Any]:
    """获取会话详情，包括消息历史。"""
    try:
        session: dict[str, Any] = await session_manager.get_session(session_id)
        return success(
            data=SessionResponse(
                session_id=session.session_id,
                agent_id=session.agent_id,
                user_id=session.user_id,
                channel=session.channel,
                runtime_type=session.runtime_type,
                message_count=len(session.messages),
                created_at=session.created_at.isoformat(),
                updated_at=session.updated_at.isoformat(),
            ).model_dump()
        )
    except SessionNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)


@router.delete("/{session_id}")
async def close_session(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager_dep),
) -> dict[str, Any]:
    """关闭并移除会话。"""
    try:
        await session_manager.close_session(session_id)
        return success(message="Session closed")
    except SessionNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)


@router.get("/{session_id}/messages")
async def get_messages(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager_dep),
) -> dict[str, Any]:
    """获取会话中的所有消息。"""
    try:
        session: dict[str, Any] = await session_manager.get_session(session_id)
        messages: list[dict[str, Any]] = [
            MessageResponse(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                metadata=msg.metadata,
                timestamp=msg.timestamp.isoformat(),
            ).model_dump()
            for msg in session.messages
        ]
        return success(data=messages)
    except SessionNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)


@router.post("/{session_id}/messages")
async def send_message(
    session_id: str,
    req: SendMessageRequest,
    session_manager: SessionManager = Depends(get_session_manager_dep),
    agent_manager=Depends(get_agent_manager_dep),
) -> dict[str, Any]:
    """
    向会话发送消息并获取非流式响应。

    流式响应请使用 WebSocket 端点。
    """
    try:
        from src.agent.session import Message
        from src.runtime.events import AgentEventType

        # 获取会话
        session: dict[str, Any] = await session_manager.get_session(session_id)

        # 添加用户消息
        user_msg: Message = await session_manager.add_message(
            session_id=session_id,
            role=req.role,
            content=req.content,
            metadata=req.metadata,
        )

        # 确保 Agent 已注册并处于 RUNNING（支持启动时未同步的懒加载）
        instance: AgentInstance = await agent_manager.ensure_agent_ready(session.agent_id)

        # 收集 runtime 流式事件
        response_parts: list[str] = []
        runtime_error: str | None = None
        tool_errors: list[str] = []
        async for event in instance.process_message(
            session=session,
            message=Message(role=req.role, content=req.content, metadata=req.metadata),
        ):
            if event.type == AgentEventType.TEXT_DELTA and event.content:
                response_parts.append(event.content)
            elif event.type == AgentEventType.TOOL_RESULT and event.result:
                err: Skill | None = event.result.get("error")
                if err:
                    tool_errors.append(f"{event.tool_name}: {err}")
            elif event.type == AgentEventType.ERROR:
                runtime_error: Any = event.message or "Agent runtime error"

        response_text: str = "".join(response_parts)

        # 工具失败已转为 tool.result，不应中断；仅无有效回复时的致命错误返回 500
        if runtime_error and not response_text.strip():
            return error_response(
                9000,
                runtime_error,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        if runtime_error:
            logger.warning(
                "Agent completed with runtime warning",
                session_id=session_id,
                error=runtime_error,
                tool_errors=tool_errors,
            )

        # 保存助手响应
        await session_manager.add_message(
            session_id=session_id,
            role="assistant",
            content=response_text,
        )

        return success(
            data={
                "message_id": user_msg.id,
                "response": response_text,
                "session_id": session_id,
                "warnings": [runtime_error] if runtime_error else [],
                "tool_errors": tool_errors,
            },
            message="Message processed",
        )
    except SessionNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)
    except AgentNotFoundError as exc:
        return error_response(exc.code, exc.message, status.HTTP_404_NOT_FOUND)
    except Exception as exc:
        logger.error("Failed to process message", error=str(exc), session_id=session_id)
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/route")
async def route_request(
    req: RouteRequest,
    agent_router: AgentRouter = Depends(get_agent_router_dep),
) -> dict[str, Any]:
    """
    通过 AgentRouter 策略链路由用户请求。

    返回匹配的 agent_id、使用的策略和置信度分数。
    不处理消息——请使用 /sessions/{id}/messages 处理消息。
    """
    try:
        user_request: UserRequest = UserRequest(
            text=req.text,
            user_id=req.user_id,
            session_id=req.session_id,
            channel=req.channel,
            department=req.department,
            metadata=req.metadata,
        )

        result: RouteResult = await agent_router.route(user_request)

        return success(
            data={
                "agent_id": result.agent_id,
                "strategy_used": result.strategy_used,
                "confidence": result.confidence,
                "latency_ms": result.latency_ms,
                "metadata": result.metadata,
            },
            message="Route completed",
        )
    except Exception as exc:
        logger.error("Routing failed", error=str(exc))
        return error_response(9000, str(exc), status.HTTP_500_INTERNAL_SERVER_ERROR)
