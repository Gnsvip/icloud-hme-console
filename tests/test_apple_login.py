"""Apple sign-in contract tests. All identities and responses are synthetic."""
import concurrent.futures
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from flask import Flask

import account_manager
from icloud_hme import ICloudHME
from services import apple_login_service as login


IDENTITY = {"dsid": "123456", "appleId": "demo@example.test", "primaryEmail": "demo@icloud.com"}
INPUT = {"apple_id": "demo@example.test", "password": "synthetic-login-secret"}


class FakeApple:
    def __init__(self):
        self._password_raw = INPUT["password"]
        self.session = requests.Session()
        self.session.close = Mock(wraps=self.session.close)
        self.session.cookies.set("X-APPLE-WEBAUTH-TOKEN", "synthetic-cookie", domain=".icloud.com")
        self.requires_2fa = True
        self.requires_2sa = False
        self.two_factor_delivery_method = "trusted_device"
        self.authenticate = Mock()
        self.request_2fa_code = Mock(return_value=True)
        self.use_existing_trusted_device_code = Mock(side_effect=self.use_existing_code)
        self.validate_2fa_code = Mock(side_effect=self.validate)

    def use_existing_code(self):
        self.two_factor_delivery_method = "trusted_device"

    def validate(self, code):
        if code == "123456":
            self.requires_2fa = False
            return True
        return False


@pytest.fixture
def rig(tmp_path, monkeypatch):
    # No test in this module may accidentally reach Apple or another network.
    monkeypatch.setattr(requests.Session, "send", Mock(side_effect=AssertionError("Unexpected network")))
    monkeypatch.setattr(account_manager, "ACCOUNTS_FILE", tmp_path / "accounts.json")
    monkeypatch.setattr(account_manager, "OLD_COOKIES_FILE", tmp_path / "old.json")
    accounts = account_manager.AccountManager()
    apple = FakeApple()
    directories = []

    def factory(apple_id, password, directory, host):
        assert (apple_id, password) == (INPUT["apple_id"], INPUT["password"])
        directories.append(Path(directory))
        (Path(directory) / "session").write_text("synthetic-session")
        return apple

    verifier = Mock()
    verifier.validate_session.return_value = {"webservices": {"premiummailsettings": {"url": "https://example.test"}}}
    verifier.get_account_info.return_value = dict(IDENTITY)
    verifier_factory = Mock(return_value=verifier)
    monkeypatch.setattr(login, "ICloudHME", verifier_factory)
    manager = login.AppleLoginManager(accounts, factory, cleanup=False)
    yield SimpleNamespace(manager=manager, apple=apple, accounts=accounts,
                          verifier=verifier, verifier_factory=verifier_factory, directories=directories)
    manager.shutdown()


def idle(manager, flow_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        flow = manager.flows[flow_id]
        with flow.lock:
            if not flow.busy:
                return flow
        time.sleep(0.005)
    pytest.fail("Login worker did not finish")


def start(rig, **extra):
    result = rig.manager.start({**INPUT, **extra})
    return idle(rig.manager, result["flow_id"])


@pytest.mark.parametrize("delivery", ["trusted_device", "sms"])
def test_two_factor_imports_only_verified_icloud_cookies_and_discards_temporary_session(rig, delivery):
    rig.apple.two_factor_delivery_method = delivery
    rig.apple.session.cookies.set("auth-secret", "do-not-import", domain="idmsa.apple.com")
    rig.apple.session.cookies.set("evil-secret", "do-not-import", domain="evilicloud.com")
    rig.apple.session.cookies.set("X-APPLE-WEBAUTH-TOKEN", "other-region", domain=".icloud.com.cn")
    flow = start(rig)
    assert rig.manager.status(flow.id)["delivery"] == delivery
    assert flow.state == "awaiting_code"
    assert rig.accounts.accounts == {}
    rig.manager.verify(flow.id, "123456")
    idle(rig.manager, flow.id)
    result = rig.manager.status(flow.id)
    assert result["state"] == "complete"
    assert result["account"]["status"] == "active"
    rig.verifier.validate_session.assert_called_once_with(timeout=18, max_attempts=1, require_hme=False)
    exported = rig.verifier_factory.call_args.args[0]
    assert exported == {"X-APPLE-WEBAUTH-TOKEN": "synthetic-cookie"}
    assert all(secret not in json.dumps(result) for secret in (INPUT["password"], "synthetic-cookie", "synthetic-session"))
    assert rig.apple._password_raw is None
    assert not rig.apple.session.cookies
    assert flow.client is None and flow.temporary is None
    assert all(not p.exists() for p in rig.directories)
    rig.verifier.session.close.assert_called_once()


def test_existing_trusted_session_can_finish_without_code(rig):
    rig.apple.requires_2fa = False
    assert start(rig).state == "complete"


def test_bad_codes_retry_then_stop_after_five_attempts(rig):
    flow = start(rig)
    for attempt in range(5):
        rig.manager.verify(flow.id, "000000")
        idle(rig.manager, flow.id)
        assert flow.state == ("failed" if attempt == 4 else "awaiting_code")
    assert rig.apple.request_2fa_code.call_count == 5
    assert rig.accounts.accounts == {}
    assert flow.client is None


@pytest.mark.parametrize("kind", ["security_key", "old_2sa", "network", "invalid_cookie", "missing_identity"])
def test_failed_or_unsupported_auth_never_imports_account(rig, kind):
    if kind == "security_key":
        rig.apple.two_factor_delivery_method = kind
    elif kind == "old_2sa":
        rig.apple.requires_2fa = False
        rig.apple.requires_2sa = True
    elif kind == "network":
        rig.apple.authenticate.side_effect = requests.Timeout("secret upstream response")
    else:
        rig.apple.requires_2fa = False
        if kind == "invalid_cookie":
            rig.verifier.validate_session.side_effect = RuntimeError("secret upstream response")
        else:
            rig.verifier.get_account_info.return_value = {}
    flow = start(rig)
    assert flow.state == "failed"
    assert "secret upstream" not in flow.error
    assert rig.accounts.accounts == {}
    assert not rig.directories[0].exists()


@pytest.mark.parametrize("expire", [False, True])
def test_cancel_or_expire_removes_secrets(rig, expire):
    flow = start(rig)
    if expire:
        flow.expires = time.monotonic() - 1
        rig.manager.cleanup()
    else:
        rig.manager.cancel(flow.id)
        rig.manager.cancel(flow.id)  # idempotent
    with pytest.raises(login.LoginError) as error:
        rig.manager.status(flow.id)
    assert error.value.status == 410
    assert rig.apple._password_raw is None
    assert not rig.directories[0].exists()


def test_cancel_during_cookie_validation_does_not_save(rig):
    entered, release = threading.Event(), threading.Event()
    rig.apple.requires_2fa = False

    def validation(**kwargs):
        entered.set()
        assert release.wait(3)
        return {}

    rig.verifier.validate_session.side_effect = validation
    result = rig.manager.start(INPUT)
    try:
        assert entered.wait(2)
        rig.manager.cancel(result["flow_id"])
    finally:
        release.set()
    flow = idle(rig.manager, result["flow_id"])
    assert flow.client is None
    assert rig.accounts.accounts == {}


def test_busy_step_rejects_parallel_verification(rig):
    flow = start(rig)
    entered, release = threading.Event(), threading.Event()
    def validation(code):
        entered.set()
        assert release.wait(3)
        return False
    rig.apple.validate_2fa_code.side_effect = validation
    rig.manager.verify(flow.id, "123456")
    try:
        assert entered.wait(2)
        with pytest.raises(login.LoginError) as error:
            rig.manager.verify(flow.id, "123456")
        assert error.value.status == 409
    finally:
        release.set()
    idle(rig.manager, flow.id)


def test_capacity_and_code_format_validation(rig):
    rig.manager.MAX_FLOWS = 1
    flow = start(rig)
    with pytest.raises(login.LoginError) as error:
        rig.manager.start(INPUT)
    assert error.value.status == 429
    with pytest.raises(login.LoginError):
        rig.manager.verify(flow.id, "12x456")
    rig.apple.validate_2fa_code.assert_not_called()


def test_unavailable_automatic_delivery_accepts_an_existing_device_code(rig):
    rig.apple.two_factor_delivery_method = "unknown"
    rig.apple.request_2fa_code.return_value = False
    flow = start(rig)
    assert flow.state == "awaiting_code"
    assert rig.manager.status(flow.id)["delivery"] == "trusted_device_manual"
    rig.apple.use_existing_trusted_device_code.assert_called_once()
    assert rig.accounts.accounts == {}
    rig.manager.verify(flow.id, "123456")
    assert idle(rig.manager, flow.id).state == "complete"


def test_existing_device_code_retry_keeps_input_available_without_resending(rig):
    rig.apple.request_2fa_code.return_value = False
    flow = start(rig)
    for attempt in range(5):
        rig.manager.verify(flow.id, "000000")
        idle(rig.manager, flow.id)
        assert flow.state == ("failed" if attempt == 4 else "awaiting_code")
    rig.apple.request_2fa_code.assert_called_once()
    assert rig.accounts.accounts == {}


def test_security_key_discovered_during_delivery_cannot_use_device_code(rig):
    def require_key():
        rig.apple.two_factor_delivery_method = "security_key"
        return False
    rig.apple.request_2fa_code.side_effect = require_key
    assert start(rig).state == "failed"
    rig.apple.use_existing_trusted_device_code.assert_not_called()


def test_real_library_unknown_delivery_verifies_existing_device_code(rig, tmp_path):
    client = login.create_client(INPUT["apple_id"], INPUT["password"], str(tmp_path), "icloud.com")
    client.authenticate = Mock()
    client._requires_mfa = True
    client.session.cookies.set("X-APPLE-WEBAUTH-TOKEN", "synthetic-cookie", domain=".icloud.com")
    client.session.post = Mock()
    client.trust_session = Mock(side_effect=lambda: setattr(client, "_requires_mfa", False))
    rig.manager.client_factory = lambda *args: client
    flow = start(rig)
    assert flow.state == "awaiting_code"
    assert flow.delivery == "trusted_device_manual"
    rig.manager.verify(flow.id, "123456")
    assert idle(rig.manager, flow.id).state == "complete"
    assert client.session.post.call_count == 1
    assert client.session.post.call_args.args[0].endswith("/verify/trusteddevice/securitycode")
    assert client.session.post.call_args.kwargs["json"] == {"securityCode": {"code": "123456"}}
    client.trust_session.assert_called_once()


def scripted_apple(rig, tmp_path, responses, host="icloud.com"):
    """Exercise pyicloud's real verification/trust/token methods, not mocks."""
    client = login.create_client(INPUT["apple_id"], INPUT["password"], str(tmp_path), host)
    client.authenticate = Mock()
    client._requires_mfa = True
    client.session.data.update(session_token="synthetic-session", account_country="CHN")
    client.session.cookies.set("X-APPLE-WEBAUTH-TOKEN", "synthetic-cookie", domain="." + host)
    calls = []

    def send(request, **kwargs):
        calls.append(request)
        expected, status, body = responses.pop(0)
        assert request.url == expected
        if isinstance(status, Exception):
            raise status
        response = requests.Response()
        response.status_code = status
        response._content = json.dumps(body).encode() if body is not None else b""
        response.headers["Content-Type"] = "application/json"
        response.url = request.url
        response.request = request
        return response

    client.session.send = send
    rig.manager.client_factory = lambda *args: client
    return client, calls


AUTH = "https://idmsa.apple.com/appleauth/auth"
SETUP = "https://setup.icloud.com/setup/ws/1/accountLogin"
SETUP_CN = "https://setup.icloud.com.cn/setup/ws/1/accountLogin"


@pytest.mark.parametrize("host,target,setup", [
    ("icloud.com", "iCloud.com.cn", SETUP),
    ("icloud.com.cn", "iCloud.com", SETUP_CN),
])
def test_real_library_rejects_region_change_after_accepting_code(rig, tmp_path, host, target, setup):
    responses = [
        (AUTH + "/verify/trusteddevice/securitycode", 204, None),
        (AUTH + "/2sv/trust", 204, None),
        (setup, 302, {"domainToUse": target}),
    ]
    client, calls = scripted_apple(rig, tmp_path, responses, host)
    flow = start(rig, host=host)
    rig.manager.verify(flow.id, "123456")
    assert idle(rig.manager, flow.id).state == "failed"
    assert flow.code_accepted and flow.attempts == 0
    assert flow.host == host and client.is_china_mainland == (host == "icloud.com.cn")
    assert "未自动切换区域" in flow.error
    assert "你选择的是" + ("中国区" if host == "icloud.com.cn" else "国际区") in flow.error
    assert len(calls) == 3 and not responses
    rig.verifier_factory.assert_not_called()
    assert rig.accounts.accounts == {}


@pytest.mark.parametrize("host,setup", [("icloud.com", SETUP), ("icloud.com.cn", SETUP_CN)])
def test_real_library_completes_in_selected_region(rig, tmp_path, host, setup):
    responses = [
        (AUTH + "/verify/trusteddevice/securitycode", 204, None),
        (AUTH + "/2sv/trust", 204, None),
        (setup, 200, {"dsInfo": {**IDENTITY, "hsaVersion": 2}, "hsaTrustedBrowser": True, "webservices": {}}),
    ]
    _, calls = scripted_apple(rig, tmp_path, responses, host)
    # Omitting the region must default to international.
    flow = start(rig, **({"host": host} if host == "icloud.com.cn" else {}))
    rig.manager.verify(flow.id, "123456")
    assert idle(rig.manager, flow.id).state == "complete"
    assert flow.host == host
    assert calls[-1].headers["Origin"] == "https://www." + host
    assert rig.verifier_factory.call_args.kwargs["host"] == host
    assert rig.accounts.get_account(flow.account["id"])["host"] == host
    assert not responses


@pytest.mark.parametrize("host,target", [("icloud.com", "icloud.com.cn"), ("icloud.com.cn", "icloud.com")])
def test_cross_region_http_requests_are_blocked_before_sending(rig, host, target):
    send = Mock()
    rig.apple.session.send = send
    rig.apple.authenticate.side_effect = lambda: rig.apple.session.get("https://setup." + target + "/setup/ws/1/accountLogin")
    flow = start(rig, host=host)
    assert flow.state == "failed" and flow.host == host
    assert "未自动切换区域" in flow.error
    send.assert_not_called()


@pytest.mark.parametrize("failure", [403, requests.ReadTimeout("secret response")])
def test_real_library_session_failure_is_not_reported_as_an_incorrect_code(rig, tmp_path, failure):
    scripted_apple(rig, tmp_path, [
        (AUTH + "/verify/trusteddevice/securitycode", 204, None),
        (AUTH + "/2sv/trust", failure, {}),
    ])
    flow = start(rig)
    rig.manager.verify(flow.id, "123456")
    idle(rig.manager, flow.id)
    assert flow.state == ("awaiting_connection" if isinstance(failure, Exception) else "failed")
    assert flow.attempts == 0
    assert "验证码已通过" in flow.error
    assert "secret" not in flow.error
    assert rig.accounts.accounts == {}


@pytest.mark.parametrize("host,setup", [("icloud.com", SETUP), ("icloud.com.cn", SETUP_CN)])
def test_resume_keeps_selected_region_without_resubmitting_code(rig, tmp_path, host, setup):
    responses = [
        (AUTH + "/verify/trusteddevice/securitycode", 204, None),
        (AUTH + "/2sv/trust", 204, None),
        (setup, requests.ReadTimeout(), {}),
        (AUTH + "/2sv/trust", 204, None),
        (setup, 200, {"dsInfo": {**IDENTITY, "hsaVersion": 2}, "hsaTrustedBrowser": True, "webservices": {}}),
    ]
    _, calls = scripted_apple(rig, tmp_path, responses, host)
    flow = start(rig, host=host)
    with pytest.raises(login.LoginError):
        rig.manager.resume(flow.id)
    rig.manager.verify(flow.id, "123456")
    idle(rig.manager, flow.id)
    assert flow.state == "awaiting_connection" and flow.client is not None
    assert flow.host == host
    rig.manager.resume(flow.id)
    assert idle(rig.manager, flow.id).state == "complete"
    assert sum("/securitycode" in call.url for call in calls) == 1
    assert flow.host == host
    assert not responses


def test_resume_cookie_check_only_does_not_repeat_apple_verification(rig):
    flow = start(rig)
    flow.code_accepted = True
    rig.verifier.validate_session.side_effect = [TimeoutError(), {}]
    rig.manager.verify(flow.id, "123456")
    idle(rig.manager, flow.id)
    assert flow.state == "awaiting_connection" and flow.resume_step == "finish"
    rig.manager.resume(flow.id)
    assert idle(rig.manager, flow.id).state == "complete"
    rig.apple.validate_2fa_code.assert_called_once()


def test_cancelled_pending_connection_cannot_resume(rig):
    flow = start(rig)
    flow.code_accepted = True
    rig.verifier.validate_session.side_effect = TimeoutError()
    rig.manager.verify(flow.id, "123456")
    idle(rig.manager, flow.id)
    rig.manager.cancel(flow.id)
    with pytest.raises(login.LoginError) as error:
        rig.manager.resume(flow.id)
    assert error.value.status == 410 and flow.client is None


@pytest.mark.parametrize("target", ["https://example.test", "evilicloud.com.cn", "icloud.com"])
def test_region_redirect_never_follows_arbitrary_hosts_or_loops(rig, tmp_path, target):
    _, calls = scripted_apple(rig, tmp_path, [
        (AUTH + "/verify/trusteddevice/securitycode", 204, None),
        (AUTH + "/2sv/trust", 204, None),
        (SETUP, 302, {"domainToUse": target}),
    ])
    flow = start(rig)
    rig.manager.verify(flow.id, "123456")
    assert idle(rig.manager, flow.id).state == "failed"
    assert len(calls) == 3 and flow.attempts == 0
    assert rig.accounts.accounts == {}


def test_diagnostic_logs_include_stage_but_no_password_code_or_tokens(rig, tmp_path, caplog):
    caplog.set_level("INFO", logger="services.apple_login_service")
    scripted_apple(rig, tmp_path, [
        (AUTH + "/verify/trusteddevice/securitycode", 204, None),
        (AUTH + "/2sv/trust", requests.ReadTimeout("secret response"), {}),
    ])
    flow = start(rig)
    rig.manager.verify(flow.id, "123456")
    idle(rig.manager, flow.id)
    assert "phase=trust_session" in caplog.text
    assert all(value not in caplog.text for value in ("123456", INPUT["apple_id"], INPUT["password"], "synthetic-session", "secret response"))


def test_network_calls_are_bounded_and_expired_steps_cannot_continue(rig):
    send = Mock(return_value=Mock())
    rig.apple.session.send = send
    rig.apple.authenticate.side_effect = lambda: rig.apple.session.send(Mock(), timeout=None)
    flow = start(rig)
    assert send.call_args.kwargs["timeout"] == (10, 20)
    flow.deadline = time.monotonic() - 1
    with pytest.raises(TimeoutError):
        rig.apple.session.send(Mock())
    assert send.call_count == 1


def test_cleanup_failure_is_retried_without_losing_terminal_result(rig, monkeypatch):
    flow = start(rig)
    temporary = flow.temporary
    cleanup = Mock(side_effect=[OSError("busy"), None])
    monkeypatch.setattr(temporary, "cleanup", cleanup)
    rig.manager.cancel(flow.id)
    assert flow.temporary is temporary
    rig.manager.cleanup()
    assert flow.id not in rig.manager.flows
    assert cleanup.call_count == 2


def test_unsubscribed_login_is_saved_and_revalidation_detects_upgrade(rig, monkeypatch):
    rig.apple.requires_2fa = False
    rig.verifier.validate_session.return_value = {}
    flow = start(rig)
    account = rig.accounts.get_account(flow.account["id"])
    assert account["status"] == "warning" and account["hme_available"] is False
    rig.verifier.list_aliases.return_value = []
    monkeypatch.setattr("icloud_hme.ICloudHME", Mock(return_value=rig.verifier))
    account = rig.accounts.validate_account(account["id"])
    assert account["status"] == "active" and account["hme_available"] is True


def test_relogin_preserves_password_mailbox_notes_counts_and_identity(rig):
    account = rig.accounts.add_account("我的名称", '{"SESSION_TOKEN":"old"}', verified_identity=IDENTITY, hme_available=True)
    rig.accounts.update_account(account["id"], app_password="existing-app-password", icloud_email="custom@icloud.com", notes="备注", alias_total=99, alias_active=90)
    rig.apple.requires_2fa = False
    flow = start(rig, account_id=account["id"])
    updated = rig.accounts.get_account(account["id"])
    assert flow.account["id"] == account["id"] and len(rig.accounts.accounts) == 1
    assert updated["name"] == "我的名称"
    assert updated["app_password"] == "existing-app-password"
    assert updated["icloud_email"] == "custom@icloud.com"
    assert updated["notes"] == "备注"
    assert (updated["alias_total"], updated["alias_active"]) == (99, 90)


def test_relogin_cannot_replace_different_account(rig):
    account = rig.accounts.add_account("原账号", '{"SESSION_TOKEN":"old"}', verified_identity={**IDENTITY, "dsid": "other"}, hme_available=True)
    rig.apple.requires_2fa = False
    assert start(rig, account_id=account["id"]).state == "failed"
    assert rig.accounts.get_account(account["id"])["cookies"] == {"SESSION_TOKEN": "old"}


def test_concurrent_same_identity_imports_one_account(rig):
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        accounts = list(pool.map(lambda _: rig.accounts.add_account(
            "", '{"SESSION_TOKEN":"new"}', replace_existing=True,
            verified_identity=IDENTITY, hme_available=True), range(2)))
    assert accounts[0]["id"] == accounts[1]["id"]
    assert len(rig.accounts.accounts) == 1


@pytest.mark.parametrize("host", ["icloud.com", "icloud.com.cn"])
def test_real_library_constructs_without_network_and_verifies_tls(rig, tmp_path, host):
    client = login.create_client(INPUT["apple_id"], INPUT["password"], str(tmp_path), host)
    assert client.is_china_mainland == (host == "icloud.com.cn")
    assert client.session.verify is True
    login.AppleLoginManager._dispose(SimpleNamespace(client=client, temporary=None))
    assert client._password_raw is None


@pytest.mark.parametrize("host", ["icloud.com", "icloud.com.cn"])
@pytest.mark.parametrize("result", [200, 302, "timeout"])
def test_cookie_validation_uses_only_selected_region(rig, monkeypatch, host, result):
    client = ICloudHME({}, host=host, verbose=False)
    response = requests.Response()
    response.status_code = result if isinstance(result, int) else 200
    response._content = json.dumps({"dsInfo": IDENTITY}).encode()
    response.headers["Location"] = "https://setup." + ("icloud.com" if host == "icloud.com.cn" else "icloud.com.cn")
    request = Mock(return_value=response)
    if result == "timeout":
        request.side_effect = requests.Timeout()
    monkeypatch.setattr(client.session, "request", request)
    try:
        if result == 200:
            client.validate_session(max_attempts=1, require_hme=False)
        else:
            with pytest.raises(RuntimeError):
                client.validate_session(max_attempts=1, require_hme=False)
        request.assert_called_once()
        assert request.call_args.args[1].startswith("https://setup." + host + "/setup/ws/1/validate?")
        assert request.call_args.kwargs["allow_redirects"] is False
        assert client.host == host
        assert client.setup_url == "https://setup." + host + "/setup/ws/1"
    finally:
        client.session.close()


@pytest.mark.parametrize("data,require_hme,valid", [
    ({"dsInfo": IDENTITY}, False, True),
    ({"dsInfo": IDENTITY}, True, False),
    ({}, False, False),
    ({"dsInfo": {"dsid": None}}, False, False),
])
def test_cookie_validation_does_not_confuse_missing_subscription_and_invalid_identity(monkeypatch, data, require_hme, valid):
    client = ICloudHME({}, verbose=False)
    monkeypatch.setattr(client, "_request", Mock(return_value=data))
    try:
        if valid:
            assert client.validate_session(require_hme=require_hme) == data
        else:
            with pytest.raises(RuntimeError):
                client.validate_session(require_hme=require_hme)
    finally:
        client.session.close()


def test_routes_require_admin_and_handle_invalid_json_and_expired_flow(rig, monkeypatch):
    import app_core
    from routes import apple_login
    monkeypatch.setattr(apple_login, "manager", rig.manager)
    app = Flask(__name__)
    app_core.init_app(app)
    app.register_blueprint(apple_login.bp)
    client = app.test_client()
    for method, path in [("post", "/api/apple-login"), ("get", "/api/apple-login/missing"),
                         ("delete", "/api/apple-login/missing"), ("post", "/api/apple-login/missing/verify"),
                         ("post", "/api/apple-login/missing/resume")]:
        assert getattr(client, method)(path, json={}).status_code == 401
    with app.app_context():
        client.set_cookie(app_core.ADMIN_SESSION_COOKIE, app_core._admin_token())
    for payload in ([], None, {}, {**INPUT, "host": "other"}):
        assert client.post("/api/apple-login", json=payload).status_code == 400
    response = client.post("/api/apple-login", json=INPUT)
    assert response.status_code == 202
    assert "no-store" in response.headers["Cache-Control"]
    flow = idle(rig.manager, response.json["flow_id"])
    assert client.get(f"/api/apple-login/{flow.id}").json["state"] == "awaiting_code"
    assert client.post(f"/api/apple-login/{flow.id}/verify", json={"code": "123456"}).status_code == 202
    idle(rig.manager, flow.id)
    assert client.delete(f"/api/apple-login/{flow.id}").status_code == 200
    assert client.get(f"/api/apple-login/{flow.id}").status_code == 410
