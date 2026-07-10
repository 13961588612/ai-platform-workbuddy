"""
WeComOrgSync — 企业微信组织架构的定时同步。

每小时运行一次（通过 APScheduler）从企业微信 API
拉取部门与用户数据，并 upsert 到本地 PostgreSQL 数据库中。

同步实体：
  - 部门 → :class:`DepartmentModel`
  - 用户 → :class:`UserModel`（wecom_user_id 映射）
"""

from __future__ import annotations
from typing import Any

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.identity.auth import WeComClient
from src.models.user import DepartmentModel, UserModel

logger = structlog.get_logger(__name__)


class WeComOrgSync:
    """将企业微信部门与用户同步到本地数据库。"""

    def __init__(
        self,
        wecom_client: WeComClient | None = None,
    ) -> None:
        """初始化企业微信组织架构同步器。

        Args:
            wecom_client: 企业微信 API 客户端；未提供时使用默认实例。
        """
        self._wecom = wecom_client or WeComClient()
        self._last_sync_at: datetime | None = None

    async def sync_all(self, session: AsyncSession) -> dict[str, int]:
        """运行完整同步周期：先同步部门，再同步用户。

        Args:
            session: 一个异步 SQLAlchemy session。

        Returns:
            包含 ``departments_synced`` 和 ``users_synced`` 计数的字典。
        """
        logger.info("Starting WeCom org sync")
        dept_count: int = await self.sync_departments(session)
        user_count: int = await self.sync_users(session)
        await session.commit()
        self._last_sync_at = datetime.now(timezone.utc)
        logger.info(
            "WeCom org sync complete",
            departments=dept_count,
            users=user_count,
        )
        return {"departments_synced": dept_count, "users_synced": user_count}

    async def sync_departments(self, session: AsyncSession) -> int:
        """从企业微信拉取部门并 upsert 到数据库。"""
        try:
            depts: list[dict[str, Any]] = await self._wecom.get_department_list()
        except Exception:
            logger.exception("Failed to fetch departments from WeCom")
            return 0

        count: int = 0
        for dept_data in depts:
            dept_id: str = str(dept_data.get("id", ""))
            if not dept_id:
                continue

            # 检查部门是否存在
            stmt: Any = select(DepartmentModel).where(
                DepartmentModel.dept_id == dept_id,
                DepartmentModel.deleted_at.is_(None),
            )
            result: Any = await session.execute(stmt)
            existing: Any = result.scalar_one_or_none()

            if existing:
                existing.name = dept_data.get("name", existing.name)
                parent_id: int | None = dept_data.get("parentid")
                if parent_id is not None:
                    existing.parent_id = str(parent_id)
            else:
                new_dept: DepartmentModel = DepartmentModel(
                    dept_id=dept_id,
                    name=dept_data.get("name", ""),
                    parent_id=str(dept_data.get("parentid", "")) or None,
                )
                session.add(new_dept)
            count += 1

        return count

    async def sync_users(self, session: AsyncSession) -> int:
        """从所有企业微信部门拉取用户并 upsert 到数据库。

        遍历所有已同步的部门，获取每个部门的用户。
        """
        # 获取所有部门
        stmt: Any = select(DepartmentModel).where(
            DepartmentModel.deleted_at.is_(None),
            DepartmentModel.is_active.is_(True),
        )
        result: Any = await session.execute(stmt)
        departments: Any = result.scalars().all()

        count: int = 0
        seen_userids: set[str] = set()

        for dept in departments:
            try:
                # 企业微信部门 ID 是整数
                dept_id_int: int = int(dept.dept_id) if dept.dept_id.isdigit() else 0
                if dept_id_int == 0:
                    continue
                users: list[dict[str, Any]] = await self._wecom.get_department_users(dept_id_int)
            except Exception:
                logger.warning(
                    "Failed to fetch users for department",
                    dept_id=dept.dept_id,
                )
                continue

            for user_data in users:
                wecom_user_id: str = user_data.get("userid", "")
                if not wecom_user_id or wecom_user_id in seen_userids:
                    continue
                seen_userids.add(wecom_user_id)

                await self._upsert_user(session, user_data, dept.dept_id)
                count += 1

        return count

    async def _upsert_user(
        self,
        session: AsyncSession,
        user_data: dict[str, Any],
        dept_id: str,
    ) -> None:
        """从企业微信数据中插入或更新单个用户。"""
        wecom_user_id: str = user_data.get("userid", "")

        stmt: Any = select(UserModel).where(
            UserModel.wecom_user_id == wecom_user_id,
            UserModel.deleted_at.is_(None),
        )
        result: Any = await session.execute(stmt)
        existing: Any = result.scalar_one_or_none()

        name: str = user_data.get("name", wecom_user_id)
        email: Any = user_data.get("email") or user_data.get("biz_mail")
        phone: Any = user_data.get("mobile") or user_data.get("telephone")

        if existing:
            existing.display_name = name
            if email:
                existing.email = email
            if phone:
                existing.phone = phone
            existing.department = (
                user_data.get("department", [{}])[0]
                if user_data.get("department")
                else existing.department
            )
            existing.dept_id = dept_id
            existing.is_active = user_data.get("status", 1) == 1
        else:
            new_user: UserModel = UserModel(
                user_id=f"wecom_{wecom_user_id}",
                username=wecom_user_id,
                display_name=name,
                email=email,
                phone=phone,
                department="",
                dept_id=dept_id,
                wecom_user_id=wecom_user_id,
                channel="wecom_h5",
                is_active=user_data.get("status", 1) == 1,
            )
            session.add(new_user)

    @property
    def last_sync_at(self) -> datetime | None:
        """返回上次成功同步的时间戳。"""
        return self._last_sync_at
