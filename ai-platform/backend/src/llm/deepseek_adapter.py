"""DeepSeekAdapter — 基于 OpenAI SDK 的 DeepSeek LLM API 适配器。"""

from __future__ import annotations

from src.config import get_settings
from src.llm.openai_sdk_adapter import OpenAISDKAdapter


class DeepSeekAdapter(OpenAISDKAdapter):
    """DeepSeek LLM API（deepseek-v4-flash）适配器，使用 OpenAI 兼容端点。"""

    PROVIDER_NAME: str = "deepseek"

    def __init__(self) -> None:
        settings = get_settings()
        super().__init__(
            base_url=settings.DEEPSEEK_API_ENDPOINT,
            timeout=settings.LLM_REQUEST_TIMEOUT,
        )
