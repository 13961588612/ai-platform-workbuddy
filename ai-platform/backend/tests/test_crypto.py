"""Tests for backend/src/utils/crypto.py — AES-256-GCM encrypt/decrypt."""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import pytest

from src.utils.crypto import CryptoError, decrypt, decrypt_dict, encrypt, encrypt_dict


class TestEncryptDecryptSymmetry:
    """Verify that encrypt → decrypt round-trips correctly."""

    def test_encrypt_decrypt_string(self):
        """encrypt(plaintext) then decrypt(token) should return the original."""
        plaintext = "hello world"
        token = encrypt(plaintext)
        assert token != plaintext
        assert decrypt(token) == plaintext

    def test_encrypt_decrypt_chinese(self):
        """Chinese text should round-trip correctly via UTF-8."""
        plaintext = "你好世界！加密测试 🔐"
        token = encrypt(plaintext)
        assert decrypt(token) == plaintext

    def test_encrypt_decrypt_empty_string(self):
        """Empty string should round-trip correctly."""
        token = encrypt("")
        assert decrypt(token) == ""

    def test_encrypt_decrypt_long_text(self):
        """A long string (10 KB) should round-trip correctly."""
        plaintext = "A" * 10240
        token = encrypt(plaintext)
        assert decrypt(token) == plaintext

    def test_encrypt_produces_different_tokens(self):
        """Each encrypt call should produce a different token (random nonce)."""
        t1 = encrypt("same text")
        t2 = encrypt("same text")
        assert t1 != t2  # different nonces
        assert decrypt(t1) == decrypt(t2) == "same text"

    def test_encrypt_accepts_bytes(self):
        """encrypt() should accept bytes input."""
        token = encrypt(b"binary data")
        assert decrypt(token) == "binary data"


class TestEncryptDictDecryptDict:
    """Verify dict-level encrypt/decrypt."""

    def test_encrypt_dict_decrypt_dict_roundtrip(self):
        """encrypt_dict → decrypt_dict should restore the original dict."""
        data = {"username": "alice", "password": "s3cret", "port": 5432}
        token = encrypt_dict(data)
        assert isinstance(token, str)
        result = decrypt_dict(token)
        assert result == data

    def test_encrypt_dict_with_nested(self):
        """Nested dicts should round-trip correctly."""
        data = {"outer": {"inner": "value"}, "list": [1, 2, 3]}
        token = encrypt_dict(data)
        result = decrypt_dict(token)
        assert result == data

    def test_encrypt_dict_empty(self):
        """Empty dict should round-trip."""
        token = encrypt_dict({})
        assert decrypt_dict(token) == {}


class TestDecryptionFailures:
    """Verify error handling for invalid or mismatched tokens."""

    def test_decrypt_invalid_base64(self):
        """Decrypting a non-base64 string should raise CryptoError."""
        with pytest.raises(CryptoError, match="Invalid base64"):
            decrypt("!!!not-base64!!!")

    def test_decrypt_short_token(self):
        """A token too short to contain nonce+tag should raise CryptoError."""
        short_token = base64.urlsafe_b64encode(b"short").decode("ascii")
        with pytest.raises(CryptoError, match="too short"):
            decrypt(short_token)

    def test_decrypt_wrong_key(self):
        """Decrypting with a different key should raise CryptoError."""
        token = encrypt("secret data")
        # Patch _get_key to return a different key
        import hashlib

        wrong_key = hashlib.sha256(b"different-key-entirely").digest()
        with patch("src.utils.crypto._get_key", return_value=wrong_key):
            with pytest.raises(CryptoError, match="Decryption failed"):
                decrypt(token)

    def test_decrypt_corrupted_token(self):
        """A corrupted token should raise CryptoError."""
        token = encrypt("some data")
        # Flip a character in the middle of the token
        corrupted = token[:10] + ("A" if token[10] != "A" else "B") + token[11:]
        with pytest.raises(CryptoError):
            decrypt(corrupted)


class TestEncryptFormat:
    """Verify the encrypted token format."""

    def test_encrypt_returns_url_safe_base64(self):
        """The token should be URL-safe base64 (no + or / characters)."""
        token = encrypt("test")
        # URL-safe base64 only contains [A-Za-z0-9_-] and possibly = padding
        for char in token:
            assert char.isalnum() or char in "-_="

    def test_encrypt_token_length_includes_nonce(self):
        """The decoded token should be longer than the plaintext (nonce + tag overhead)."""
        import base64

        plaintext = "test"
        token = encrypt(plaintext)
        blob = base64.urlsafe_b64decode(token)
        # nonce (12) + ciphertext + tag (16) > plaintext length
        assert len(blob) > len(plaintext)
