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
        self._by_username: dict[str, TestAccount] = {}
        self._reload()

    def _reload(self) -> None:
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
        return get_settings().DEV_TEST_ACCOUNTS_ENABLED and bool(self._by_username)

    def authenticate(self, username: str, password: str) -> TestAccount | None:
        if not get_settings().DEV_TEST_ACCOUNTS_ENABLED:
            return None
        account = self._by_username.get(username)
        if account is None or account.password != password:
            return None
        return account


_test_account_store: TestAccountStore | None = None


def get_test_account_store() -> TestAccountStore:
    global _test_account_store
    if _test_account_store is None:
        _test_account_store = TestAccountStore()
    return _test_account_store
