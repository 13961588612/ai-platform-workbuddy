"""AgentEvent 类型定义 — 统一的流式事件协议。

所有运行时输出都作为 AsyncIterable[AgentEvent] 流发出。
Gateway 的 EventTransformer 将这些事件映射为各渠道特定的格式。
"""

from __future__ import annotations
from typing import Any

from enum import Enum

from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
    """所有 AgentEvent 类型的枚举。"""

    TEXT_DELTA = "text.delta"
    TOOL_CALL = "tool.call"
    TOOL_RESULT = "tool.result"
    UI_RENDER = "ui.render"
    APPROVAL_REQUEST = "approval.request"
    ERROR = "error"
    DONE = "done"


class TokenUsage(BaseModel):
    """单次 LLM 调用的 token 用量。"""

    prompt: int = Field(default=0, description="Prompt token 数量")
    completion: int = Field(default=0, description="Completion token 数量")
    total: int = Field(default=0, description="总 token 数量")

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """将两个 TokenUsage 实例相加（用于累加流式片段）。"""
        return TokenUsage(
            prompt=self.prompt + other.prompt,
            completion=self.completion + other.completion,
            total=self.total + other.total,
        )


class AgentEvent(BaseModel):
    """
    Agent 流式协议中的统一事件。

    每个事件都有一个 `type` 字段，以及根据类型填充的可选字段：
    - text.delta:       content
    - tool.call:        tool_name、args
    - tool.result:      tool_name、result
    - ui.render:        component、props
    - approval.request: skill_id、detail
    - error:            error_code、message
    - done:             token_usage
    """

    type: AgentEventType
    content: str | None = None
    tool_name: str | None = None
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    component: str | None = None
    props: dict[str, Any] | None = None
    skill_id: str | None = None
    error_code: str | None = None
    message: str | None = None
    token_usage: TokenUsage | None = None

    @classmethod
    def text_delta(cls, content: str) -> AgentEvent:
        """创建一个 text.delta 事件。"""
        return cls(type=AgentEventType.TEXT_DELTA, content=content)

    @classmethod
    def tool_call(cls, tool_name: str, args: dict[str, Any]) -> AgentEvent:
        """创建一个 tool.call 事件。"""
        return cls(type=AgentEventType.TOOL_CALL, tool_name=tool_name, args=args)

    @classmethod
    def tool_result(cls, tool_name: str, result: dict[str, Any]) -> AgentEvent:
        """创建一个 tool.result 事件。"""
        return cls(type=AgentEventType.TOOL_RESULT, tool_name=tool_name, result=result)

    @classmethod
    def ui_render(cls, component: str, props: dict[str, Any]) -> AgentEvent:
        """创建一个 ui.render 事件。"""
        return cls(type=AgentEventType.UI_RENDER, component=component, props=props)

    @classmethod
    def approval_request(cls, skill_id: str, detail: dict[str, Any]) -> AgentEvent:
        """创建一个 approval.request 事件。"""
        return cls(type=AgentEventType.APPROVAL_REQUEST, skill_id=skill_id, detail=detail)  # type: ignore[call-arg]

    @classmethod
    def error(cls, error_code: str, message: str) -> AgentEvent:
        """创建一个 error 事件。"""
        return cls(type=AgentEventType.ERROR, error_code=error_code, message=message)

    @classmethod
    def done(cls, token_usage: TokenUsage | None = None) -> AgentEvent:
        """创建一个 done 事件。"""
        return cls(type=AgentEventType.DONE, token_usage=token_usage)


class HealthStatus(BaseModel):
    """运行时或 agent 实例的健康检查结果。"""

    healthy: bool = Field(..., description="组件是否健康")
    details: dict[str, Any] = Field(default_factory=dict, description="额外的健康详情")
    timestamp: str | None = None
