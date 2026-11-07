import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from flask import Flask
from requests.cookies import RequestsCookieJar

from services.alias_delete_service import AliasDeleteJobs, DeleteJobError


class FakeAccounts:
    def __init__(self, count=24):
        self.aliases = {f"id-{i}": {"email": f"box-{i}@example.test", "anonymousId": f"id-{i}", "active": True} for i in range(count)}
        self.lock = threading.Lock()
        self.clients = []
        self.list_calls = 0
        self.delete_calls = []
        self.inflight = self.peak = 0
        self.started = threading.Event()
        self.release = threading.Event()
        self.release.set()
        self.fail = ""
        self.fail_list = False
        self.update_account = Mock()

    def get_account(self, key):
        return {"id": key} if key == "account" else None

    def get_client(self, *_args, **_kwargs):
        owner = self

        class Client:
            _service_url = "https://synthetic.example.test"

            def __init__(self):
                self.session = SimpleNamespace(cookies=RequestsCookieJar(), close=Mock())

            def list_aliases(self, **kwargs):
                assert kwargs == {"timeout": 15, "max_attempts": 1}
                with owner.lock:
                    owner.list_calls += 1
                    if owner.fail_list:
                        raise RuntimeError("list failed")
                    return list(owner.aliases.values())

            def delete(self, anonymous_id, active):
                with owner.lock:
                    owner.inflight += 1
                    owner.peak = max(owner.peak, owner.inflight)
                    owner.delete_calls.append((anonymous_id, active, id(self)))
                owner.started.set()
                try:
                    assert owner.release.wait(3)
                    time.sleep(0.01)
                    if owner.fail:
                        raise RuntimeError(owner.fail)
                    with owner.lock:
                        del owner.aliases[anonymous_id]
                    return True
                finally:
                    with owner.lock:
                        owner.inflight -= 1

        client = Client()
        self.clients.append(client)
        return client


def payload(accounts, request_id="test-batch-001"):
    return {"request_id": request_id, "items": [{**a, "account_id": "account"} for a in accounts.aliases.values()]}


def finished(jobs, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = jobs.status(job_id)
        if status["state"] == "complete":
            return status
        time.sleep(0.01)
    raise AssertionError("job did not finish")


@pytest.fixture
def rig():
    accounts = FakeAccounts()
    record = Mock()
    jobs = AliasDeleteJobs(accounts, record)
    yield SimpleNamespace(accounts=accounts, jobs=jobs, record=record)
    accounts.release.set()
    jobs.shutdown()


def test_24_deletes_reuse_list_and_two_independent_sessions(rig):
    job = rig.jobs.start(payload(rig.accounts))
    result = finished(rig.jobs, job["job_id"])
    assert result["deleted"] == result["completed"] == result["total"] == 24
    assert result["failed"] == 0
    assert rig.accounts.list_calls == 2  # initial lookup plus final count refresh
    assert len(rig.accounts.clients) == 3  # reader and two reusable worker sessions
    assert rig.accounts.peak == 2
    assert len(rig.accounts.delete_calls) == rig.record.call_count == 24
    assert len({c[2] for c in rig.accounts.delete_calls}) == 2
    rig.accounts.update_account.assert_called_once_with("account", alias_total=0, alias_active=0)
    assert all(c.session.close.call_count == 1 for c in rig.accounts.clients)


def test_duplicate_submission_and_polling_never_replay_deletes(rig):
    rig.accounts.release.clear()
    data = payload(rig.accounts)
    first = rig.jobs.start(data)
    assert rig.accounts.started.wait(2)
    second = rig.jobs.start(data)
    assert first["job_id"] == second["job_id"]
    assert rig.jobs.active()["job"]["job_id"] == first["job_id"]
    with pytest.raises(DeleteJobError) as error:
        rig.jobs.start({**data, "request_id": "another-batch"})
    assert error.value.status == 409
    rig.accounts.release.set()
    result = finished(rig.jobs, first["job_id"])
    assert rig.jobs.start(data) == result
    assert len(rig.accounts.delete_calls) == 24


def test_mismatch_and_absent_addresses_do_not_send_deletions(rig):
    data = {"request_id": "test-identity", "items": [
        {"email": "other@example.test", "anonymousId": "id-0", "account_id": "account"},
        {"email": "absent@example.test", "anonymousId": "old-id", "account_id": "account"},
    ]}
    result = finished(rig.jobs, rig.jobs.start(data)["job_id"])
    assert result["failed"] == result["absent"] == 1
    assert not rig.accounts.delete_calls
    assert rig.record.call_count == 1


def test_missing_cached_ids_are_resolved_by_email_from_the_current_account(rig):
    rows = payload(rig.accounts)["items"][:3]
    rows[0]["anonymousId"] = ""
    rows[1].pop("anonymousId")
    rows[2]["anonymousId"] = None
    result = finished(rig.jobs, rig.jobs.start({"request_id": "missing-cached-ids", "items": rows})["job_id"])
    assert result["deleted"] == 3 and result["failed"] == 0
    assert {call[0] for call in rig.accounts.delete_calls} == {"id-0", "id-1", "id-2"}
    assert rig.accounts.list_calls == 2
    assert rig.record.call_count == 3


def test_missing_cached_id_and_absent_email_never_send_a_cloud_deletion(rig):
    data = {"request_id": "missing-and-absent", "items": [
        {"email": "absent@example.test", "account_id": "account", "anonymousId": ""},
    ]}
    result = finished(rig.jobs, rig.jobs.start(data)["job_id"])
    assert result["absent"] == 1 and result["deleted"] == 0
    assert not rig.accounts.delete_calls
    rig.record.assert_called_once_with("account", {"email": "absent@example.test", "deleted": False, "already_absent": True})


def test_missing_cached_id_with_failed_cloud_lookup_is_not_treated_as_absent(rig):
    rig.accounts.fail_list = True
    row = {"email": "box-0@example.test", "account_id": "account", "anonymousId": ""}
    result = finished(rig.jobs, rig.jobs.start({"request_id": "missing-id-list-fails", "items": [row]})["job_id"])
    assert result["failed"] == 1 and result["absent"] == result["deleted"] == 0
    assert not rig.accounts.delete_calls
    rig.record.assert_not_called()


@pytest.mark.parametrize("changes,message", [
    ({"account_id": "missing-account", "anonymousId": ""}, "所属账号不存在"),
    ({"anonymousId": 123}, "云端标识格式无效"),
    ({"email": "invalid"}, "邮箱地址无效"),
])
def test_invalid_identity_is_rejected_with_a_specific_reason(rig, changes, message):
    row = {**payload(rig.accounts)["items"][0], **changes}
    with pytest.raises(DeleteJobError, match=message):
        rig.jobs.start({"request_id": "invalid-identity", "items": [row]})
    assert not rig.accounts.clients


def test_rate_limiting_stops_remaining_requests_and_retains_failed_rows(rig):
    rig.accounts.fail = "HTTP 429: rate limit"
    result = finished(rig.jobs, rig.jobs.start(payload(rig.accounts))["job_id"])
    assert result["failed"] == 24 and result["deleted"] == 0
    assert len(rig.accounts.delete_calls) <= 2
    rig.record.assert_not_called()


def test_list_failure_never_guesses_absence(rig):
    rig.accounts.fail_list = True
    result = finished(rig.jobs, rig.jobs.start(payload(rig.accounts))["job_id"])
    assert result["failed"] == 24 and result["absent"] == 0
    assert not rig.accounts.delete_calls
    rig.record.assert_not_called()


def test_local_write_failure_does_not_replay_confirmed_cloud_deletion(rig):
    rig.record.side_effect = OSError("disk failure")
    data = payload(rig.accounts)
    result = finished(rig.jobs, rig.jobs.start(data)["job_id"])
    assert result["deleted"] == 24 and result["failed"] == 0
    assert all("本地状态保存失败" in r["error"] for r in result["items"])
    assert rig.jobs.start(data)["completed"] == 24
    assert len(rig.accounts.delete_calls) == 24


@pytest.mark.parametrize("data", [None, {}, {"request_id": "request-1", "items": []}, {"request_id": "request-1", "items": [None]}])
def test_invalid_input_does_not_start_work(rig, data):
    with pytest.raises(DeleteJobError):
        rig.jobs.start(data)
    assert not rig.accounts.clients


def test_batch_routes_are_admin_only(rig, monkeypatch):
    import app_core
    from routes import accounts
    monkeypatch.setattr(accounts, "_delete_jobs", rig.jobs)
    app = Flask(__name__)
    app_core.init_app(app)
    app.register_blueprint(accounts.bp)
    client = app.test_client()
    assert client.post("/api/alias-deletions", json=payload(rig.accounts)).status_code == 401
    assert client.get("/api/alias-deletions/active").status_code == 401
    assert client.get("/api/alias-deletions/missing").status_code == 401
    assert not rig.accounts.clients
    with app.app_context():
        client.set_cookie(app_core.ADMIN_SESSION_COOKIE, app_core._admin_token())
    assert client.get("/api/alias-deletions/missing").status_code == 410
    response = client.post("/api/alias-deletions", json=payload(rig.accounts))
    assert response.status_code == 202
    assert "no-store" in response.headers["Cache-Control"]
    assert finished(rig.jobs, response.json["job_id"])["deleted"] == 24
