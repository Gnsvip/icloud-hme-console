"""Deletion regressions use synthetic aliases and mocked Apple responses."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask

from account_manager import AccountManager
from icloud_hme import ICloudHME


EMAIL = "delete-me@example.test"
ALIAS = {"email": EMAIL, "anonymousId": "current-id", "active": True}


@pytest.fixture
def apple(monkeypatch):
    client = ICloudHME({}, verbose=False)
    client._service_url = "https://apple.example.test"
    monkeypatch.setattr(client, "_request", Mock())
    yield client
    client.session.close()


@pytest.mark.parametrize("response", [{}, {"success": False}, {"success": True, "result": {}}, []])
def test_failed_or_incomplete_list_is_not_treated_as_no_aliases(apple, response):
    apple._request.return_value = response
    with pytest.raises(RuntimeError, match="完整的别名列表"):
        apple.list_aliases()


def test_confirmed_empty_list_is_valid(apple):
    apple._request.return_value = {"success": True, "result": {"hmeEmails": [], "forwarding": [{"email": "owner@example.test", "id": "not-an-alias"}]}}
    assert apple.list_aliases() == []


@pytest.mark.parametrize("active,actions", [(True, ["deactivate", "delete"]), (False, ["delete"])])
def test_active_alias_is_deactivated_before_permanent_deletion(apple, active, actions):
    apple._request.return_value = {"success": True}
    assert apple.delete("current-id", active=active) is True
    assert [c.args[1].rsplit("/", 1)[-1] for c in apple._request.call_args_list] == actions
    assert all(c.kwargs["json_data"] == {"anonymousId": "current-id"} for c in apple._request.call_args_list)
    assert all(c.kwargs["max_attempts"] == 1 for c in apple._request.call_args_list)


def test_deactivation_failure_never_attempts_deletion(apple):
    apple._request.return_value = {"success": False, "error": {"errorMessage": "refused"}}
    with pytest.raises(RuntimeError, match="refused"):
        apple.delete("current-id", active=True)
    assert apple._request.call_count == 1


@pytest.mark.parametrize("response", [{"success": False}, {}])
def test_deactivation_is_not_reported_as_permanent_deletion(apple, response):
    apple._request.side_effect = [{"success": True}, response]
    with pytest.raises(RuntimeError, match="永久删除未完成"):
        apple.delete("current-id", active=True)


def test_cli_delete_checks_current_state(apple, monkeypatch):
    monkeypatch.setattr(apple, "list_aliases", Mock(return_value=[{**ALIAS, "active": False}]))
    apple._request.return_value = {"success": True}
    assert apple.delete("current-id")
    assert apple._request.call_count == 1
    assert apple._request.call_args.args[1].endswith("/delete")


@pytest.fixture
def manager(monkeypatch):
    mgr = AccountManager()
    client = Mock()
    client.list_aliases.return_value = [dict(ALIAS)]
    client.delete.return_value = True
    monkeypatch.setattr(mgr, "get_client", Mock(return_value=client))
    monkeypatch.setattr(mgr, "_remove_local_email", Mock())
    monkeypatch.setattr(mgr, "validate_account", Mock())
    return SimpleNamespace(mgr=mgr, client=client)


def test_already_deleted_alias_does_not_send_stale_id_to_apple(manager):
    manager.client.list_aliases.return_value = []
    result = manager.mgr.delete_alias("account", "stale-id", EMAIL)
    assert result == {"deleted": False, "already_absent": True, "email": EMAIL}
    manager.client.delete.assert_not_called()
    manager.mgr._remove_local_email.assert_called_once_with(EMAIL)


def test_email_resolves_current_id_instead_of_old_cache(manager):
    result = manager.mgr.delete_alias("account", "stale-id", EMAIL.upper())
    manager.client.delete.assert_called_once_with("current-id", active=True)
    assert result["deleted"] and not result["already_absent"]


def test_mismatched_email_and_id_never_delete_another_alias(manager):
    with pytest.raises(ValueError, match="不一致"):
        manager.mgr.delete_alias("account", "current-id", "another@example.test")
    manager.client.delete.assert_not_called()
    manager.mgr._remove_local_email.assert_not_called()


@pytest.mark.parametrize("stage", ["list", "delete"])
def test_network_or_permanent_delete_failure_keeps_local_record(manager, stage):
    getattr(manager.client, "list_aliases" if stage == "list" else "delete").side_effect = RuntimeError("network failure")
    with pytest.raises(RuntimeError):
        manager.mgr.delete_alias("account", "current-id", EMAIL)
    manager.mgr._remove_local_email.assert_not_called()
    manager.mgr.validate_account.assert_not_called()
    manager.client.session.close.assert_called_once()


@pytest.fixture
def delete_api(monkeypatch):
    from routes import accounts
    mgr = Mock()
    inventory = Mock()
    remove_cache = Mock()
    monkeypatch.setattr(accounts, "_account_mgr", mgr)
    monkeypatch.setattr(accounts, "_inventory", inventory)
    monkeypatch.setattr(accounts, "_remove_alias_cache", remove_cache)
    monkeypatch.setattr(accounts, "_emit_log", Mock())
    app = Flask(__name__)
    app.register_blueprint(accounts.bp)
    return SimpleNamespace(client=app.test_client(), mgr=mgr, inventory=inventory, remove_cache=remove_cache)


def test_already_absent_response_distinguishes_cloud_absence_and_local_trash(delete_api):
    delete_api.mgr.delete_alias.return_value = {"deleted": False, "already_absent": True, "email": EMAIL}
    response = delete_api.client.post("/api/accounts/account/aliases/stale-id/delete", json={"email": EMAIL})
    data = response.get_json()
    assert data["ok"] and data["already_absent"] and not data["deleted"]
    assert "本地垃圾箱" in data["message"]
    delete_api.remove_cache.assert_called_once_with(email=EMAIL)
    assert delete_api.inventory.update_item.call_args.kwargs["group"] == "trash"


def test_delete_route_does_not_hide_record_on_failure(delete_api):
    delete_api.mgr.delete_alias.side_effect = RuntimeError("permanent delete failed")
    data = delete_api.client.post("/api/accounts/account/aliases/id/delete", json={"email": EMAIL}).get_json()
    assert data["ok"] is False
    delete_api.remove_cache.assert_not_called()
    delete_api.inventory.update_item.assert_not_called()
