"""Family/subscription reads use synthetic responses; no Apple mutations."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import urlparse

import pytest
import requests

from services import account_benefits_service as benefits


@pytest.fixture
def rig(monkeypatch):
    account = {"id": "acc_demo", "cookies": {"X-APPLE-WEBAUTH-TOKEN": "secret"}, "host": "icloud.com",
               "app_password": "keep-this", "notes": "keep-this-too"}
    responses = {
        "validate": {"dsInfo": {"dsid": "123", "appleId": "demo@example.test", "isHideMyEmailSubscriptionActive": True},
                     "webservices": {"account": {"url": "https://p197-setup.icloud.com"}}},
        "getFamilyDetails": {"isMemberOfFamily": True, "family": {"organizer": "123"}, "familyInvitations": [],
                             "familyMembers": [{"dsid": "123", "fullName": "Demo", "appleId": "demo@example.test"},
                                               {"dsid": "456", "fullName": "Other", "appleId": "other@example.test"}]},
        "storageUsageInfo": {"storageUsageInfo": {"usedStorageInBytes": 100, "totalStorageInBytes": 200 * 1024**3}},
        "plan-summary": {"summary": {"includedInPlan": True, "limit": 200, "limitUnits": "GIB"},
                         "includedWithSharedPlan": {"includedInPlan": True},
                         "includedWithAccountPurchasedPlan": {"includedInPlan": False}},
    }
    calls = []

    def send(session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        key = urlparse(url).path.rsplit("/", 1)[-1]
        body = responses[key]
        if isinstance(body, Exception):
            raise body
        status, payload = body if isinstance(body, tuple) else (200, body)
        result = requests.Response()
        result.status_code = status
        result._content = json.dumps(payload).encode()
        return result

    monkeypatch.setattr(requests.Session, "request", send)
    manager = SimpleNamespace(get_account=lambda account_id: account if account_id == "acc_demo" else None)
    return SimpleNamespace(account=account, responses=responses, calls=calls, manager=manager,
                           read=lambda: benefits.read_benefits(manager, "acc_demo"))


def test_reads_members_source_and_usage_without_changing_account(rig):
    before = copy.deepcopy(rig.account)
    result = rig.read()
    assert result["family"]["is_organizer"] is True
    assert result["family"]["members"][0]["is_self"] is True
    assert result["family"]["members"][1]["is_self"] is False
    assert result["subscription"]["sources"] == ["家庭共享"]
    assert result["storage"]["total_bytes"] == 200 * 1024**3
    assert result["hide_my_email"] is True
    assert rig.account == before
    assert "secret" not in json.dumps(result) and "123" not in json.dumps(result)
    assert len(rig.calls) == 4
    assert all(call[2]["allow_redirects"] is False for call in rig.calls)
    assert {urlparse(c[1]).path for c in rig.calls} == {
        "/setup/ws/1/validate", "/setup/web/family/getFamilyDetails", "/setup/ws/1/storageUsageInfo",
        "/acsegateway/v3/accounts/123/subscriptions/features/cloud.storage/plan-summary",
    }


def test_china_region_is_kept_for_all_requests(rig):
    rig.account["host"] = "icloud.com.cn"
    rig.responses["validate"]["webservices"]["account"]["url"] = "https://p232-setup.icloud.com.cn"
    rig.read()
    assert all(urlparse(c[1]).hostname.endswith(".icloud.com.cn") for c in rig.calls)


@pytest.mark.parametrize("url", ["https://evil.test", "https://setup.icloud.com.cn", "http://setup.icloud.com",
                                 "https://setup.icloud.com@evil.test", "https://setup.icloud.com:999/x",
                                 "https://setup.icloud.com:bad", "https://setup.icloud.com?secret=1"])
def test_unexpected_service_url_is_never_requested(rig, url):
    rig.responses["validate"]["webservices"]["account"]["url"] = url
    result = rig.read()
    assert result["family"]["ok"] is False
    assert result["storage"]["ok"] is False
    assert result["subscription"]["ok"] is True
    assert len(rig.calls) == 2


@pytest.mark.parametrize("body", [(421, {"token": "never-return-this"}), (302, {}), {}, {"isMemberOfFamily": True}, requests.Timeout()])
def test_partial_failure_is_not_reported_as_no_family_or_retried(rig, body):
    rig.responses["getFamilyDetails"] = body
    result = rig.read()
    assert result["family"]["ok"] is False
    assert "is_member" not in result["family"]
    assert result["subscription"]["ok"] is True
    assert len(rig.calls) == 4
    assert "never-return-this" not in json.dumps(result)


def test_explicit_no_family_and_no_subscription_are_distinct_from_failure(rig):
    rig.responses["getFamilyDetails"] = {"isMemberOfFamily": False}
    rig.responses["plan-summary"] = {"summary": {"includedInPlan": False}}
    result = rig.read()
    assert result["family"] == {"ok": True, "is_member": False, "is_organizer": False, "members": [], "invitation_count": None}
    assert result["subscription"]["included"] is False


def test_empty_or_invalid_plan_never_means_unsubscribed(rig):
    rig.responses["plan-summary"] = {"summary": {"includedInPlan": "false"}}
    result = rig.read()
    assert result["subscription"]["ok"] is False
    assert "included" not in result["subscription"]


def test_invalid_login_never_uses_fallback_dsid(rig):
    rig.responses["validate"]["dsInfo"].pop("dsid")
    with pytest.raises(benefits.BenefitsError):
        rig.read()
    assert len(rig.calls) == 1


def test_unknown_or_logged_out_account_does_not_call_apple(rig):
    with pytest.raises(benefits.BenefitsError) as exc:
        benefits.read_benefits(rig.manager, "missing")
    assert exc.value.status == 404
    rig.account["cookies"] = {}
    with pytest.raises(benefits.BenefitsError) as exc:
        rig.read()
    assert exc.value.status == 409
    assert not rig.calls


def test_route_requires_admin_and_does_not_expire_admin_for_apple_errors(monkeypatch):
    import web_ui
    import app_core
    from routes import accounts
    client = web_ui.app.test_client()
    assert client.get("/api/accounts/acc_demo/benefits").status_code == 401
    with web_ui.app.app_context():
        client.set_cookie(app_core.ADMIN_SESSION_COOKIE, app_core._admin_token())
    monkeypatch.setattr(accounts, "_account_mgr", SimpleNamespace(get_account=lambda _: None))
    response = client.get("/api/accounts/missing/benefits")
    assert response.status_code == 404
    assert "no-store" in response.headers["Cache-Control"]
    assert client.post("/api/accounts/missing/benefits", json={}).status_code == 405
    monkeypatch.setattr(benefits, "read_benefits", Mock(side_effect=benefits.BenefitsError("Apple 会话失效")))
    assert client.get("/api/accounts/acc_demo/benefits").status_code == 502
    assert client.get("/api/admin/session").json["ok"] is True
