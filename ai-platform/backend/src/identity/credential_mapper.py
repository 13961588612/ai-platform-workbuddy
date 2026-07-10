"""
CredentialMapper — 将平台用户映射到业务系统账号。

一个平台用户可能在不同的业务系统中
拥有不同的账号（例如，平台中的用户 "zhangsan" 可能在
财务系统中是 "zhangsan_finance"，在 HR 系统中是 "zs001"）。

此模块提供 BusinessSystemAdapters 使用的查找接口，
用于在代表用户调用业务系统 API 时
获取正确的凭据。
"""

from __future__ import annotations
from typing import Any


import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.credential_vault import CredentialVault
from src.models.user import CredentialMappingModel

logger = structlog.get_logger(__name__)


class CredentialMapper:
    """解析 (user_id, system_type) → (account, credential) 映射。"""

    def __init__(self, vault: CredentialVault | None = None) -> None:
        """初始化凭据映射器。

        Args:
            vault: 加密凭据存储；未提供时使用默认 ``CredentialVault``。
        """
        self._vault = vault or CredentialVault()

    async def get_credential(
        self,
        session: AsyncSession,
        user_id: str,
        system_type: str,
    ) -> tuple[str, dict[str, Any]] | None:
        """返回给定映射的 ``(system_account, credential_dict)``。

        如果不存在映射或凭据无法解密，
        则返回 ``None``。
        """
        # 获取账号名称
        stmt: Any = select(CredentialMappingModel).where(
            CredentialMappingModel.user_id == user_id,
            CredentialMappingModel.system_type == system_type,
            CredentialMappingModel.is_active.is_(True),
        )
        result: Any = await session.execute(stmt)
        mapping: Any = result.scalar_one_or_none()
        if not mapping:
            logger.debug(
                "No credential mapping found",
                user_id=user_id,
                system_type=system_type,
            )
            return None

        # 解密凭据
        credential: dict[str, Any] | None = await self._vault.retrieve_credential(
            session, user_id, system_type
        )
        if credential is None:
            logger.warning(
                "Credential decryption failed",
                user_id=user_id,
                system_type=system_type,
            )
            return None

        return (mapping.system_account, credential)

    async def set_credential(
        self,
        session: AsyncSession,
        user_id: str,
        system_type: str,
        system_account: str,
        credential: dict[str, Any],
    ) -> str:
        """为用户 + 系统创建或更新凭据映射。

        返回存储的映射的数据库行 ID。
        """
        return await self._vault.store_credential(
            session=session,
            user_id=user_id,
            system_type=system_type,
            system_account=system_account,
            credential=credential,
        )

    async def remove_credential(
        self,
        session: AsyncSession,
        user_id: str,
        system_type: str,
    ) -> bool:
        """停用凭据映射。"""
        return await self._vault.delete_credential(session, user_id, system_type)

    async def list_systems(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> list[str]:
        """返回用户拥有凭据的业务系统类型列表。"""
        stmt: Any = select(CredentialMappingModel.system_type).where(
            CredentialMappingModel.user_id == user_id,
            CredentialMappingModel.is_active.is_(True),
        )
        result: Any = await session.execute(stmt)
        return [row[0] for row in result.all()]
