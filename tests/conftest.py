"""Provide an isolated, non-production password for tests only."""
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('ADMIN_PASSWORD', 'test-only-not-for-deployment')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="session", autouse=True)
def isolated_runtime(tmp_path_factory):
    """Every test uses disposable data, including legacy tests and Flask imports."""
    import account_manager
    import inventory_manager
    import mail_cache
    root = tmp_path_factory.mktemp("runtime")
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(mail_cache, "CACHE_FILE", root / "mail_cache.json")
        patch.setattr(account_manager, "RESULTS_DIR", root)
        patch.setattr(account_manager, "LATEST_EMAILS", root / "latest_emails.txt")
        patch.setattr(account_manager, "ACCOUNTS_FILE", root / "accounts.json")
        patch.setattr(account_manager, "OLD_COOKIES_FILE", root / "cookies.json")
        patch.setattr(inventory_manager, "FORWARD_CONFIG_FILE", root / "forward.json")
        import app_core
        patch.setattr(app_core, "RESULTS_DIR", root)
        patch.setattr(app_core, "LOGS_DIR", root / "logs")
        patch.setattr(app_core, "RUNTIME_LOG_FILE", root / "logs/runtime.log")
        patch.setattr(app_core, "ALIASES_CACHE_FILE", root / "aliases.json")
        patch.setattr(app_core, "ADMIN_SECRET_FILE", root / "admin.key")
        patch.setattr(app_core, "COOKIE_HELPER_TOKEN_FILE", root / "helper.key")
        patch.setattr(app_core, "_inventory", inventory_manager.InventoryManager(root / "inventory.json"))
        yield
