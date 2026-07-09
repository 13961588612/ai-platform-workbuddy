"""
AES-256-GCM 加密/解密工具。

由 CredentialVault 使用，用于安全存储业务系统登录凭据。
加密密钥来源于 ``CREDENTIAL_VAULT_KEY`` 环境变量，
必须是恰好 32 字节（256 位）以用于 AES-256。
"""

from __future__ import annotations
from typing import Any

import base64
import os

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from src.config import get_settings

logger = structlog.get_logger(__name__)

# GCM 模式推荐使用 12 字节 nonce。
_NONCE_SIZE = 12


class CryptoError(Exception):
    """加密或解密操作失败时抛出。"""


def _get_key() -> bytes:
    """从 settings 返回派生的 32 字节 AES 密钥。

    设置中的原始密钥可能短于或长于 32 字节；
    我们对其进行 SHA-256 哈希以确保获得有效的 256 位 AES 密钥。
    """
    import hashlib

    raw: bytes = get_settings().CREDENTIAL_VAULT_KEY.encode("utf-8")
    return hashlib.sha256(raw).digest()  # 始终 32 字节


def encrypt(plaintext: str | bytes) -> str:
    """使用 AES-256-GCM 加密 *plaintext* 并返回 URL 安全 base64 字符串。

    输出格式为 ``base64(nonce || ciphertext+tag)``，因此 nonce 与密文一同传输，
    无需单独存储。
    """
    if isinstance(plaintext, str):
        plaintext_bytes: bytes = plaintext.encode("utf-8")
    else:
        plaintext_bytes: Any = plaintext

    key: bytes = _get_key()
    nonce: Any = os.urandom(_NONCE_SIZE)
    aesgcm: AESGCM = AESGCM(key)
    ciphertext: str = aesgcm.encrypt(nonce, plaintext_bytes, associated_data=None)
    blob: Any = nonce + ciphertext
    return base64.urlsafe_b64encode(blob).decode("ascii")


def decrypt(token: str) -> str:
    """解密由 :func:`encrypt` 生成的 token 并返回原始 UTF-8 字符串。"""
    try:
        blob: Any = base64.urlsafe_b64decode(token.encode("ascii"))
    except Exception as exc:
        raise CryptoError("Invalid base64 token") from exc

    if len(blob) < _NONCE_SIZE + 16:  # nonce + 最小 GCM tag（16 字节）
        raise CryptoError("Token too short to contain nonce and tag")

    nonce: Any = blob[:_NONCE_SIZE]
    ciphertext: Any = blob[_NONCE_SIZE:]

    key: bytes = _get_key()
    aesgcm: AESGCM = AESGCM(key)
    try:
        plaintext_bytes: str = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except Exception as exc:
        raise CryptoError("Decryption failed — key mismatch or corrupted data") from exc

    return plaintext_bytes.decode("utf-8")


def encrypt_dict(data: dict[str, Any]) -> str:
    """将 *data* 序列化为 JSON 并加密。"""
    import json

    return encrypt(json.dumps(data, ensure_ascii=False, sort_keys=True))


def decrypt_dict(token: str) -> dict[str, Any]:
    """解密 *token* 并将其解析为 JSON，返回字典。"""
    import json

    return json.loads(decrypt(token))
