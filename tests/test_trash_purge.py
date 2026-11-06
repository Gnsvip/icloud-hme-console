"""Permanent trash removal must survive cached and live synchronization."""
from unittest.mock import Mock

import pytest
from flask import Flask

from inventory_manager import InventoryManager


TARGET = "discarded@example.test"
KEEP = "retained@example.test"


@pytest.fixture
def inventory(tmp_path):
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.sync_aliases([{"email": TARGET, "account_id": "one"}, {"email": KEEP, "account_id": "one", "label": "keep"}])
    inv.move(TARGET, "trash")
    return inv


def test_purged_trash_does_not_return_from_any_sync_source_after_restart(inventory):
    kept = inventory.load()["items"][KEEP]
    assert inventory.purge(TARGET)
    restarted = InventoryManager(inventory.path)
    for source in ("local", "cloud", "mail", "inventory"):
        restarted.sync_aliases([{"email": TARGET.upper(), "account_id": "one", "source": source}])
    restarted.apply_messages([{"to": TARGET, "subject": "Your verification code", "body": "Code: 123456"}])
    assert restarted.load()["items"] == {KEEP: kept}
    assert restarted.purge(TARGET) is True
    with pytest.raises(ValueError, match="已永久删除"):
        restarted.update_item(TARGET, remark="stale request")
    assert TARGET not in restarted.load()["items"]


def test_active_record_cannot_be_purged(inventory):
    before = inventory.path.read_bytes()
    with pytest.raises(ValueError, match="先移入垃圾箱"):
        inventory.purge(KEEP)
    assert inventory.path.read_bytes() == before
    assert inventory.purge("missing@example.test") is False


def test_failed_atomic_write_keeps_trash_record(inventory, monkeypatch):
    import inventory_manager
    before = inventory.path.read_bytes()
    monkeypatch.setattr(inventory_manager.os, "replace", Mock(side_effect=OSError("disk full")))
    with pytest.raises(OSError):
        inventory.purge(TARGET)
    assert inventory.path.read_bytes() == before
    assert TARGET in inventory.load()["items"]


def test_purge_endpoint_is_admin_only_and_safe_to_retry(inventory, monkeypatch):
    import app_core
    from services import code_inventory_service
    from routes import inventory as routes
    monkeypatch.setattr(code_inventory_service, "_inventory", inventory)
    app = Flask(__name__)
    app_core.init_app(app)
    app.register_blueprint(routes.bp)
    client = app.test_client()
    path = f"/api/inventory/{TARGET}/purge"
    assert client.post(path, json={}).status_code == 401
    assert TARGET in inventory.load()["items"]
    with app.app_context():
        client.set_cookie(app_core.ADMIN_SESSION_COOKIE, app_core._admin_token())
    assert client.post(path, json={}).get_json()["ok"] is True
    assert client.post(path, json={}).get_json()["ok"] is True
    failure = client.post(f"/api/inventory/{KEEP}/purge", json={}).get_json()
    assert failure["ok"] is False and "垃圾箱" in failure["error"]
