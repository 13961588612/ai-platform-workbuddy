"""Tests for backend/src/identity/token.py — JWT HS256 sign/verify/refresh."""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest

from src.identity.token import TokenError, TokenManager


@pytest.fixture
def token_manager():
    """Return a TokenManager with default test settings."""
    return TokenManager()


class TestCreateTokenSet:
    """Tests for token creation."""

    def test_create_token_set_returns_pair(self, token_manager):
        """create_token_set should return both access and refresh tokens."""
        ts = token_manager.create_token_set(
            user_id="u001", username="alice", roles=["admin"]
        )
        assert ts.access_token
        assert ts.refresh_token
        assert ts.access_token != ts.refresh_token
        assert ts.token_type == "Bearer"
        assert ts.expires_in > 0

    def test_access_token_contains_claims(self, token_manager):
        """The access token should contain user_id, username, roles, type='access'."""
        ts = token_manager.create_token_set(
            user_id="u001",
            username="alice",
            roles=["admin", "viewer"],
            department="engineering",
            channel="wecom_h5",
        )
        # Decode without verifying to inspect payload
        payload = jwt.decode(ts.access_token, options={"verify_signature": False})
        assert payload["user_id"] == "u001"
        assert payload["username"] == "alice"
        assert payload["roles"] == ["admin", "viewer"]
        assert payload["department"] == "engineering"
        assert payload["channel"] == "wecom_h5"
        assert payload["type"] == "access"
        assert payload["iss"] == "ai-platform"

    def test_refresh_token_type(self, token_manager):
        """The refresh token should have type='refresh'."""
        ts = token_manager.create_token_set(user_id="u001", username="alice")
        payload = jwt.decode(ts.refresh_token, options={"verify_signature": False})
        assert payload["type"] == "refresh"
        assert payload["user_id"] == "u001"


class TestVerifyAccessToken:
    """Tests for access token verification."""

    def test_verify_valid_access_token(self, token_manager):
        """A valid access token should verify and return TokenPayload."""
        ts = token_manager.create_token_set(
            user_id="u001", username="alice", roles=["admin"]
        )
        payload = token_manager.verify_access_token(ts.access_token)
        assert payload.user_id == "u001"
        assert payload.username == "alice"
        assert payload.roles == ["admin"]

    def test_verify_expired_access_token(self, token_manager):
        """An expired access token should raise TokenError."""
        # Create a token that expired in the past
        import jwt as jwt_lib

        expired_payload = {
            "user_id": "u001",
            "username": "alice",
            "type": "access",
            "iss": "ai-platform",
            "iat": int(time.time()) - 10000,
            "exp": int(time.time()) - 5000,
        }
        expired_token = jwt_lib.encode(
            expired_payload,
            token_manager._secret,
            algorithm="HS256",
        )
        with pytest.raises(TokenError, match="expired"):
            token_manager.verify_access_token(expired_token)

    def test_verify_refresh_token_as_access_fails(self, token_manager):
        """Using a refresh token where an access token is expected should fail."""
        ts = token_manager.create_token_set(user_id="u001", username="alice")
        with pytest.raises(TokenError, match="Expected access token"):
            token_manager.verify_access_token(ts.refresh_token)

    def test_verify_token_invalid_signature(self, token_manager):
        """A token signed with a different secret should be rejected."""
        wrong_token = jwt.encode(
            {"user_id": "u001", "username": "x", "type": "access", "iss": "ai-platform"},
            "wrong-secret-key",
            algorithm="HS256",
        )
        with pytest.raises(TokenError):
            token_manager.verify_access_token(wrong_token)

    def test_verify_garbage_token(self, token_manager):
        """A completely invalid token string should raise TokenError."""
        with pytest.raises(TokenError):
            token_manager.verify_access_token("not.a.jwt")


class TestVerifyRefreshToken:
    """Tests for refresh token verification."""

    def test_verify_valid_refresh_token(self, token_manager):
        """A valid refresh token should verify and return payload dict."""
        ts = token_manager.create_token_set(user_id="u001", username="alice")
        payload = token_manager.verify_refresh_token(ts.refresh_token)
        assert payload["user_id"] == "u001"
        assert payload["type"] == "refresh"

    def test_verify_access_token_as_refresh_fails(self, token_manager):
        """Using an access token where a refresh token is expected should fail."""
        ts = token_manager.create_token_set(user_id="u001", username="alice")
        with pytest.raises(TokenError, match="Expected refresh token"):
            token_manager.verify_refresh_token(ts.access_token)


class TestRefreshTokenSet:
    """Tests for the refresh token rotation mechanism."""

    def test_refresh_produces_new_pair(self, token_manager):
        """refresh_token_set should produce a new valid token pair."""
        # Create first token set with a mocked past time so that the second
        # set (created with real current time) will have different iat/exp
        past = datetime.now(timezone.utc) - timedelta(seconds=2)

        class PastDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return past

        with patch("src.identity.token.datetime", PastDateTime):
            ts = token_manager.create_token_set(user_id="u001", username="alice")

        # Refresh with real current time — different iat → different tokens
        new_ts = token_manager.refresh_token_set(ts.refresh_token)

        assert new_ts.access_token != ts.access_token
        assert new_ts.refresh_token != ts.refresh_token
        # New access token should verify
        payload = token_manager.verify_access_token(new_ts.access_token)
        assert payload.user_id == "u001"

    def test_refresh_with_invalid_token_fails(self, token_manager):
        """Refreshing with an invalid token should raise TokenError."""
        with pytest.raises(TokenError):
            token_manager.refresh_token_set("invalid-token-string")
