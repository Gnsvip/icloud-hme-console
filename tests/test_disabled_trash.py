"""Deleted aliases keep history in Trash, but must leave the disabled view."""
import json
from unittest.mock import Mock

import pytest
from flask import Flask

from inventory_manager import InventoryManager


def test_existing_deleted_disabled_records_are_hidden_without_rewriting_data(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps({"items": {
        "deleted@icloud.com": {"email": "deleted@icloud.com", "group": "trash", "lifecycle_status": "disabled", "remark": "retain", "status_message": "已从 iCloud 删除"},
        "disabled@icloud.com": {"email": "disabled@icloud.com", "group": "finished", "lifecycle_status": "disabled"},
    }}), encoding="utf-8")
    before = path.read_bytes()
    inv = InventoryManager(path)
    disabled, summary = inv.list_items(group="disabled")
    assert [row["email"] for row in disabled] == ["disabled@icloud.com"]
    assert summary["disabled"] == 1 and summary["trash"] == 1 and summary["all"] == 2
    trash, _ = inv.list_items(group="trash")
    assert trash[0]["remark"] == "retain"
    assert trash[0]["lifecycle_status"] == "disabled"
    assert path.read_bytes() == before


@pytest.mark.parametrize("absent", [False, True])
def test_cloud_delete_completion_clears_disabled_view_and_cached_count(tmp_path, monkeypatch, absent):
    from routes import accounts
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.update_item("removed@icloud.com", group="finished", lifecycle_status="disabled", remark="keep")
    assert inv.list_items(group="disabled")[1]["disabled"] == 1
    monkeypatch.setattr(accounts, "_inventory", inv)
    monkeypatch.setattr(accounts, "_account_mgr", Mock())
    monkeypatch.setattr(accounts, "_remove_alias_cache", Mock())
    accounts._record_batch_delete("account", {"email": "removed@icloud.com", "deleted": not absent, "already_absent": absent})
    disabled, summary = inv.list_items(group="disabled")
    assert disabled == [] and summary["disabled"] == 0
    assert inv.list_items(group="trash")[0][0]["remark"] == "keep"
    # Later cached alias and message imports must not bring it back into this view.
    inv.sync_aliases([{"email": "removed@icloud.com", "active": False}])
    inv.apply_messages([{"to": "removed@icloud.com", "subject": "Hello", "body": "Archived message"}])
    assert inv.list_items(group="disabled")[0] == []
    assert len(inv.list_items(group="trash")[0]) == 1


def test_inventory_api_and_summary_agree_about_disabled_trash(tmp_path, monkeypatch):
    import app_core
    from services import code_inventory_service as service
    inv = InventoryManager(tmp_path / "inventory.json")
    inv.update_item("gone@icloud.com", account_id="account", group="trash", lifecycle_status="disabled")
    inv.update_item("remaining@icloud.com", account_id="account", group="finished", lifecycle_status="disabled")
    monkeypatch.setattr(service, "_inventory", inv)
    monkeypatch.setattr(service, "_active_account_ids", lambda: {"account"})
    monkeypatch.setattr(service, "_read_alias_cache", lambda: {"aliases": []})
    monkeypatch.setattr(service, "_sync_inventory_from_known", Mock())
    monkeypatch.setattr(service, "_sync_inventory_from_mail_cache", Mock())
    all_rows, _ = inv.list_items(group="all")
    assert app_core._inventory_summary_from_items(all_rows)["disabled"] == 1
    with Flask(__name__).test_request_context("/api/inventory?group=disabled&page=1&page_size=20"):
        result = service.api_inventory().get_json()
    assert result["ok"] and result["count"] == 1
    assert [row["email"] for row in result["items"]] == ["remaining@icloud.com"]
