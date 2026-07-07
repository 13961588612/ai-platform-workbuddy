"""Tests for backend/src/llm/gateway.py — LLM gateway with failover and key rotation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.llm.gateway import LLMGateway
from src.llm.models import LLMMessage, LLMRequest, LLMResponse, TokenUsage
from src.utils.exceptions import FailoverExhaustedError, LLMProviderError, QuotaExceededError


@pytest.fixture
def gateway():
    """Return an LLMGateway with all sub-managers mocked."""
    gw = LLMGateway()

    # Mock all sub-managers
    gw._key_manager = MagicMock()
    gw._key_manager.get_key = MagicMock(return_value=MagicMock(key="test-key"))
    gw._key_manager.record_success = MagicMock()
    gw._key_manager.record_error = MagicMock()
    gw._key_manager.mark_key_invalid = MagicMock()
    gw._key_manager.get_healthy_key_count = MagicMock(return_value=1)
    gw._key_manager.get_key_stats = MagicMock(return_value=[])

    gw._quota_manager = MagicMock()
    gw._quota_manager.check_quota = AsyncMock(return_value=True)
    gw._quota_manager.record_usage = AsyncMock()

    gw._proxy_manager = MagicMock()
    gw._proxy_manager.check_domain = MagicMock(return_value=True)
    gw._proxy_manager.get_pool_status = MagicMock(return_value=[])

    gw._token_tracker = MagicMock()
    gw._token_tracker.record = AsyncMock()

    gw._failover_manager = MagicMock()
    gw._failover_manager.get_active_provider = MagicMock(return_value="deepseek")
    gw._failover_manager.get_failover_providers = MagicMock(return_value=["deepseek", "qwen"])
    gw._failover_manager.record_success = MagicMock()
    gw._failover_manager.record_failure = MagicMock()
    gw._failover_manager.get_status = MagicMock(return_value={})

    gw._initialized = True
    return gw


def _make_request(model="deepseek-v4-flash") -> LLMRequest:
    """Create a minimal LLMRequest."""
    return LLMRequest(
        messages=[LLMMessage(role="user", content="Hello")],
        model=model,
        user_id="u001",
        session_id="sess-1",
    )


def _make_response(model="deepseek-v4-flash") -> LLMResponse:
    """Create a minimal LLMResponse."""
    return LLMResponse(
        content="Hi there!",
        model=model,
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


class TestProviderSelection:
    """Test _select_provider based on model name."""

    def test_select_deepseek(self, gateway):
        """Model name containing 'deepseek' should select deepseek provider."""
        assert gateway._select_provider("deepseek-v4-flash") == "deepseek"

    def test_select_qwen(self, gateway):
        """Model name containing 'qwen' should select qwen provider."""
        assert gateway._select_provider("qwen3.6-plus") == "qwen"

    def test_select_default(self, gateway):
        """Unknown model name should fall back to active provider."""
        gateway._failover_manager.get_active_provider = MagicMock(return_value="deepseek")
        assert gateway._select_provider("unknown-model") == "deepseek"


class TestChatSuccess:
    """Test successful chat completion."""

    async def test_chat_success(self, gateway):
        """A successful chat call should return LLMResponse and track usage."""
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value=_make_response())
        gateway._adapters = {"deepseek": mock_adapter, "qwen": MagicMock()}

        request = _make_request()
        response = await gateway.chat(request)

        assert response.content == "Hi there!"
        gateway._failover_manager.record_success.assert_called_once_with("deepseek")
        gateway._token_tracker.record.assert_called_once()
        gateway._quota_manager.record_usage.assert_called_once()

    async def test_chat_checks_quota_first(self, gateway):
        """chat() should check quota before making the LLM call."""
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value=_make_response())
        gateway._adapters = {"deepseek": mock_adapter, "qwen": MagicMock()}

        await gateway.chat(_make_request())
        gateway._quota_manager.check_quota.assert_called_once()

    async def test_chat_domain_whitelist_check(self, gateway):
        """chat() should check domain whitelist via proxy manager."""
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value=_make_response())
        gateway._adapters = {"deepseek": mock_adapter, "qwen": MagicMock()}

        await gateway.chat(_make_request())
        gateway._proxy_manager.check_domain.assert_called()


class TestFailover:
    """Test failover behavior when primary provider fails."""

    async def test_failover_to_fallback(self, gateway):
        """When primary fails, should try fallback provider."""
        deepseek_adapter = MagicMock()
        deepseek_adapter.chat = AsyncMock(
            side_effect=LLMProviderError("deepseek", "Connection refused")
        )
        qwen_adapter = MagicMock()
        qwen_adapter.chat = AsyncMock(return_value=_make_response("qwen3.6-plus"))

        gateway._adapters = {"deepseek": deepseek_adapter, "qwen": qwen_adapter}

        response = await gateway.chat(_make_request())

        assert response.content == "Hi there!"
        gateway._failover_manager.record_failure.assert_called_with(
            "deepseek", "LLM provider error [deepseek]: Connection refused"
        )
        gateway._failover_manager.record_success.assert_called_with("qwen")

    async def test_all_providers_fail_raises(self, gateway):
        """When all providers fail, should raise FailoverExhaustedError."""
        deepseek_adapter = MagicMock()
        deepseek_adapter.chat = AsyncMock(
            side_effect=LLMProviderError("deepseek", "Error 1")
        )
        qwen_adapter = MagicMock()
        qwen_adapter.chat = AsyncMock(
            side_effect=LLMProviderError("qwen", "Error 2")
        )

        gateway._adapters = {"deepseek": deepseek_adapter, "qwen": qwen_adapter}

        with pytest.raises(FailoverExhaustedError):
            await gateway.chat(_make_request())

    async def test_quota_exceeded_raises(self, gateway):
        """When quota is exceeded, should raise QuotaExceededError."""
        gateway._quota_manager.check_quota = AsyncMock(
            side_effect=QuotaExceededError("Quota exceeded")
        )

        with pytest.raises(QuotaExceededError):
            await gateway.chat(_make_request())


class TestKeyRotation:
    """Test API key rotation behavior."""

    async def test_key_selected_per_call(self, gateway):
        """Each call should select a key via the key manager."""
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value=_make_response())
        gateway._adapters = {"deepseek": mock_adapter, "qwen": MagicMock()}

        await gateway.chat(_make_request())
        gateway._key_manager.get_key.assert_called_with("deepseek")

    async def test_key_success_recorded(self, gateway):
        """On success, key success should be recorded."""
        mock_adapter = MagicMock()
        mock_adapter.chat = AsyncMock(return_value=_make_response())
        gateway._adapters = {"deepseek": mock_adapter, "qwen": MagicMock()}

        await gateway.chat(_make_request())
        gateway._key_manager.record_success.assert_called_with("deepseek", "test-key")

    async def test_auth_failure_marks_key_invalid(self, gateway):
        """On 401/403 (Authentication failed), key should be marked invalid."""
        deepseek_adapter = MagicMock()
        deepseek_adapter.chat = AsyncMock(
            side_effect=LLMProviderError("deepseek", "Authentication failed: 401")
        )
        qwen_adapter = MagicMock()
        qwen_adapter.chat = AsyncMock(return_value=_make_response())

        gateway._adapters = {"deepseek": deepseek_adapter, "qwen": qwen_adapter}

        await gateway.chat(_make_request())
        gateway._key_manager.mark_key_invalid.assert_called_with(
            "deepseek", "test-key",
            "LLM provider error [deepseek]: Authentication failed: 401",
        )


class TestTokenTracking:
    """Test token usage tracking after LLM calls."""

    async def test_token_usage_tracked(self, gateway):
        """After a successful call, token usage should be recorded."""
        mock_adapter = MagicMock()
        response = _make_response()
        mock_adapter.chat = AsyncMock(return_value=response)
        gateway._adapters = {"deepseek": mock_adapter, "qwen": MagicMock()}

        await gateway.chat(_make_request())

        gateway._token_tracker.record.assert_called_once()
        call_kwargs = gateway._token_tracker.record.call_args
        assert call_kwargs.kwargs["usage"].total_tokens == 15

    async def test_quota_usage_recorded(self, gateway):
        """After a successful call, actual quota usage should be recorded."""
        mock_adapter = MagicMock()
        response = _make_response()
        mock_adapter.chat = AsyncMock(return_value=response)
        gateway._adapters = {"deepseek": mock_adapter, "qwen": MagicMock()}

        await gateway.chat(_make_request())

        gateway._quota_manager.record_usage.assert_called_once_with(
            "u001", "", 15
        )


class TestGatewayStatus:
    """Test get_status() for monitoring."""

    def test_get_status(self, gateway):
        """get_status should return a dict with initialized, failover, proxy, providers."""
        status = gateway.get_status()
        assert "initialized" in status
        assert "failover" in status
        assert "proxy_pool" in status
        assert "providers" in status
        assert "deepseek" in status["providers"]
        assert "qwen" in status["providers"]
