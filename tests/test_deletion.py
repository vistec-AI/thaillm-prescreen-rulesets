"""Tests for session soft-delete and hard-delete features.

Verifies that:
  - Soft-delete sets ``deleted_at`` and hides the session from get/list
  - Hard-delete removes the session entirely
  - Double soft-delete raises an error (session already invisible)
  - Pipeline-level delete methods raise on non-existent sessions

Uses the same MockSessionRow / MockRepository from test_engine.py.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from prescreen_db.models.enums import SessionStatus
from prescreen_rulesets.engine import PrescreenEngine
from prescreen_rulesets.pipeline import PrescreenPipeline
from prescreen_rulesets.ruleset import RulesetStore

# Reuse mock infrastructure from test_engine
from test_engine import MockRepository, MockSessionRow

# Valid demographics for session setup
VALID_DEMOGRAPHICS = {
    "date_of_birth": "1994-06-15",
    "gender": "Male",
    "height": 175,
    "weight": 70,
    "underlying_diseases": [],
}


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture(scope="session")
def store():
    """Load the full RulesetStore once for the entire test session."""
    s = RulesetStore()
    s.load()
    return s


@pytest.fixture
def mock_repo():
    """Fresh MockRepository for each test."""
    return MockRepository()


@pytest.fixture
def engine(store, mock_repo):
    """PrescreenEngine with mocked repository."""
    eng = PrescreenEngine(store)
    eng._repo = mock_repo
    return eng


@pytest.fixture
def pipeline(engine, store, mock_repo):
    """PrescreenPipeline wrapping the mocked engine."""
    pipe = PrescreenPipeline(engine, store)
    pipe._repo = mock_repo
    return pipe


@pytest.fixture
def mock_db():
    """AsyncMock standing in for AsyncSession — flush/commit are no-ops."""
    return AsyncMock()


# =====================================================================
# Soft-delete tests
# =====================================================================


class TestSoftDelete:
    """Tests for soft-delete behaviour via the pipeline."""

    @pytest.mark.asyncio
    async def test_soft_delete_sets_deleted_at(
        self, pipeline, engine, mock_db, mock_repo,
    ):
        """Soft-deleting a session sets deleted_at to a non-None timestamp."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        row = mock_repo._sessions[("u1", "s1")]
        assert row.deleted_at is None, "New session should not be deleted"

        await pipeline.soft_delete_session(mock_db, user_id="u1", session_id="s1")
        assert row.deleted_at is not None, (
            "deleted_at should be set after soft-delete"
        )
        assert isinstance(row.deleted_at, datetime), (
            "deleted_at should be a datetime"
        )

    @pytest.mark.asyncio
    async def test_soft_deleted_session_hidden_from_get(
        self, pipeline, engine, mock_db,
    ):
        """A soft-deleted session is not returned by get_session."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await pipeline.soft_delete_session(mock_db, user_id="u1", session_id="s1")

        result = await pipeline.get_session(mock_db, user_id="u1", session_id="s1")
        assert result is None, (
            "Soft-deleted session should not be visible via get_session"
        )

    @pytest.mark.asyncio
    async def test_soft_deleted_session_hidden_from_list(
        self, pipeline, engine, mock_db,
    ):
        """A soft-deleted session is excluded from list_sessions."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await engine.create_session(mock_db, user_id="u1", session_id="s2")
        await pipeline.soft_delete_session(mock_db, user_id="u1", session_id="s1")

        sessions = await pipeline.list_sessions(mock_db, user_id="u1")
        session_ids = [s.session_id for s in sessions]
        assert "s1" not in session_ids, (
            "Soft-deleted session should not appear in list"
        )
        assert "s2" in session_ids, (
            "Non-deleted session should still appear in list"
        )

    @pytest.mark.asyncio
    async def test_double_soft_delete_raises(
        self, pipeline, engine, mock_db,
    ):
        """Soft-deleting an already-deleted session raises ValueError."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await pipeline.soft_delete_session(mock_db, user_id="u1", session_id="s1")

        # Second soft-delete should fail because the session is now
        # invisible to _load_session (get_by_user_and_session returns None)
        with pytest.raises(ValueError, match="Session not found"):
            await pipeline.soft_delete_session(
                mock_db, user_id="u1", session_id="s1",
            )

    @pytest.mark.asyncio
    async def test_soft_delete_nonexistent_session_raises(
        self, pipeline, mock_db,
    ):
        """Soft-deleting a non-existent session raises ValueError."""
        with pytest.raises(ValueError, match="Session not found"):
            await pipeline.soft_delete_session(
                mock_db, user_id="ghost", session_id="nope",
            )


# =====================================================================
# Hard-delete tests
# =====================================================================


class TestHardDelete:
    """Tests for hard-delete (permanent removal) via the pipeline."""

    @pytest.mark.asyncio
    async def test_hard_delete_removes_session(
        self, pipeline, engine, mock_db, mock_repo,
    ):
        """Hard-deleting a session removes it from the repository entirely."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        assert ("u1", "s1") in mock_repo._sessions, (
            "Session should exist before hard-delete"
        )

        await pipeline.hard_delete_session(mock_db, user_id="u1", session_id="s1")
        assert ("u1", "s1") not in mock_repo._sessions, (
            "Session should be gone after hard-delete"
        )

    @pytest.mark.asyncio
    async def test_hard_delete_session_not_in_list(
        self, pipeline, engine, mock_db,
    ):
        """Hard-deleted session does not appear in list_sessions."""
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await pipeline.hard_delete_session(mock_db, user_id="u1", session_id="s1")

        sessions = await pipeline.list_sessions(mock_db, user_id="u1")
        assert len(sessions) == 0, (
            "No sessions should remain after hard-delete"
        )

    @pytest.mark.asyncio
    async def test_hard_delete_nonexistent_session_raises(
        self, pipeline, mock_db,
    ):
        """Hard-deleting a non-existent session raises ValueError."""
        with pytest.raises(ValueError, match="Session not found"):
            await pipeline.hard_delete_session(
                mock_db, user_id="ghost", session_id="nope",
            )

    @pytest.mark.asyncio
    async def test_hard_delete_after_soft_delete_raises(
        self, pipeline, engine, mock_db,
    ):
        """Cannot hard-delete a session that was already soft-deleted.

        Since soft-deleted sessions are invisible to _load_session,
        hard_delete_session raises ValueError (session not found).
        """
        await engine.create_session(mock_db, user_id="u1", session_id="s1")
        await pipeline.soft_delete_session(mock_db, user_id="u1", session_id="s1")

        with pytest.raises(ValueError, match="Session not found"):
            await pipeline.hard_delete_session(
                mock_db, user_id="u1", session_id="s1",
            )


# =====================================================================
# MockRepository-level tests
# =====================================================================


class TestMockRepositoryDeletion:
    """Direct tests on MockRepository soft/hard-delete methods."""

    @pytest.mark.asyncio
    async def test_repo_soft_delete_sets_timestamp(self, mock_repo, mock_db):
        """MockRepository.soft_delete sets deleted_at."""
        row = await mock_repo.create_session(
            mock_db, user_id="u1", session_id="s1",
        )
        assert row.deleted_at is None

        result = await mock_repo.soft_delete(mock_db, row)
        assert result.deleted_at is not None, "deleted_at should be set"
        assert result is row, "Should return the same row object"

    @pytest.mark.asyncio
    async def test_repo_soft_delete_already_deleted_raises(
        self, mock_repo, mock_db,
    ):
        """MockRepository.soft_delete raises on already-deleted row."""
        row = await mock_repo.create_session(
            mock_db, user_id="u1", session_id="s1",
        )
        await mock_repo.soft_delete(mock_db, row)

        with pytest.raises(ValueError, match="already deleted"):
            await mock_repo.soft_delete(mock_db, row)

    @pytest.mark.asyncio
    async def test_repo_hard_delete_removes_row(self, mock_repo, mock_db):
        """MockRepository.hard_delete removes the row from storage."""
        await mock_repo.create_session(
            mock_db, user_id="u1", session_id="s1",
        )
        assert ("u1", "s1") in mock_repo._sessions

        row = mock_repo._sessions[("u1", "s1")]
        await mock_repo.hard_delete(mock_db, row)
        assert ("u1", "s1") not in mock_repo._sessions
