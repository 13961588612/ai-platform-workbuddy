"""Shared pytest fixtures and configuration for the AI Platform backend tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Ensure backend/ is on sys.path so `from src.xxx import yyy` works
_backend_root = Path(__file__).resolve().parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# Clear the lru_cache on get_settings before any test runs
from src.config import get_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture
def settings():
    """Return a fresh Settings instance (defaults are test-safe)."""
    from src.config import get_settings as _gs
    _gs.cache_clear()
    return _gs()


@pytest.fixture
def mock_redis():
    """Return a mock async Redis client."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.setex = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    redis.incrby = AsyncMock(return_value=1)
    redis.expire = AsyncMock(return_value=True)
    return redis


@pytest.fixture
def make_skill():
    """Factory fixture for creating Skill instances."""
    from src.skills.models import Skill, SkillCategory, SkillStatus

    def _make(
        skill_id: str = "test-skill",
        name: str = "Test Skill",
        category: str = SkillCategory.BUILT_IN,
        call_count: int = 0,
        last_called_at=None,
        priority: float = 1.0,
    ):
        return Skill(
            skill_id=skill_id,
            name=name,
            description=f"Description for {name}",
            category=category,
            call_count=call_count,
            last_called_at=last_called_at,
            priority=priority,
        )

    return _make


@pytest.fixture
def make_user():
    """Factory fixture for creating UserContext instances."""
    from src.identity.models import UserContext

    def _make(
        user_id: str = "u001",
        username: str = "tester",
        roles: list[str] | None = None,
        dept_id: str | None = None,
        allowed_categories: list[str] | None = None,
        skill_allow_list: list[str] | None = None,
        skill_deny_list: list[str] | None = None,
    ):
        return UserContext(
            user_id=user_id,
            username=username,
            roles=roles or [],
            dept_id=dept_id,
            allowed_categories=allowed_categories or [],
            skill_allow_list=skill_allow_list or [],
            skill_deny_list=skill_deny_list or [],
        )

    return _make
