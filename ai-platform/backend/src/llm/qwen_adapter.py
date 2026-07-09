"""QwenAdapter — 基于 OpenAI SDK 的通义千问 LLM API 适配器。"""

from __future__ import annotations

from src.config import get_settings
from src.llm.openai_sdk_adapter import OpenAISDKAdapter


class QwenAdapter(OpenAISDKAdapter):
    """Qwen LLM API（DashScope 兼容模式）适配器，使用 OpenAI 兼容端点。"""

    PROVIDER_NAME: str = "qwen"

    def __init__(self) -> None:
        """从配置加载 Qwen API 端点与超时并初始化 OpenAI SDK 客户端。"""
        settings = get_settings()
        super().__init__(
            base_url=settings.QWEN_API_ENDPOINT,
            timeout=settings.LLM_REQUEST_TIMEOUT,
        )
