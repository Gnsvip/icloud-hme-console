"""Verify the Apple-only proxy route without sending any network traffic."""
import json
from types import SimpleNamespace

import pytest
import requests

from icloud_hme import ICloudHME, configure_icloud_proxy
from services.apple_login_service import AppleLoginManager, create_client


@pytest.mark.parametrize("kind", ["login", "hme"])
@pytest.mark.parametrize("host", ["icloud.com", "icloud.com.cn"])
def test_apple_requests_use_dedicated_proxy_and_keep_tls_validation(monkeypatch, tmp_path, kind, host):
    proxy = "http://127.0.0.1:7892"
    monkeypatch.setenv("ICLOUD_PROXY_URL", proxy)
    monkeypatch.setenv("HTTPS_PROXY", "http://unused.example.test:8080")
    monkeypatch.setenv("NO_PROXY", "*")
    calls = []

    def send(adapter, request, **kwargs):
        calls.append((request.url, kwargs))
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"ok": True}).encode()
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", send)
    if kind == "login":
        client = create_client("demo@example.test", "synthetic-password", str(tmp_path), host)
    else:
        client = ICloudHME({}, host=host, verbose=False)
    try:
        url = "https://setup." + host + "/setup/ws/1/validate"
        client.session.get(url, timeout=3)
        assert len(calls) == 1
        assert calls[0][0] == url
        assert calls[0][1]["proxies"]["https"] == proxy
        assert calls[0][1]["verify"] is True
        with requests.Session() as unrelated:
            assert unrelated.proxies == {} and unrelated.trust_env
    finally:
        if kind == "login":
            AppleLoginManager._dispose(SimpleNamespace(client=client, temporary=None))
        else:
            client.session.close()


def test_no_dedicated_proxy_preserves_existing_session_configuration(monkeypatch):
    monkeypatch.delenv("ICLOUD_PROXY_URL", raising=False)
    with requests.Session() as session:
        session.proxies["https"] = "http://existing.example.test:8080"
        configure_icloud_proxy(session)
        assert session.trust_env
        assert session.proxies == {"https": "http://existing.example.test:8080"}


def test_invalid_proxy_does_not_expose_credentials_or_silently_use_direct_connection(monkeypatch):
    monkeypatch.setenv("ICLOUD_PROXY_URL", "socks://user:synthetic-secret@example.test:1080")
    with requests.Session() as session:
        with pytest.raises(ValueError) as error:
            configure_icloud_proxy(session)
        assert "synthetic-secret" not in str(error.value)
