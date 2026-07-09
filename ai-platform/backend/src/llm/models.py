"""LLM 数据模型 — 请求、响应、数据块、token 用量、API Key、配额、代理。

这些 Pydantic 模型定义了所有 LLM Gateway 操作的数据契约，
确保 Gateway、适配器和调用方之间的类型安全。
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class LLMRole(str, Enum):
    """LLM 对话中的消息角色。"""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class LLMMessage(BaseModel):
    """LLM 对话中的单条消息。"""

    role: LLMRole = LLMRole.USER
    content: str = ""
    name: str = Field(default="", description="tool 角色消息的工具名称")
    tool_call_id: str = Field(default="", description="tool 结果消息的工具调用 ID")
    tool_calls: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Assistant 工具调用请求（OpenAI function-calling 格式）",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_api_dict(self) -> dict[str, Any]:
        """转换为 provider API 格式（role + content）。"""
        result: dict[str, Any] = {"role": self.role.value}

        if self.role == LLMRole.ASSISTANT and self.tool_calls:
            result["content"] = self.content or None
            result["tool_calls"] = self.tool_calls
            return result

        if self.role == LLMRole.TOOL:
            result["content"] = self.content
            result["tool_call_id"] = self.tool_call_id
            return result

        result["content"] = self.content
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


class TokenUsage(BaseModel):
    """LLM 调用的 token 用量信息。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        """两个 TokenUsage 实例相加（用于累积流式数据块）。"""
        return TokenUsage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        """就地累加，用于累积流式数据块。"""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        return self


class LLMRequest(BaseModel):
    """发送到 LLM Gateway 的请求。"""

    messages: list[LLMMessage] = Field(default_factory=list)
    model: str = Field(default="deepseek-v4-flash", description="模型名称")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    stream: bool = Field(default=False, description="是否流式返回响应")

    # 追踪元数据
    session_id: str = Field(default="", description="用于追踪的 Session ID")
    user_id: str = Field(default="", description="用于配额追踪的 User ID")
    dept: str = Field(default="", description="用于配额追踪的部门")

    # 工具调用
    tools: list[dict[str, Any]] = Field(default_factory=list, description="工具 schema 列表")
    tool_choice: str = Field(default="auto", description="工具选择：auto | none | specific")

    # 额外的 provider 特定参数
    extra: dict[str, Any] = Field(default_factory=dict)


class LLMChunk(BaseModel):
    """LLM 流式响应中的单个数据块。"""

    content: str = Field(default="", description="增量内容文本")
    reasoning_content: str = Field(default="", description="推理/思考增量文本（DeepSeek 等）")
    role: str = Field(default="", description="数据块中的角色信息")
    finish_reason: str = Field(default="", description="生成停止原因")
    usage: TokenUsage | None = Field(default=None, description="Token 用量（通常在最后一个数据块中）")
    index: int = Field(default=0, description="选项索引")


class LLMResponse(BaseModel):
    """完整的（非流式）LLM 响应。"""

    content: str = Field(default="", description="生成的文本内容")
    reasoning_content: str = Field(default="", description="模型推理/思考文本")
    role: str = Field(default="assistant")
    model: str = Field(default="")
    usage: TokenUsage = Field(default_factory=TokenUsage)
    finish_reason: str = Field(default="stop")
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict, description="provider 原始响应")


class APIKey(BaseModel):
    """LLM provider 的 API Key，包含追踪元数据。"""

    key: str = Field(..., description="实际的 API Key 字符串")
    provider: str = Field(..., description="Provider：deepseek | qwen")
    label: str = Field(default="", description="人类可读的标签")
    is_active: bool = True
    is_healthy: bool = True
    total_calls: int = 0
    error_count: int = 0
    last_used_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_message: str = ""

    @property
    def error_rate(self) -> float:
        """计算此 Key 的错误率。"""
        if self.total_calls == 0:
            return 0.0
        return self.error_count / self.total_calls

    def record_success(self) -> None:
        """记录一次成功的 API 调用。"""
        self.total_calls += 1
        self.last_used_at = datetime.now(timezone.utc)

    def record_error(self, message: str = "") -> None:
        """记录一次失败的 API 调用。"""
        self.total_calls += 1
        self.error_count += 1
        self.last_used_at = datetime.now(timezone.utc)
        self.last_error_at = datetime.now(timezone.utc)
        self.last_error_message = message

    def mark_unhealthy(self) -> None:
        """将此 Key 标记为不健康（例如收到 401/403 后）。"""
        self.is_healthy = False


class QuotaInfo(BaseModel):
    """用户或部门的 token 配额信息。"""

    user_id: str = ""
    department: str = ""
    daily_limit: int = Field(default=100000, description="每日 token 限额")
    used_today: int = 0
    alert_threshold: float = Field(default=0.8, description="使用率达到 80% 时告警")

    @property
    def remaining(self) -> int:
        """今日剩余 token 数。"""
        return max(0, self.daily_limit - self.used_today)

    @property
    def usage_ratio(self) -> float:
        """当前使用率（0.0 - 1.0+）。"""
        if self.daily_limit == 0:
            return 1.0
        return self.used_today / self.daily_limit

    @property
    def is_exceeded(self) -> bool:
        """配额是否已超限。"""
        return self.used_today >= self.daily_limit

    @property
    def is_alert(self) -> bool:
        """使用量是否已超过告警阈值。"""
        return self.usage_ratio >= self.alert_threshold


class ProxyNode(BaseModel):
    """LLM API 请求的出口代理节点。"""

    host: str
    port: int
    protocol: str = Field(default="http", description="http | https | socks5")
    is_healthy: bool = True
    last_check_at: datetime | None = None
    consecutive_failures: int = 0
    total_requests: int = 0

    @property
    def url(self) -> str:
        """完整的代理 URL 字符串。"""
        return f"{self.protocol}://{self.host}:{self.port}"


class ProviderConfig(BaseModel):
    """单个 LLM provider 的配置。"""

    name: str = Field(..., description="Provider 名称：deepseek | qwen")
    endpoint: str = Field(..., description="API 基础 URL")
    models: list[str] = Field(default_factory=list)
    api_keys: list[APIKey] = Field(default_factory=list)
    key_rotation: str = Field(default="round-robin")
    proxy_url: str = Field(default="", description="出口代理 URL")
    timeout: int = Field(default=60, description="请求超时时间（秒）")
    max_retries: int = Field(default=3)


class FailoverConfig(BaseModel):
    """LLM provider 故障转移配置。"""

    primary: str = Field(default="deepseek")
    fallback: str = Field(default="qwen")
    auto_switch: bool = True
    max_retries: int = 3
    failure_threshold: int = Field(default=3, description="切换前连续失败次数阈值")
    recovery_check_interval: int = Field(default=60, description="恢复探测间隔（秒）")
