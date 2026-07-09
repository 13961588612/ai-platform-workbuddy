"""AgentConfig 数据模型 — Agent 实例的完整配置。

包含运行时、模型、skills、MCP 服务器、访问控制、推送、
记忆和路由配置等部分。
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class RuntimeConfig(BaseModel):
    """Agent 的运行时类型与参数。"""

    type: str = Field(default="openharness", description="运行时类型：openharness | custom | langgraph")
    version: str = Field(default="1.0.0")
    params: dict[str, Any] = Field(
        default_factory=lambda: {
            "maxSteps": 20,
            "temperature": 0.7,
            "maxTokens": 4096,
        }
    )
    prompts: dict[str, str] = Field(default_factory=dict)
    middleware: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(
        default_factory=list,
        description="OpenHarness 工具白名单；支持 glob（如 mcp__*）。空则使用平台默认 skill + mcp__*",
    )


class ModelConfig(BaseModel):
    """Agent 的 LLM 模型配置。"""

    primary: str = Field(default="deepseek-v4-flash", description="主模型")
    fallback: str = Field(default="qwen3.6-plus", description="回退模型")
    strategy: str = Field(default="default-primary", description="模型选择策略")
    gateway: str = Field(default="llm-gateway", description="LLM gateway 引用")


class SkillRef(BaseModel):
    """Agent 配置中对一个 Skill 的引用。"""

    skill_id: str
    enabled: bool = True
    overrides: dict[str, Any] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    """MCP Server 连接配置。"""

    name: str
    transport: str = Field(default="stdio", description="传输方式：stdio | http | sse")
    endpoint: str = ""
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    enabled: bool = True


class AccessControl(BaseModel):
    """Agent 的访问控制配置。"""

    departments: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    skill_permissions: dict[str, list[str]] = Field(default_factory=dict)
    sensitive_ops: list[dict[str, Any]] = Field(default_factory=list)


class PushConfig(BaseModel):
    """Agent 的主动推送配置。"""

    enabled: bool = False
    channels: list[str] = Field(default_factory=list)
    schedules: list[dict[str, Any]] = Field(default_factory=list)


class MemoryConfig(BaseModel):
    """Agent 记忆配置（v1.4）。"""

    static_enabled: bool = True
    personality_file: str = "memory/personality.md"
    facts_dir: str = "memory/facts/"
    dynamic_enabled: bool = True
    collection: str = "agent_memory_index"
    top_k: int = 5
    write_back: bool = True
    ttl_days: int = 30
    max_per_user: int = 200


class RoutingConfig(BaseModel):
    """Agent 的 AgentRouter 路由配置。"""

    keywords: list[str] = Field(default_factory=list)
    enabled: bool = True
    priority: int = 10


class AgentMetadata(BaseModel):
    """用于 AgentRouter 语义搜索的 Agent 元数据。"""

    name: str
    display_name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    version: str = "1.0.0"
    enabled: bool = True
    capabilities: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    """
    Agent 实例的完整配置。

    由 ConfigLoader 从 configs/agents/{agent_name}/agent.yaml 加载。
    包含运行一个 Agent 所需的所有子配置。
    """

    agent_id: str = Field(..., description="Agent ID（等于目录名）")
    name: str = Field(..., description="显示名称")
    display_name: str = Field(default="", description="UI 显示名称")
    description: str = Field(default="")
    version: str = Field(default="1.0.0")
    tags: list[str] = Field(default_factory=list)

    # Sub-configurations
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    model: ModelConfig = Field(default_factory=ModelConfig)
    system_prompt: str = Field(default="")
    skills: list[SkillRef] = Field(default_factory=list)
    mcp_servers: list[MCPServerConfig] = Field(default_factory=list)
    access_control: AccessControl = Field(default_factory=AccessControl)
    push: PushConfig = Field(default_factory=PushConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    metadata: AgentMetadata | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # File references (for FILE_SYSTEM mode)
    includes: dict[str, str] = Field(default_factory=dict)
    config_path: str = ""

    @classmethod
    def from_yaml_dict(cls, data: dict[str, Any]) -> AgentConfig:
        """
        从已解析的 agent.yaml 字典创建 AgentConfig。

        处理配置文件中的嵌套 YAML 结构。
        """
        agent_section: Skill | None = data.get("agent", data)

        # Parse runtime section
        runtime_data: Skill | None = agent_section.get("runtime", data.get("runtime", {}))
        runtime: RuntimeConfig = RuntimeConfig(
            type=runtime_data.get("type", "openharness"),
            version=runtime_data.get("version", "1.0.0"),
            params=runtime_data.get("params", {}),
            prompts=runtime_data.get("prompts", {}),
            middleware=runtime_data.get("middleware", {}),
            allowed_tools=list(runtime_data.get("allowed_tools", []) or []),
        )

        # Parse model section
        model_data: Skill | None = agent_section.get("model", data.get("model", {}))
        model: ModelConfig = ModelConfig(
            primary=model_data.get("primary", "deepseek-v4-flash"),
            fallback=model_data.get("fallback", "qwen3.6-plus"),
            strategy=model_data.get("strategy", "default-primary"),
            gateway=model_data.get("gateway", "llm-gateway"),
        )

        # Parse routing section
        routing_data: Skill | None = agent_section.get("routing", data.get("routing", {}))
        routing: RoutingConfig = RoutingConfig(
            keywords=routing_data.get("keywords", []),
            enabled=routing_data.get("enabled", True),
            priority=routing_data.get("priority", 10),
        )

        # Parse memory section
        memory_data: Skill | None = agent_section.get("memory", data.get("memory", {}))
        static_data: Skill | None = memory_data.get("static", {})
        dynamic_data: Skill | None = memory_data.get("dynamic", {})
        memory: MemoryConfig = MemoryConfig(
            static_enabled=static_data.get("enabled", True),
            personality_file=static_data.get("personality", "memory/personality.md"),
            facts_dir=static_data.get("facts_dir", "memory/facts/"),
            dynamic_enabled=dynamic_data.get("enabled", True),
            collection=dynamic_data.get("collection", "agent_memory_index"),
            top_k=dynamic_data.get("top_k", 5),
            write_back=dynamic_data.get("write_back", True),
            ttl_days=dynamic_data.get("ttl_days", 30),
            max_per_user=dynamic_data.get("max_per_user", 200),
        )

        # Parse includes
        includes: Skill | None = agent_section.get("includes", {})

        # Parse enabled skills (from skills/enabled-skills.yaml merged by ConfigLoader)
        skills: list[SkillRef] = []
        skills_data: Skill | None = data.get("skills", agent_section.get("skills", {}))
        enabled_list: Skill | None | list[Any] = skills_data.get("enabled", []) if isinstance(skills_data, dict) else []
        for item in enabled_list:
            if not isinstance(item, dict) or not item.get("skill_id"):
                continue
            skills.append(
                SkillRef(
                    skill_id=item["skill_id"],
                    enabled=item.get("enabled", True),
                    overrides=item.get("overrides", {}),
                )
            )

        # Parse MCP servers (from system/mcp-servers.yaml merged by ConfigLoader)
        mcp_servers: list[MCPServerConfig] = []
        for entry in data.get("mcp_servers", agent_section.get("mcp_servers", [])):
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            transport: str = str(entry.get("transport", "stdio")).lower()
            if transport in ("streamable_http", "streamable-http"):
                transport: str = "http"
            mcp_servers.append(
                MCPServerConfig(
                    name=entry["name"],
                    transport=transport,
                    endpoint=entry.get("endpoint", ""),
                    command=entry.get("command", ""),
                    args=list(entry.get("args", []) or []),
                    env=dict(entry.get("env", {}) or {}),
                    enabled=entry.get("enabled", True),
                )
            )

        system_prompt: Skill | None = data.get("system_prompt", agent_section.get("system_prompt", ""))

        return cls(
            agent_id=agent_section.get("name", ""),
            name=agent_section.get("name", ""),
            display_name=agent_section.get("display_name", agent_section.get("name", "")),
            description=agent_section.get("description", ""),
            version=agent_section.get("version", "1.0.0"),
            tags=agent_section.get("tags", []),
            runtime=runtime,
            model=model,
            system_prompt=system_prompt,
            skills=skills,
            mcp_servers=mcp_servers,
            routing=routing,
            memory=memory,
            includes=includes,
        )
