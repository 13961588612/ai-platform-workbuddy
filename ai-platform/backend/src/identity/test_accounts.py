"""开发环境测试账号加载与校验。"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from src.config import get_settings
from src.utils.logging import get_logger

logger = get_logger("identity.test_accounts")


class TestAccount(BaseModel):
    """测试账号条目。"""

    username: str
    password: str
    user_id: str
    display_name: str = ""
    department: str = "dev"
    roles: list[str] = Field(default_factory=list)
    channel: str = "web"


class TestAccountStore:
    """从 YAML 加载测试账号，仅在 DEV_TEST_ACCOUNTS_ENABLED 时可用。"""

    def __init__(self) -> None:
        """初始化测试账号存储并从 YAML 加载（若已启用）。"""
        self._by_username: dict[str, TestAccount] = {}
        self._reload()

    def _reload(self) -> None:
        """从配置路径重新加载测试账号 YAML 到内存索引。"""
        self._by_username.clear()
        settings = get_settings()
        if not settings.DEV_TEST_ACCOUNTS_ENABLED:
            return

        path = Path(settings.TEST_ACCOUNTS_FILE)
        if not path.is_absolute():
            path = Path(settings.CONFIG_BASE_PATH) / path

        if not path.is_file():
            logger.warning("Test accounts file not found", path=str(path))
            return

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.error("Failed to load test accounts", path=str(path), error=str(exc))
            return

        for item in data.get("accounts", []):
            if not isinstance(item, dict):
                continue
            try:
                account = TestAccount.model_validate(item)
            except Exception as exc:
                logger.warning("Skip invalid test account entry", error=str(exc))
                continue
            self._by_username[account.username] = account

        logger.info(
            "Test accounts loaded",
            path=str(path),
            count=len(self._by_username),
            usernames=sorted(self._by_username.keys()),
        )

    def is_enabled(self) -> bool:
        """开发测试账号功能是否已启用且已加载至少一条账号。"""
        return get_settings().DEV_TEST_ACCOUNTS_ENABLED and bool(self._by_username)

    def authenticate(self, username: str, password: str) -> TestAccount | None:
        """校验用户名与密码，成功时返回测试账号。

        Args:
            username: 登录用户名。
            password: 明文密码（与 YAML 中配置比对）。

        Returns:
            匹配的 ``TestAccount``；未启用、用户不存在或密码错误时返回 ``None``。
        """
        if not get_settings().DEV_TEST_ACCOUNTS_ENABLED:
            return None
        account = self._by_username.get(username)
        if account is None or account.password != password:
            return None
        return account


_test_account_store: TestAccountStore | None = None


def get_test_account_store() -> TestAccountStore:
    """返回单例 ``TestAccountStore`` 实例。"""
    global _test_account_store
    if _test_account_store is None:
        _test_account_store = TestAccountStore()
    return _test_account_store
