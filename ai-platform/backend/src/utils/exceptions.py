"""AI Platform 后端的自定义异常层次结构。"""

from __future__ import annotations


class AIPlatformError(Exception):
    """所有 AI Platform 错误的基础异常。"""

    def __init__(self, message: str, code: int = 9000) -> None:
        super().__init__(message)
        self.message = message
        self.code = code


# ===== 认证/权限错误（1000-1999） =====


class AuthenticationError(AIPlatformError):
    """认证失败时抛出。"""

    def __init__(self, message: str = "Authentication failed") -> None:
        super().__init__(message, code=1001)


class PermissionDeniedError(AIPlatformError):
    """用户缺少所需权限时抛出。"""

    def __init__(self, message: str = "Permission denied") -> None:
        super().__init__(message, code=1003)


class TokenExpiredError(AIPlatformError):
    """JWT Token 过期时抛出。"""

    def __init__(self, message: str = "Token expired") -> None:
        super().__init__(message, code=1002)


# ===== Agent 错误（2000-2999） =====


class AgentNotFoundError(AIPlatformError):
    """请求的 Agent 不存在时抛出。"""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent not found: {agent_id}", code=2001)


class AgentAlreadyExistsError(AIPlatformError):
    """尝试创建重复的 Agent 时抛出。"""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent already exists: {agent_id}", code=2002)


class AgentStateError(AIPlatformError):
    """尝试进行无效状态转换时抛出。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=2003)


class AgentNotRunningError(AIPlatformError):
    """操作需要 Agent 处于运行状态时抛出。"""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent is not running: {agent_id}", code=2004)


class SessionNotFoundError(AIPlatformError):
    """请求的 Session 不存在时抛出。"""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"Session not found: {session_id}", code=2005)


# ===== Skill 错误（3000-3999） =====


class SkillNotFoundError(AIPlatformError):
    """请求的 Skill 不存在时抛出。"""

    def __init__(self, skill_id: str) -> None:
        super().__init__(f"Skill not found: {skill_id}", code=3001)


class SkillTimeoutError(AIPlatformError):
    """Skill 执行超时时抛出。"""

    def __init__(self, skill_id: str, timeout: int) -> None:
        super().__init__(
            f"Skill execution timed out: {skill_id} ({timeout}s)",
            code=3002,
        )


# ===== MCP 错误（4000-4999） =====


class MCPConnectionError(AIPlatformError):
    """MCP Server 连接失败时抛出。"""

    def __init__(self, server_name: str, detail: str = "") -> None:
        super().__init__(
            f"MCP Server connection failed: {server_name} — {detail}",
            code=4001,
        )


class MCPToolNotFoundError(AIPlatformError):
    """请求的 MCP Tool 未找到时抛出。"""

    def __init__(self, tool_name: str) -> None:
        super().__init__(f"MCP Tool not found: {tool_name}", code=4002)


# ===== 渠道/Gateway 错误（5000-5999） =====


class ChannelError(AIPlatformError):
    """渠道适配器遇到错误时抛出。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=5001)


# ===== LLM Gateway 错误（6000-6999） =====


class LLMGatewayError(AIPlatformError):
    """LLM Gateway 遇到错误时抛出。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=6001)


class QuotaExceededError(AIPlatformError):
    """用户/部门 Token 配额超限时抛出。"""

    def __init__(self, message: str = "Token quota exceeded") -> None:
        super().__init__(message, code=6002)


class LLMProviderError(AIPlatformError):
    """LLM Provider 返回错误时抛出。"""

    def __init__(self, provider: str, detail: str) -> None:
        super().__init__(f"LLM provider error [{provider}]: {detail}", code=6003)


class ProxyUnavailableError(AIPlatformError):
    """所有出站代理节点均不可用时抛出。"""

    def __init__(self, message: str = "All outbound proxy nodes unavailable") -> None:
        super().__init__(message, code=6004)


class FailoverExhaustedError(AIPlatformError):
    """所有故障转移 Provider 均已耗尽时抛出。"""

    def __init__(self, message: str = "All LLM providers failed") -> None:
        super().__init__(message, code=6005)


# ===== 配置错误（7000-7999） =====


class ConfigValidationError(AIPlatformError):
    """配置验证失败时抛出。"""

    def __init__(self, errors: list[str]) -> None:
        super().__init__(
            f"Configuration validation failed: {'; '.join(errors)}",
            code=7001,
        )
        self.validation_errors = errors


class ConfigNotFoundError(AIPlatformError):
    """配置文件或条目未找到时抛出。"""

    def __init__(self, path: str) -> None:
        super().__init__(f"Configuration not found: {path}", code=7002)


class ConfigLoadError(AIPlatformError):
    """配置文件无法加载/解析时抛出。"""

    def __init__(self, path: str, detail: str = "") -> None:
        super().__init__(
            f"Failed to load configuration: {path} — {detail}",
            code=7003,
        )


# ===== 系统错误（9000-9999） =====


class DatabaseError(AIPlatformError):
    """数据库操作失败时抛出。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=9001)


class RedisError(AIPlatformError):
    """Redis 操作失败时抛出。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=9002)


class QdrantError(AIPlatformError):
    """Qdrant 操作失败时抛出。"""

    def __init__(self, message: str) -> None:
        super().__init__(message, code=9003)
