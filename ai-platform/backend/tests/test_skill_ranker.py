"""Tests for backend/src/skills/ranker.py — Stage-2 skill ranking engine."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src.identity.models import UserContext
from src.skills.models import Skill, SkillCategory, SkillScore
from src.skills.ranker import SkillRanker


@pytest.fixture
def ranker():
    """Return a SkillRanker without a permission engine (no filtering)."""
    return SkillRanker(permission_engine=None, default_top_k=5)


@pytest.fixture
def ranker_with_perm():
    """Return a SkillRanker with a mock permission engine."""
    perm_engine = MagicMock()
    perm_engine.check_permission = MagicMock(return_value=True)
    return SkillRanker(permission_engine=perm_engine, default_top_k=5)


def _make_score(
    skill_id: str,
    semantic: float = 0.5,
    call_count: int = 0,
    last_called_at: datetime | None = None,
    category: str = SkillCategory.HR,
    priority: float = 1.0,
) -> SkillScore:
    """Create a SkillScore with given parameters."""
    skill = Skill(
        skill_id=skill_id,
        name=f"Skill {skill_id}",
        category=category,
        call_count=call_count,
        last_called_at=last_called_at,
        priority=priority,
    )
    return SkillScore(skill=skill, semantic_similarity=semantic)


class TestPermissionFiltering:
    """Permission filtering removes skills the user cannot invoke."""

    async def test_filter_removes_denied_skills(self):
        """Skills denied by the permission engine should be removed."""
        perm_engine = MagicMock()
        perm_engine.check_permission = MagicMock(side_effect=[True, False, True])

        ranker = SkillRanker(permission_engine=perm_engine)
        candidates = [_make_score("s1"), _make_score("s2"), _make_score("s3")]
        user = UserContext(user_id="u001", username="alice")

        filtered = await ranker.filter_by_permission(candidates, user)
        assert len(filtered) == 2
        assert filtered[0].skill.skill_id == "s1"
        assert filtered[1].skill.skill_id == "s3"

    async def test_no_permission_engine_passes_all(self, ranker):
        """Without a permission engine, all candidates should pass."""
        candidates = [_make_score("s1"), _make_score("s2")]
        user = UserContext(user_id="u001", username="alice")
        filtered = await ranker.filter_by_permission(candidates, user)
        assert len(filtered) == 2


class TestReranking:
    """Reranking computes composite scores and sorts by them."""

    def test_rerank_sorts_by_composite_score(self, ranker):
        """Skills should be sorted by descending composite score."""
        now = datetime.now(timezone.utc)
        candidates = [
            _make_score("low", semantic=0.1),
            _make_score("high", semantic=0.9),
            _make_score("mid", semantic=0.5),
        ]
        user = UserContext(user_id="u001", username="alice")

        result = ranker.rerank(candidates, user, "test query")
        assert result[0].skill.skill_id == "high"
        assert result[1].skill.skill_id == "mid"
        assert result[2].skill.skill_id == "low"

    def test_rerank_empty_candidates(self, ranker):
        """Reranking empty list should return empty list."""
        user = UserContext(user_id="u001", username="alice")
        result = ranker.rerank([], user, "query")
        assert result == []

    def test_composite_score_weights(self, ranker):
        """Verify the 0.5×semantic + 0.2×frequency + 0.15×recency + 0.15×category formula."""
        now = datetime.now(timezone.utc)
        # All sub-scores at 1.0 → composite should be 1.0
        candidate = _make_score("perfect", semantic=1.0, call_count=10, last_called_at=now)
        candidates = [_make_score("max_calls", call_count=10, last_called_at=now), candidate]
        user = UserContext(
            user_id="u001",
            username="alice",
            allowed_categories=[SkillCategory.HR],
        )
        ranker.rerank(candidates, user, "query")
        # candidate has semantic=1.0, usage_frequency=1.0 (10/10),
        # recency_bonus≈1.0 (just called), category_match=1.0
        # composite = 0.5*1.0 + 0.2*1.0 + 0.15*~1.0 + 0.15*1.0 ≈ 1.0
        assert candidate.score > 0.9

    def test_recency_bonus_decay(self, ranker):
        """Skills called long ago should have lower recency bonus."""
        now = datetime.now(timezone.utc)
        recent = _make_score("recent", semantic=0.5, last_called_at=now)
        old = _make_score(
            "old",
            semantic=0.5,
            last_called_at=now - timedelta(days=60),
        )
        user = UserContext(user_id="u001", username="alice")
        ranker.rerank([recent, old], user, "query")
        assert recent.recency_bonus > old.recency_bonus
        assert recent.score > old.score

    def test_category_match_bonus(self, ranker):
        """Skills in user's preferred categories should get a bonus."""
        cat_match = _make_score("match", semantic=0.5, category=SkillCategory.HR)
        cat_no_match = _make_score("no_match", semantic=0.5, category=SkillCategory.FINANCE)
        user = UserContext(
            user_id="u001",
            username="alice",
            allowed_categories=[SkillCategory.HR],
        )
        ranker.rerank([cat_match, cat_no_match], user, "query")
        assert cat_match.category_match == 1.0
        assert cat_no_match.category_match == 0.0
        assert cat_match.score > cat_no_match.score


class TestDynamicK:
    """Dynamic K selection based on query complexity."""

    def test_simple_query_k5(self, ranker):
        """Short, single-intent query → K=5."""
        assert SkillRanker._compute_dynamic_k("hello") == 5

    def test_medium_query_k10(self):
        """20-80 char query → K=10."""
        query = "a" * 50  # 50 chars
        assert SkillRanker._compute_dynamic_k(query) == 10

    def test_complex_query_k20(self):
        """>80 char query → K=20."""
        query = "a" * 100
        assert SkillRanker._compute_dynamic_k(query) == 20

    def test_multi_step_query_k20(self):
        """Query with multi-step markers → K=20 regardless of length."""
        query = "查询并然后分析"  # short but has 然后
        assert SkillRanker._compute_dynamic_k(query) == 20

    def test_multi_condition_query_k10(self):
        """Query with 2+ condition markers → K=10."""
        query = "查询A和B、C"  # has 和 and 、
        assert SkillRanker._compute_dynamic_k(query) == 10


class TestRankIntegration:
    """End-to-end rank() tests combining all stages."""

    async def test_rank_returns_top_k(self, ranker):
        """rank() should return at most top_k skills."""
        candidates = [_make_score(f"s{i}", semantic=0.1 * i) for i in range(1, 21)]
        user = UserContext(user_id="u001", username="alice")
        result = await ranker.rank(candidates, user, "hello")
        assert len(result) <= 5  # default K for simple query

    async def test_rank_with_explicit_top_k(self, ranker):
        """rank() should respect explicit top_k override."""
        candidates = [_make_score(f"s{i}", semantic=0.1 * i) for i in range(1, 21)]
        user = UserContext(user_id="u001", username="alice")
        result = await ranker.rank(candidates, user, "hello", top_k=3)
        assert len(result) == 3

    async def test_rank_returns_skill_objects(self, ranker):
        """rank() should return Skill objects, not SkillScore."""
        candidates = [_make_score("s1", semantic=0.9)]
        user = UserContext(user_id="u001", username="alice")
        result = await ranker.rank(candidates, user, "hello")
        assert len(result) == 1
        assert isinstance(result[0], Skill)

    async def test_rank_empty_candidates(self, ranker):
        """rank() with no candidates should return empty list."""
        user = UserContext(user_id="u001", username="alice")
        result = await ranker.rank([], user, "hello")
        assert result == []
