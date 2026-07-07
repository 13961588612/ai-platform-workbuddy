"""Tests for backend/src/router/agent_router.py — 4-level routing strategy chain."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.config import AgentConfig, RoutingConfig
from src.router.agent_router import AgentRouter
from src.router.models import RouteResult, SessionContext, UserRequest
from src.router.strategies.default_fallback import DefaultFallbackStrategy
from src.router.strategies.keyword_match import KeywordMatchStrategy
from src.router.strategies.session_affinity import SessionAffinityStrategy


def _make_agent(agent_id: str, keywords=None, enabled=True, priority=10) -> AgentConfig:
    """Create a minimal AgentConfig for routing tests."""
    return AgentConfig(
        agent_id=agent_id,
        name=agent_id,
        routing=RoutingConfig(
            keywords=keywords or [],
            enabled=enabled,
            priority=priority,
        ),
    )


def _make_request(text="hello", session_id="sess-1", user_id="u001") -> UserRequest:
    """Create a UserRequest for testing."""
    return UserRequest(text=text, session_id=session_id, user_id=user_id)


class TestStrategyChainOrder:
    """Verify the 4-level strategy chain is ordered by priority."""

    def test_strategies_sorted_by_priority(self):
        """Strategies should be ordered: session_affinity(1) → keyword(2) → semantic(3) → default(4)."""
        router = AgentRouter()
        strategies = router.get_strategies()
        priorities = [s.priority for s in strategies]
        assert priorities == sorted(priorities)
        assert strategies[0].name == "session_affinity"
        assert strategies[1].name == "keyword_matching"
        # strategies[2] is semantic_search (priority 3)
        assert strategies[3].name == "default_fallback"


class TestSessionAffinityRouting:
    """Session affinity strategy routes to previously-bound agent."""

    async def test_session_affinity_hit(self):
        """When a session has an agent binding, it should be used."""
        router = AgentRouter()
        router.set_candidates([_make_agent("hr-agent")])

        # Mock session_manager to return a binding
        router._session_manager = MagicMock()
        router._session_manager.get_agent_binding = AsyncMock(return_value="hr-agent")
        router._session_manager.set_agent_binding = AsyncMock()

        # Mock route_logger
        router._route_logger = MagicMock()
        router._route_logger.log_route = AsyncMock()

        # Also mock the strategy's Redis to return the binding
        with patch.object(SessionAffinityStrategy, "_get_redis") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value="hr-agent")
            mock_get_redis.return_value = mock_redis

            result = await router.route(_make_request())

        assert result.agent_id == "hr-agent"
        assert result.strategy_used == "session_affinity"
        assert result.confidence == 1.0

    async def test_session_affinity_miss_falls_through(self):
        """When no binding exists, should fall through to keyword or default."""
        router = AgentRouter()
        router.set_candidates([_make_agent("default-agent")])

        router._session_manager = MagicMock()
        router._session_manager.get_agent_binding = AsyncMock(return_value=None)
        router._session_manager.set_agent_binding = AsyncMock()

        router._route_logger = MagicMock()
        router._route_logger.log_route = AsyncMock()

        with patch.object(SessionAffinityStrategy, "_get_redis") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_get_redis.return_value = mock_redis

            result = await router.route(_make_request())

        # Should fall through to default_fallback
        assert result.strategy_used == "default_fallback"
        assert result.confidence == 0.0


class TestKeywordRouting:
    """Keyword match strategy routes based on keywords in user input."""

    async def test_keyword_match_hit(self):
        """When user input contains a keyword, the matching agent should be selected."""
        router = AgentRouter()
        router.set_candidates([
            _make_agent("hr-agent", keywords=["年假", "请假"]),
            _make_agent("finance-agent", keywords=["报销", "预算"]),
        ])

        router._session_manager = MagicMock()
        router._session_manager.get_agent_binding = AsyncMock(return_value=None)
        router._session_manager.set_agent_binding = AsyncMock()

        router._route_logger = MagicMock()
        router._route_logger.log_route = AsyncMock()

        with patch.object(SessionAffinityStrategy, "_get_redis") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_get_redis.return_value = mock_redis

            result = await router.route(_make_request(text="我想请年假"))

        assert result.agent_id == "hr-agent"
        assert result.strategy_used == "keyword_matching"
        assert result.confidence == 0.9

    async def test_keyword_match_priority_ordering(self):
        """Higher priority agent should be checked first for keyword match."""
        router = AgentRouter()
        router.set_candidates([
            _make_agent("low-priority", keywords=["查询"], priority=5),
            _make_agent("high-priority", keywords=["查询"], priority=20),
        ])

        router._session_manager = MagicMock()
        router._session_manager.get_agent_binding = AsyncMock(return_value=None)
        router._session_manager.set_agent_binding = AsyncMock()

        router._route_logger = MagicMock()
        router._route_logger.log_route = AsyncMock()

        with patch.object(SessionAffinityStrategy, "_get_redis") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_get_redis.return_value = mock_redis

            result = await router.route(_make_request(text="查询数据"))

        assert result.agent_id == "high-priority"


class TestDefaultFallback:
    """Default fallback strategy always returns a result."""

    async def test_default_fallback_returns_result(self):
        """When no other strategy matches, default_fallback should return."""
        router = AgentRouter()
        # No candidates with keywords, no session binding
        router.set_candidates([_make_agent("some-agent")])

        router._session_manager = MagicMock()
        router._session_manager.get_agent_binding = AsyncMock(return_value=None)
        router._session_manager.set_agent_binding = AsyncMock()

        router._route_logger = MagicMock()
        router._route_logger.log_route = AsyncMock()

        with patch.object(SessionAffinityStrategy, "_get_redis") as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_get_redis.return_value = mock_redis

            result = await router.route(_make_request(text="random text"))

        assert result is not None
        assert result.strategy_used == "default_fallback"
        assert result.confidence == 0.0

    async def test_default_fallback_always_applicable(self):
        """DefaultFallbackStrategy.is_applicable should always return True."""
        strategy = DefaultFallbackStrategy()
        req = _make_request()
        ctx = SessionContext(session_id="s1", user_id="u1", channel="web")
        assert strategy.is_applicable(req, ctx) is True

    async def test_default_fallback_always_returns(self):
        """DefaultFallbackStrategy.route should always return a RouteResult."""
        strategy = DefaultFallbackStrategy()
        req = _make_request()
        ctx = SessionContext(session_id="s1", user_id="u1", channel="web")
        result = await strategy.route(request=req, candidates=[], session_ctx=ctx)
        assert result is not None
        assert result.agent_id == strategy._default_agent_id


class TestCandidateManagement:
    """Test add/remove candidate operations."""

    def test_set_candidates(self):
        """set_candidates should replace the candidate list."""
        router = AgentRouter()
        agents = [_make_agent("a1"), _make_agent("a2")]
        router.set_candidates(agents)
        assert len(router._candidates) == 2

    def test_add_candidate(self):
        """add_candidate should append to the list."""
        router = AgentRouter()
        router.set_candidates([_make_agent("a1")])
        router.add_candidate(_make_agent("a2"))
        assert len(router._candidates) == 2

    def test_add_candidate_replaces_existing(self):
        """Adding a candidate with an existing agent_id should replace it."""
        router = AgentRouter()
        router.set_candidates([_make_agent("a1")])
        router.add_candidate(_make_agent("a1"))
        assert len(router._candidates) == 1

    def test_remove_candidate(self):
        """remove_candidate should remove the specified agent."""
        router = AgentRouter()
        router.set_candidates([_make_agent("a1"), _make_agent("a2")])
        router.remove_candidate("a1")
        assert len(router._candidates) == 1
        assert router._candidates[0].agent_id == "a2"


class TestKeywordMatchStrategy:
    """Direct tests for KeywordMatchStrategy."""

    def test_is_applicable_with_text(self):
        """is_applicable should return True when text is non-empty."""
        strategy = KeywordMatchStrategy()
        req = _make_request(text="hello")
        ctx = SessionContext(session_id="s1", user_id="u1", channel="web")
        assert strategy.is_applicable(req, ctx) is True

    def test_is_applicable_empty_text(self):
        """is_applicable should return False when text is empty/whitespace."""
        strategy = KeywordMatchStrategy()
        req = _make_request(text="   ")
        ctx = SessionContext(session_id="s1", user_id="u1", channel="web")
        assert strategy.is_applicable(req, ctx) is False

    def test_match_keywords_substring(self):
        """match_keywords does substring matching on pre-lowered text/keywords.

        Note: the caller (route method) is responsible for lowercasing both
        the user text and the keywords before calling this method.
        """
        strategy = KeywordMatchStrategy()
        assert strategy.match_keywords("hello world", ["hello"]) is True
        assert strategy.match_keywords("hello world", ["world"]) is True
        assert strategy.match_keywords("goodbye", ["hello"]) is False

    def test_match_keywords_empty_list(self):
        """Empty keyword list should return False."""
        strategy = KeywordMatchStrategy()
        assert strategy.match_keywords("hello", []) is False
