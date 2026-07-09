"""
全局应用配置。

所有配置均由环境变量驱动，为本地开发提供合理的默认值。
使用 pydantic-settings 实现类型安全、带验证的配置加载，
并自动绑定环境变量。
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """部署环境标识符。"""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LogLevel(str, Enum):
    """结构化日志级别。"""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    FATAL = "FATAL"


class Settings(BaseSettings):
    """
    应用全局设置，从环境变量中加载。

    所有设置都有适用于 Docker Compose 中本地开发的默认值。
    生产环境中请通过环境变量或 .env 文件覆盖。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ===== 应用 =====
    APP_NAME: str = "ai-platform-backend"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = True
    LOG_LEVEL: LogLevel = LogLevel.INFO
    LOG_FORMAT: str = "json"
    LOG_FILE: str = Field(
        default="logs/backend.log",
        description="日志文件路径；设为空字符串则仅输出到控制台",
    )
    LOG_MAX_BYTES: int = Field(
        default=10_485_760,
        description="单个日志文件最大字节数（默认 10MB）",
    )
    LOG_BACKUP_COUNT: int = Field(
        default=5,
        description="日志轮转保留的历史文件数量",
    )
    AGENT_TRACE_LOG: bool = True
    AGENT_MESSAGE_TIMEOUT: int = Field(
        default=120,
        description="单条入站消息 Agent 处理超时（秒），超时后向前端推送 error + done",
    )
    MCP_TOOL_CALL_TIMEOUT: int = Field(
        default=30,
        description="单次 MCP 工具调用超时（秒）",
    )

    # ===== 服务器 =====
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1
    RELOAD: bool = False
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:80",
            "http://nginx",
        ]
    )

    # ===== PostgreSQL =====
    POSTGRES_HOST: str = "postgres"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "aiplatform"
    POSTGRES_PASSWORD: str = "aiplatform_dev_password"
    POSTGRES_DB: str = "ai_platform"
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 10
    POSTGRES_POOL_TIMEOUT: int = 30
    POSTGRES_POOL_RECYCLE: int = 3600

    # ===== Redis =====
    REDIS_HOST: str = "redis"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str = ""
    REDIS_MAX_CONNECTIONS: int = 50

    # ===== Redis Streams（Gateway ↔ Agent Core） =====
    STREAM_CONSUMER_ENABLED: bool = Field(
        default=True,
        description="是否启动 Redis Stream 入站消息消费者",
    )
    STREAM_CONSUMER_GROUP: str = "agent-core-group"

    # ===== Qdrant =====
    QDRANT_HOST: str = "qdrant"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str = ""
    QDRANT_COLLECTION_SKILLS: str = "skills_index"
    QDRANT_COLLECTION_AGENT_ROUTER: str = "agent_router_index"
    QDRANT_COLLECTION_AGENT_MEMORY: str = "agent_memory_index"
    QDRANT_VECTOR_SIZE: int = 768

    # ===== 嵌入模型 =====
    EMBEDDING_SERVICE_URL: str = "http://embedding:8001"
    EMBEDDING_MODEL_NAME: str = "bge-small-zh-v1.5"
    EMBEDDING_DIMENSION: int = 768

    # ===== LLM Gateway =====
    LLM_GATEWAY_ENABLED: bool = True
    LLM_PRIMARY_PROVIDER: str = "deepseek"
    LLM_FALLBACK_PROVIDER: str = "qwen"
    LLM_PRIMARY_MODEL: str = "deepseek-v4-flash"
    LLM_FALLBACK_MODEL: str = "qwen3.6-plus"
    LLM_REQUEST_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3
    LLM_FAILOVER_AUTO_SWITCH: bool = True

    # DeepSeek API
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_API_ENDPOINT: str = "https://api.deepseek.com/v1"

    # Qwen API
    QWEN_API_KEY: str = ""
    QWEN_API_ENDPOINT: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    # ===== 出站代理 =====
    OUTBOUND_PROXY_ENABLED: bool = True
    OUTBOUND_PROXY_HOST: str = "outbound-proxy"
    OUTBOUND_PROXY_PORT: int = 3128
    OUTBOUND_PROXY_ALLOWED_DOMAINS: list[str] = Field(
        default_factory=lambda: [
            "api.deepseek.com",
            "dashscope.aliyuncs.com",
        ]
    )

    # ===== JWT / 认证 =====
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    DEV_TEST_ACCOUNTS_ENABLED: bool = Field(
        default=False,
        description="是否启用 configs/test-accounts.yaml 中的测试账号登录",
    )
    TEST_ACCOUNTS_FILE: str = Field(
        default="test-accounts.yaml",
        description="测试账号配置文件（相对 CONFIG_BASE_PATH）",
    )

    # ===== 企业微信 =====
    WECOM_CORP_ID: str = ""
    WECOM_AGENT_ID: str = ""
    WECOM_SECRET: str = ""
    WECOM_ENCODING_AES_KEY: str = ""
    WECOM_TOKEN: str = ""
    WECOM_BOT_CALLBACK_TOKEN: str = ""
    WECOM_BOT_CALLBACK_ENCODING_AES_KEY: str = ""

    # ===== 凭据保险箱（AES-256-GCM） =====
    CREDENTIAL_VAULT_KEY: str = "dev-vault-key-change-in-production-32b!"

    # ===== Gateway 通信 =====
    GATEWAY_HOST: str = "gateway"
    GATEWAY_PORT: int = 3100
    GATEWAY_API_URL: str = "http://gateway:3100"

    # ===== 配置管理器 =====
    CONFIG_MODE: str = "file_system"
    CONFIG_BASE_PATH: str = "/app/configs"
    CONFIG_WATCH_ENABLED: bool = True
    CONFIG_RELOAD_INTERVAL: int = 5

    # ===== Agent Router =====
    AGENT_ROUTER_SESSION_AFFINITY_TTL: int = 1800
    AGENT_ROUTER_SEMANTIC_TOP_K: int = 5
    AGENT_ROUTER_DEFAULT_AGENT: str = "default-agent"

    # ===== Skills =====
    SKILLS_RETRIEVAL_TOP_N: int = 50
    SKILLS_RANKING_TOP_K: int = 10
    SKILLS_CACHE_TTL: int = 300
    SKILLS_CACHE_MAX_SIZE: int = 500

    # ===== 速率限制 =====
    RATE_LIMIT_PER_USER_PER_MINUTE: int = 30
    RATE_LIMIT_PER_DEPARTMENT_PER_MINUTE: int = 200

    # ===== HITL（人机协同） =====
    HITL_APPROVAL_TIMEOUT_SECONDS: int = 300
    HITL_MAX_PENDING_PER_USER: int = 5

    # ===== Agent Memory =====
    AGENT_MEMORY_DYNAMIC_ENABLED: bool = True
    AGENT_MEMORY_TOP_K: int = 5
    AGENT_MEMORY_TTL_DAYS: int = 30
    AGENT_MEMORY_MAX_PER_USER: int = 200

    # ===== APScheduler =====
    SCHEDULER_TIMEZONE: str = "Asia/Shanghai"
    SCHEDULER_JOBSTORE_URL: str = ""

    # ===== Sentry / Tracing（可选） =====
    SENTRY_DSN: str = ""
    JAEGER_AGENT_HOST: str = ""
    JAEGER_AGENT_PORT: int = 6831

    # ===== 属性验证器 =====

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Any) -> list[str]:
        """从逗号分隔字符串或列表中解析 CORS Origins。"""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v

    @field_validator("OUTBOUND_PROXY_ALLOWED_DOMAINS", mode="before")
    @classmethod
    def parse_allowed_domains(cls, v: Any) -> list[str]:
        """从逗号分隔字符串或列表中解析允许的域名。"""
        if isinstance(v, str):
            return [domain.strip() for domain in v.split(",") if domain.strip()]
        return v

    # ===== 派生属性 =====

    @property
    def postgres_dsn(self) -> str:
        """异步 PostgreSQL 连接字符串。"""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def postgres_dsn_sync(self) -> str:
        """同步 PostgreSQL 连接字符串（用于 Alembic 迁移）。"""
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def redis_url(self) -> str:
        """Redis 连接 URL。"""
        if self.REDIS_PASSWORD:
            return (
                f"redis://:{self.REDIS_PASSWORD}"
                f"@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
            )
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def qdrant_url(self) -> str:
        """Qdrant 服务 URL。"""
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    @property
    def outbound_proxy_url(self) -> str:
        """LLM API 请求的出站代理 URL。"""
        return f"http://{self.OUTBOUND_PROXY_HOST}:{self.OUTBOUND_PROXY_PORT}"

    @property
    def is_production(self) -> bool:
        """检查是否在生产环境中运行。"""
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        """检查是否在开发环境中运行。"""
        return self.ENVIRONMENT == Environment.DEVELOPMENT


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    返回缓存的 Settings 实例。

    使用 lru_cache 确保每个进程仅加载一次配置。
    在应用的任何地方调用 get_settings() 即可访问配置。
    """
    return Settings()
