"""Tests for backend/src/memory/manager.py — Agent memory two-phase retrieval & forgetting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.memory.manager import MemoryManager
from src.memory.models import ExtractedMemory, MemoryEntry, MemorySearchResult, MemoryType


@pytest.fixture
def mock_qdrant():
    """Return a mock AsyncQdrantClient."""
    client = AsyncMock()
    client.get_collections = AsyncMock(return_value=MagicMock(collections=[]))
    client.create_collection = AsyncMock()
    client.create_payload_index = AsyncMock()
    client.search = AsyncMock(return_value=[])
    client.upsert = AsyncMock()
    client.delete = AsyncMock()
    client.set_payload = AsyncMock()
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_static_loader():
    """Return a mock StaticMemoryLoader."""
    loader = MagicMock()
    loader.load = MagicMock(return_value="static memory text")
    loader.invalidate = MagicMock()
    loader.invalidate_all = MagicMock()
    loader.check_and_reload = MagicMock(return_value=False)
    return loader


@pytest.fixture
def manager(mock_qdrant, mock_static_loader):
    """Return a MemoryManager with mocked dependencies."""
    with patch("src.memory.manager.get_static_memory_loader", return_value=mock_static_loader):
        mgr = MemoryManager(
            static_loader=mock_static_loader,
            qdrant_client=mock_qdrant,
        )
    mgr._collection_ready = True  # skip ensure_collection
    return mgr


class TestStaticMemory:
    """Test static memory delegation."""

    def test_load_static_memory(self, manager, mock_static_loader):
        """load_static_memory should delegate to the static loader."""
        result = manager.load_static_memory("hr-assistant")
        assert result == "static memory text"
        mock_static_loader.load.assert_called_with("hr-assistant")

    def test_invalidate_static_cache_all(self, manager, mock_static_loader):
        """invalidate_static_cache() with no arg should clear all."""
        manager.invalidate_static_cache()
        mock_static_loader.invalidate_all.assert_called_once()

    def test_invalidate_static_cache_single(self, manager, mock_static_loader):
        """invalidate_static_cache(agent_name) should clear only that agent."""
        manager.invalidate_static_cache("hr-assistant")
        mock_static_loader.invalidate.assert_called_with("hr-assistant")


class TestTwoPhaseRetrieval:
    """Test the two-phase dynamic memory retrieval (user-level + session-level)."""

    async def test_retrieve_empty_query_returns_empty(self, manager):
        """An empty query should return an empty list."""
        result = await manager.retrieve_dynamic_memory(
            query="  ",
            agent_name="hr-assistant",
            user_id="u001",
        )
        assert result == []

    async def test_retrieve_user_level_only(self, manager, mock_qdrant):
        """When no session_id is given, only user-level memories are searched."""
        mock_qdrant.search = AsyncMock(return_value=[
            MagicMock(
                id="mem-1",
                score=0.9,
                payload={
                    "memory_id": "mem-1",
                    "agent_name": "hr-assistant",
                    "user_id": "u001",
                    "session_id": None,
                    "scope": "user",
                    "memory_type": "preference",
                    "content": "User prefers Chinese",
                    "importance": 0.8,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "expires_at": None,
                },
            ),
        ])

        with patch.object(manager, "_generate_embedding", return_value=[0.1] * 768):
            results = await manager.retrieve_dynamic_memory(
                query="user preferences",
                agent_name="hr-assistant",
                user_id="u001",
                session_id=None,
            )

        assert len(results) == 1
        assert results[0].entry.content == "User prefers Chinese"
        assert results[0].similarity == 0.9

    async def test_retrieve_session_level_isolation(self, manager, mock_qdrant):
        """Session-level memories should only match the given session_id."""
        call_count = 0

        async def mock_qdrant_search(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call = user-level (scope="user")
            # Second call = session-level (scope="session")
            if kwargs.get("scope") == "session":
                assert kwargs.get("session_id") == "sess-123"
                return [
                    {
                        "id": "mem-2",
                        "score": 0.85,
                        "payload": {
                            "memory_id": "mem-2",
                            "agent_name": "hr-assistant",
                            "user_id": "u001",
                            "session_id": "sess-123",
                            "scope": "session",
                            "memory_type": "context",
                            "content": "Session context",
                            "importance": 0.6,
                            "created_at": datetime.now(timezone.utc).isoformat(),
                            "expires_at": None,
                        },
                    },
                ]
            return []  # user-level returns empty

        with patch.object(manager, "_qdrant_search", side_effect=mock_qdrant_search):
            with patch.object(manager, "_generate_embedding", return_value=[0.1] * 768):
                results = await manager.retrieve_dynamic_memory(
                    query="context",
                    agent_name="hr-assistant",
                    user_id="u001",
                    session_id="sess-123",
                )

        assert call_count == 2  # both user-level and session-level were called
        assert len(results) == 1
        assert results[0].entry.session_id == "sess-123"

    async def test_retrieve_top_k_limit(self, manager, mock_qdrant):
        """Results should be limited to top_k."""
        mock_results = []
        for i in range(10):
            mock_results.append(
                MagicMock(
                    id=f"mem-{i}",
                    score=0.9 - i * 0.05,
                    payload={
                        "memory_id": f"mem-{i}",
                        "agent_name": "hr",
                        "user_id": "u001",
                        "session_id": None,
                        "scope": "user",
                        "memory_type": "context",
                        "content": f"Memory {i}",
                        "importance": 0.5,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                        "expires_at": None,
                    },
                )
            )
        mock_qdrant.search = AsyncMock(return_value=mock_results)

        with patch.object(manager, "_generate_embedding", return_value=[0.1] * 768):
            results = await manager.retrieve_dynamic_memory(
                query="test",
                agent_name="hr",
                user_id="u001",
                top_k=3,
            )

        assert len(results) == 3
        # Should be sorted by composite score descending
        assert results[0].composite_score >= results[1].composite_score


class TestWriteDynamicMemory:
    """Test memory write-back to PostgreSQL + Qdrant."""

    async def test_write_user_level_memory(self, manager, mock_qdrant):
        """Writing with session_id=None should create user-level memory (scope='user')."""
        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch.object(manager, "_generate_embedding", return_value=[0.1] * 768):
                with patch.object(manager, "_enforce_capacity", return_value=0):
                    result = await manager.write_dynamic_memory(
                        agent_name="hr-assistant",
                        user_id="u001",
                        session_id=None,
                        memory_type=MemoryType.PREFERENCE,
                        content="User prefers dark mode",
                        importance=0.7,
                    )

        assert result is not None
        assert result.content == "User prefers dark mode"
        assert result.importance == 0.7
        assert result.session_id is None  # user-level
        mock_qdrant.upsert.assert_called_once()
        upsert_args = mock_qdrant.upsert.call_args
        point = upsert_args.kwargs["points"][0]
        assert point.payload["scope"] == "user"

    async def test_write_session_level_memory(self, manager, mock_qdrant):
        """Writing with a session_id should create session-level memory (scope='session')."""
        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch.object(manager, "_generate_embedding", return_value=[0.1] * 768):
                with patch.object(manager, "_enforce_capacity", return_value=0):
                    result = await manager.write_dynamic_memory(
                        agent_name="hr-assistant",
                        user_id="u001",
                        session_id="sess-123",
                        memory_type=MemoryType.CONTEXT,
                        content="Discussed salary review",
                        importance=0.6,
                    )

        assert result is not None
        assert result.session_id == "sess-123"
        upsert_args = mock_qdrant.upsert.call_args
        point = upsert_args.kwargs["points"][0]
        assert point.payload["scope"] == "session"

    async def test_write_empty_content_returns_none(self, manager):
        """Writing empty content should return None."""
        result = await manager.write_dynamic_memory(
            agent_name="hr",
            user_id="u001",
            session_id=None,
            memory_type=MemoryType.CONTEXT,
            content="  ",
        )
        assert result is None

    async def test_importance_clamped(self, manager, mock_qdrant):
        """Importance should be clamped to [0.0, 1.0]."""
        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch.object(manager, "_generate_embedding", return_value=[0.1] * 768):
                with patch.object(manager, "_enforce_capacity", return_value=0):
                    result = await manager.write_dynamic_memory(
                        agent_name="hr",
                        user_id="u001",
                        session_id=None,
                        memory_type=MemoryType.CONTEXT,
                        content="test",
                        importance=5.0,  # over 1.0
                    )

        assert result.importance == 1.0

    async def test_write_sets_ttl(self, manager):
        """When ttl_days > 0, expires_at should be set."""
        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch.object(manager, "_generate_embedding", return_value=[0.1] * 768):
                with patch.object(manager, "_enforce_capacity", return_value=0):
                    result = await manager.write_dynamic_memory(
                        agent_name="hr",
                        user_id="u001",
                        session_id=None,
                        memory_type=MemoryType.CONTEXT,
                        content="test",
                        importance=0.5,
                        ttl_days=7,
                    )

        assert result.expires_at is not None


class TestForgettingStrategies:
    """Test the four forgetting strategies."""

    async def test_forget_expired(self, manager, mock_qdrant):
        """_forget_expired should delete memories with expires_at < now."""
        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.all.return_value = [("mem-1",), ("mem-2",)]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            count = await manager._forget_expired()

        assert count == 2
        mock_qdrant.delete.assert_called_once()

    async def test_enforce_capacity_under_limit(self, manager, mock_qdrant):
        """When count <= max_per_user, no eviction should occur."""
        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar.return_value = 50  # under 200 limit
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            count = await manager._enforce_capacity("hr", "u001")

        assert count == 0

    async def test_enforce_capacity_evicts_excess(self, manager, mock_qdrant):
        """When count > max_per_user, lowest-importance memories should be evicted."""
        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()

            # First call: count
            count_result = MagicMock()
            count_result.scalar.return_value = 203  # 3 over limit of 200

            # Second call: victim query
            victim_result = MagicMock()
            victim_result.all.return_value = [
                ("mem-low-1",), ("mem-low-2",), ("mem-low-3",),
            ]

            # Third call: delete query (in a second db_session_context)
            delete_result = MagicMock()

            mock_session.execute = AsyncMock(
                side_effect=[count_result, victim_result, delete_result]
            )
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            count = await manager._enforce_capacity("hr", "u001")

        assert count == 3
        mock_qdrant.delete.assert_called_once()

    async def test_promote_session_memories(self, manager, mock_qdrant):
        """High-importance session memories should be promoted to user-level."""
        from src.models.agent_memory import AgentMemory

        mock_record1 = MagicMock()
        mock_record1.id = "mem-1"
        mock_record1.importance = 0.85
        mock_record1.session_id = "sess-1"

        mock_record2 = MagicMock()
        mock_record2.id = "mem-2"
        mock_record2.importance = 0.9
        mock_record2.session_id = "sess-2"

        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_record1, mock_record2]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            count = await manager._promote_session_memories()

        assert count == 2
        # session_id should be cleared
        assert mock_record1.session_id is None
        assert mock_record2.session_id is None
        mock_qdrant.set_payload.assert_called_once()

    async def test_importance_decay(self, manager):
        """Memories older than 30 days should have importance decayed by 0.95."""
        old_record = MagicMock()
        old_record.id = "mem-old"
        old_record.importance = 0.8
        old_record.created_at = datetime.now(timezone.utc) - timedelta(days=60)
        old_record.metadata_ = {}

        with patch("src.memory.manager.db_session_context") as mock_ctx:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [old_record]
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_ctx.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=None)

            count = await manager._apply_importance_decay()

        assert count == 1
        # 0.8 * 0.95 = 0.76
        assert old_record.importance == pytest.approx(0.76, abs=0.01)


class TestWriteExtractedMemories:
    """Test batch writing of LLM-extracted memories."""

    async def test_low_importance_filtered(self, manager):
        """Memories with importance <= 0.3 should not be written."""
        extracted = [
            ExtractedMemory(content="important", importance=0.8),
            ExtractedMemory(content="trivial", importance=0.2),
        ]

        with patch.object(manager, "write_dynamic_memory", return_value=MagicMock()) as mock_write:
            count = await manager.write_extracted_memories(
                agent_name="hr",
                user_id="u001",
                session_id=None,
                extracted=extracted,
            )

        assert count == 1  # only the important one was written
        assert mock_write.call_count == 1

    async def test_all_high_importance_written(self, manager):
        """All memories with importance > 0.3 should be written."""
        extracted = [
            ExtractedMemory(content="m1", importance=0.5),
            ExtractedMemory(content="m2", importance=0.9),
        ]

        with patch.object(manager, "write_dynamic_memory", return_value=MagicMock()) as mock_write:
            count = await manager.write_extracted_memories(
                agent_name="hr",
                user_id="u001",
                session_id=None,
                extracted=extracted,
            )

        assert count == 2


class TestRecencyFactor:
    """Test the recency factor computation."""

    def test_recency_factor_today(self, manager):
        """A memory created today should have factor ~1.0."""
        now = datetime.now(timezone.utc)
        factor = manager._compute_recency_factor(now.isoformat(), now)
        assert factor == pytest.approx(1.0, abs=0.01)

    def test_recency_factor_old(self, manager):
        """A 12-month-old memory should have factor ~0.54."""
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=365)).isoformat()
        factor = manager._compute_recency_factor(old, now)
        # 0.95^12 ≈ 0.54
        assert 0.4 < factor < 0.7

    def test_recency_factor_empty_string(self, manager):
        """Empty created_at string should return 1.0 (neutral)."""
        factor = manager._compute_recency_factor("", datetime.now(timezone.utc))
        assert factor == 1.0

    def test_recency_factor_min_clamp(self, manager):
        """Very old memories should be clamped to minimum factor (0.05)."""
        now = datetime.now(timezone.utc)
        very_old = (now - timedelta(days=365 * 100)).isoformat()
        factor = manager._compute_recency_factor(very_old, now)
        assert factor >= 0.05
