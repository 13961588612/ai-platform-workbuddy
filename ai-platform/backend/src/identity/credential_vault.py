"""
CredentialVault — 用于业务系统凭据的 AES-256-GCM 加密存储。

将加密凭据存储在 ``credential_mappings`` 表中。
明文凭据永远不会被日志记录或通过任何 API 返回；
只有加密的二进制数据会被持久化。

密钥轮换：``CREDENTIAL_VAULT_KEY`` 环境变量可以被
轮换。``re_encrypt_all()`` 使用当前密钥重新加密所有已存储的凭据。
"""

from __future__ import annotations
from typing import Any


import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import CredentialMappingModel
from src.utils.crypto import decrypt_dict, encrypt_dict

logger = structlog.get_logger(__name__)


class CredentialVault:
    """管理加密的业务系统凭据存储。"""

    def __init__(self) -> None:
        """初始化凭据保险库（加密密钥从 ``crypto`` 模块读取配置）。"""
        pass  # 密钥从 crypto.py 内部的 settings 中获取

    async def store_credential(
        self,
        session: AsyncSession,
        user_id: str,
        system_type: str,
        system_account: str,
        credential: dict[str, Any],
    ) -> str:
        """为用户 + 业务系统加密并存储凭据。

        如果同一 (user_id, system_type) 的映射已存在，
        则进行更新。

        返回存储的凭据映射的数据库行 ID。
        """
        encrypted: str = encrypt_dict(credential)

        # 检查是否存在
        stmt: Any = select(CredentialMappingModel).where(
            CredentialMappingModel.user_id == user_id,
            CredentialMappingModel.system_type == system_type,
            CredentialMappingModel.is_active.is_(True),
        )
        result: Any = await session.execute(stmt)
        existing: Any = result.scalar_one_or_none()

        if existing:
            existing.system_account = system_account
            existing.encrypted_credential = encrypted
            await session.flush()
            logger.info(
                "Credential updated",
                user_id=user_id,
                system_type=system_type,
            )
            return existing.id

        new_mapping: CredentialMappingModel = CredentialMappingModel(
            user_id=user_id,
            system_type=system_type,
            system_account=system_account,
            encrypted_credential=encrypted,
        )
        session.add(new_mapping)
        await session.flush()
        logger.info(
            "Credential stored",
            user_id=user_id,
            system_type=system_type,
        )
        return new_mapping.id

    async def retrieve_credential(
        self,
        session: AsyncSession,
        user_id: str,
        system_type: str,
    ) -> dict[str, Any] | None:
        """解密并返回用户 + 业务系统的凭据。

        如果没有存储凭据，则返回 ``None``。
        """
        stmt: Any = select(CredentialMappingModel).where(
            CredentialMappingModel.user_id == user_id,
            CredentialMappingModel.system_type == system_type,
            CredentialMappingModel.is_active.is_(True),
        )
        result: Any = await session.execute(stmt)
        mapping: Any = result.scalar_one_or_none()
        if not mapping:
            return None

        try:
            return decrypt_dict(mapping.encrypted_credential)  # type: ignore[arg-type]
        except Exception:
            logger.exception(
                "Failed to decrypt credential",
                user_id=user_id,
                system_type=system_type,
            )
            return None

    async def delete_credential(
        self,
        session: AsyncSession,
        user_id: str,
        system_type: str,
    ) -> bool:
        """软删除凭据映射（设置 is_active=False）。

        如果找到并停用了映射，则返回 True。
        """
        stmt: Any = (
            update(CredentialMappingModel)
            .where(
                CredentialMappingModel.user_id == user_id,
                CredentialMappingModel.system_type == system_type,
                CredentialMappingModel.is_active.is_(True),
            )
            .values(is_active=False)
        )
        result: Any = await session.execute(stmt)
        return result.rowcount > 0  # type: ignore[union-attr]

    async def list_credentials(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[dict[str, Any]]:
        """列出用户的所有活跃凭据映射（不含明文）。"""
        stmt: Any = select(CredentialMappingModel).where(
            CredentialMappingModel.user_id == user_id,
            CredentialMappingModel.is_active.is_(True),
        )
        result: Any = await session.execute(stmt)
        mappings: Any = result.scalars().all()
        return [m.to_dict() for m in mappings]

    async def re_encrypt_all(self, session: AsyncSession) -> int:
        """使用当前 vault 密钥重新加密所有已存储的凭据。

        在密钥轮换后使用。返回重新加密的映射数量。
        """
        stmt: Any = select(CredentialMappingModel).where(
            CredentialMappingModel.is_active.is_(True),
        )
        result: Any = await session.execute(stmt)
        mappings: Any = result.scalars().all()

        count: int = 0
        for mapping in mappings:
            try:
                plaintext: dict[str, Any] = decrypt_dict(mapping.encrypted_credential)  # type: ignore[arg-type]
                mapping.encrypted_credential = encrypt_dict(plaintext)
                count += 1
            except Exception:
                logger.exception(
                    "Failed to re-encrypt credential",
                    user_id=mapping.user_id,
                    system_type=mapping.system_type,
                )
        await session.flush()
        logger.info("Credential re-encryption complete", count=count)
        return count
