"""ConfigValidator — 在激活前验证 agent 配置。

确保 agent.yaml 及其所有子配置文件符合所需的 schema。
返回的验证错误列表可以展示给操作员或记录到日志。
"""

from __future__ import annotations
from typing import Any


from src.agent.config import AgentConfig
from src.utils.exceptions import ConfigValidationError
from src.utils.logging import get_logger

logger = get_logger("config_manager.validator")


class ConfigValidator:
    """
    验证 Agent 配置对象。

    检查项：
    - 必填字段（agent_id、name、display_name）
    - 运行时类型是否受支持（openharness、custom、langgraph）
    - 模型名称非空
    - routing keywords 为列表
    - 记忆配置有效
    - MCP server 配置包含必填字段
    """

    SUPPORTED_RUNTIME_TYPES: set[str] = {"openharness", "custom", "langgraph"}
    SUPPORTED_MODEL_STRATEGIES: set[str] = {
        "default-primary",
        "always-fallback",
        "complex-to-fallback",
    }

    def validate(self, config: AgentConfig) -> list[str]:
        """
        验证 AgentConfig 并返回错误列表。

        Args:
            config: 要验证的 AgentConfig。

        Returns:
            错误消息列表。空列表表示验证通过。
        """
        errors: list[str] = []

        # 必填字段
        if not config.agent_id:
            errors.append("agent_id is required")
        if not config.name:
            errors.append("name is required")
        if not config.display_name:
            errors.append("display_name is required")

        # 运行时验证
        if config.runtime:
            if config.runtime.type not in self.SUPPORTED_RUNTIME_TYPES:
                errors.append(
                    f"Unsupported runtime type: {config.runtime.type}. "
                    f"Supported: {self.SUPPORTED_RUNTIME_TYPES}"
                )
            if config.runtime.params:
                max_steps: Skill | None = config.runtime.params.get("maxSteps", 20)
                if not isinstance(max_steps, int) or max_steps < 1:
                    errors.append("runtime.params.maxSteps must be a positive integer")

                temperature: Skill | None = config.runtime.params.get("temperature", 0.7)
                if not isinstance(temperature, (int, float)) or temperature < 0 or temperature > 2:
                    errors.append("runtime.params.temperature must be between 0 and 2")

                max_tokens: Skill | None = config.runtime.params.get("maxTokens", 4096)
                if not isinstance(max_tokens, int) or max_tokens < 1:
                    errors.append("runtime.params.maxTokens must be a positive integer")

        # 模型验证
        if config.model:
            if not config.model.primary:
                errors.append("model.primary is required")
            if not config.model.fallback:
                errors.append("model.fallback is required")
            if config.model.strategy not in self.SUPPORTED_MODEL_STRATEGIES:
                errors.append(
                    f"Unknown model strategy: {config.model.strategy}. "
                    f"Supported: {self.SUPPORTED_MODEL_STRATEGIES}"
                )

        # 路由验证
        if config.routing:
            if not isinstance(config.routing.keywords, list):
                errors.append("routing.keywords must be a list")
            if not isinstance(config.routing.priority, int):
                errors.append("routing.priority must be an integer")

        # 记忆验证
        if config.memory and config.memory.dynamic_enabled:
            if config.memory.top_k < 1:
                errors.append("memory.dynamic.top_k must be >= 1")
            if config.memory.ttl_days < 1:
                errors.append("memory.dynamic.ttl_days must be >= 1")
            if config.memory.max_per_user < 1:
                errors.append("memory.dynamic.max_per_user must be >= 1")

        # MCP server 验证
        for i, mcp in enumerate(config.mcp_servers):
            if not mcp.name:
                errors.append(f"mcp_servers[{i}].name is required")
            if mcp.transport not in ("stdio", "http", "sse"):
                errors.append(
                    f"mcp_servers[{i}].transport must be stdio, http, or sse"
                )
            if mcp.transport == "http" and not mcp.endpoint:
                errors.append(f"mcp_servers[{i}].endpoint is required for http transport")
            if mcp.transport == "stdio" and not mcp.command:
                errors.append(f"mcp_servers[{i}].command is required for stdio transport")

        # 推送验证
        if config.push and config.push.enabled:
            if not config.push.channels:
                errors.append("push.channels must not be empty when push is enabled")
            for schedule in config.push.schedules:
                if "cron" not in schedule:
                    errors.append("push.schedules must have a 'cron' field")
                if "template" not in schedule:
                    errors.append("push.schedules must have a 'template' field")

        # 访问控制验证
        if config.access_control:
            if not isinstance(config.access_control.departments, list):
                errors.append("access_control.departments must be a list")
            if not isinstance(config.access_control.roles, list):
                errors.append("access_control.roles must be a list")

        return errors

    def validate_or_raise(self, config: AgentConfig) -> None:
        """
        验证并在无效时抛出 ConfigValidationError。

        Args:
            config: 要验证的 AgentConfig。

        Raises:
            ConfigValidationError: 验证失败时抛出。
        """
        errors: list[str] = self.validate(config)
        if errors:
            raise ConfigValidationError(errors)

    def validate_yaml_dict(self, data: dict[str, Any]) -> list[str]:
        """在解析为 AgentConfig 之前验证原始 YAML 字典。"""
        errors: list[str] = []
        agent_section: Skill | None = data.get("agent", data)

        if not agent_section.get("name"):
            errors.append("agent.name is required")
        if not agent_section.get("display_name"):
            errors.append("agent.display_name is required")

        # 在文件模式下检查 includes 引用的文件是否存在
        includes: Skill | None = agent_section.get("includes", {})
        for ref_name, ref_path in includes.items():
            if not isinstance(ref_path, str):
                errors.append(f"agent.includes.{ref_name} must be a string path")

        return errors


# 单例实例
_config_validator: ConfigValidator | None = None


def get_config_validator() -> ConfigValidator:
    """返回单例 ConfigValidator 实例。"""
    global _config_validator
    if _config_validator is None:
        _config_validator = ConfigValidator()
    return _config_validator
