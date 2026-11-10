import threading
import time
from unittest.mock import Mock

import pytest
from flask import Flask

from inventory_manager import InventoryManager
from services.background_tasks import BackgroundTasks
from services.background_operations import prepare_operations
from services.alias_delete_service import DeleteJobError


def finished(jobs, key):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = jobs.status(key)
        if result["state"] == "complete":
            return result
        time.sleep(.01)
    raise AssertionError("task did not finish")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    import app_core
    from routes import register_routes
    from routes import inventory as routes
    from services import code_inventory_service
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.sync_aliases([{"email": f"trash-{i}@example.test", "group": "trash"} for i in range(71)] + [{"email": "keep@example.test"}])
    data = inv.load()
    for key, row in data["items"].items():
        row["group"] = "unused" if key.startswith("keep") else "trash"
    inv.save(data)
    jobs = BackgroundTasks()
    monkeypatch.setattr(routes, "_background_tasks", jobs)
    monkeypatch.setattr(code_inventory_service, "_inventory", inv)
    app = Flask(__name__)
    app_core.init_app(app)
    register_routes(app)
    client = app.test_client()
    with app.app_context():
        client.set_cookie(app_core.ADMIN_SESSION_COOKIE, app_core._admin_token())
    yield app, client, jobs, inv
    jobs.shutdown()


def payload(steps, key="background-test-001"):
    return {"request_id": key, "title": "测试任务", "steps": steps}


def test_batch_purge_saves_once_and_preserves_nontrash_and_tombstones(rig, monkeypatch):
    app, client, jobs, inv = rig
    save = Mock(wraps=inv.save)
    monkeypatch.setattr(inv, "save", save)
    before = inv.load()["items"]
    steps = [{"path": f"/api/inventory/{email}/purge"} for email in before]
    response = client.post('/api/background-tasks', json=payload(steps))
    assert response.status_code == 202
    result = finished(jobs, response.get_json()["job_id"])
    assert result["completed"] == 72 and result["failed"] == 1
    assert save.call_count == 1
    restarted = InventoryManager(inv.path)
    assert restarted.load()["items"] == {"keep@example.test": before["keep@example.test"]}
    restarted.sync_aliases(list(before.values()))
    assert len(restarted.load()["items"]) == 1
    assert len(restarted.load()["purged_emails"]) == 71
    again = client.post('/api/background-tasks', json=payload(steps)).get_json()
    assert again == result and save.call_count == 1


def test_batch_failed_write_does_not_claim_success_or_lose_data(rig, monkeypatch):
    import inventory_manager
    _, client, jobs, inv = rig
    before = inv.path.read_bytes()
    monkeypatch.setattr(inventory_manager.os, "replace", Mock(side_effect=OSError("disk full")))
    reply = client.post('/api/background-tasks', json=payload([{"path": "/api/inventory/trash-0@example.test/purge"}])).get_json()
    assert finished(jobs, reply["job_id"])["failed"] == 1
    assert inv.path.read_bytes() == before


def test_accepts_without_waiting_deduplicates_and_survives_request_exit(rig, monkeypatch):
    app, client, jobs, _ = rig
    entered, release = threading.Event(), threading.Event()
    def slow():
        entered.set()
        assert release.wait(3)
        return {"ok": True}
    handler = Mock(side_effect=slow)
    monkeypatch.setitem(app.view_functions, "inventory.api_inventory_sync", handler)
    steps = [{"path": "/api/inventory/sync", "body": {"live": True}}]
    try:
        reply = client.post('/api/background-tasks', json=payload(steps))
        assert reply.status_code == 202 and entered.wait(1)
        assert jobs.active()["jobs"]
        duplicate = client.post('/api/background-tasks', json=payload(steps, "duplicate-key-002"))
        assert duplicate.get_json()["job_id"] == reply.get_json()["job_id"]
        assert jobs.status("duplicate-key-002")["state"] == "running"
        assert client.post('/api/background-tasks', json=payload([{"path": "/api/inventory/check-forward"}])).status_code == 409
    finally:
        release.set()
    assert finished(jobs, "background-test-001")["failed"] == 0
    assert handler.call_count == 1


@pytest.mark.parametrize("step", [
    {"path": "https://example.test/api/inventory/sync"},
    {"path": "/api/accounts/add", "body": {"password": "synthetic"}},
    {"path": "/api/accounts/id/remove"},
    {"path": "/api/background-tasks"},
    {"path": "/api/inventory/sync", "method": "GET"},
    {"path": "/api/inventory/x/purge", "body": []},
])
def test_rejects_entire_batch_if_any_step_not_allowed(rig, step):
    _, client, jobs, inv = rig
    before = inv.path.read_bytes()
    reply = client.post('/api/background-tasks', json=payload([{"path": "/api/inventory/trash-0@example.test/purge"}, step]))
    assert reply.status_code == 400 and not jobs.active()["jobs"]
    assert inv.path.read_bytes() == before


def test_all_task_routes_require_admin(rig):
    app, _, _, _ = rig
    client = app.test_client()
    assert client.get('/api/background-tasks/active').status_code == 401
    assert client.get('/api/background-tasks/missing').status_code == 401
    assert client.post('/api/background-tasks', json={}).status_code == 401


def test_partial_errors_and_get_refresh_are_reported_without_returning_mail_content(rig, monkeypatch):
    app, client, jobs, _ = rig
    monkeypatch.setitem(app.view_functions, "inbox.api_all_inboxes", lambda: {"ok": True, "emails": [{"body": "private synthetic text"}]})
    monkeypatch.setitem(app.view_functions, "inventory.api_inventory_check_forward", lambda: {"ok": True, "errors": [{"error": "one account failed"}]})
    reply = client.post('/api/background-tasks', json=payload([
        {"path": "/api/inbox?refresh=1&limit=20", "method": "GET"},
        {"path": "/api/inventory/check-forward"},
    ])).get_json()
    result = finished(jobs, reply["job_id"])
    assert result["completed"] == 2 and result["failed"] == 1
    assert result["items"][1]["error"] == "one account failed"
    assert "private synthetic text" not in str(result)
