"""Short-lived, administrator-only Apple sign-in flows.

Apple authentication stays on the server. Only independently validated iCloud
cookies are imported; the Apple password and library session are discarded.
"""
import concurrent.futures
import json
import logging
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests

from icloud_hme import ICloudHME, configure_icloud_proxy


class LoginError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def region_mismatch(host, target):
    regions = {"icloud.com": "国际区", "icloud.com.cn": "中国区"}
    return LoginError(f"你选择的是{regions[host]} iCloud，但 Apple 要求使用{regions[target]}。本次登录已停止，未自动切换区域。")


@dataclass
class LoginFlow:
    id: str
    name: str
    apple_id: str
    host: str
    expires: float
    state: str = "starting"
    error: str = ""
    delivery: str = "unknown"
    account: dict | None = None
    busy: bool = True
    cancelled: bool = False
    attempts: int = 0
    client: object = None
    temporary: object = None
    deadline: float = 0
    account_id: str = ""
    phase: str = "sign_in"
    http_status: int = 0
    code_accepted: bool = False
    resume_step: str = ""
    lock: object = field(default_factory=threading.RLock)


def create_client(apple_id, password, directory, host):
    from pyicloud import PyiCloudService
    from pyicloud.exceptions import PyiCloud2FARequiredException

    class RegionLockedClient(PyiCloudService):
        def trust_session(self):
            if not super().trust_session():
                raise LoginError("验证码已通过，但 Apple 尚未建立受信任的 iCloud 会话，请在 iCloud 官方网页确认账号状态后重试。")
            return True

        def _authenticate_with_token(self, require_trust=True):
            try:
                return super()._authenticate_with_token(require_trust=require_trust)
            except PyiCloud2FARequiredException as error:
                response = error.response
                target = str(self.data.get("domainToUse") or "").lower()
                current = "icloud.com.cn" if self.is_china_mainland else "icloud.com"
                if response is None or response.status_code != 302 or target not in ("icloud.com", "icloud.com.cn") or target == current:
                    raise
                raise region_mismatch(host, target) from None

    # No keyring access, family-device discovery, or automatic terms acceptance.
    client = RegionLockedClient(
        apple_id, password, cookie_directory=directory,
        china_mainland=host == "icloud.com.cn", authenticate=False,
        with_family=False, accept_terms=False, verify=True,
    )
    configure_icloud_proxy(client.session)
    return client


def connection_error(error):
    return isinstance(error, (TimeoutError, requests.ConnectionError, requests.Timeout)) or type(error).__name__ == "PyiCloudConnectionException"


def public_error(error):
    # Library errors may embed entire upstream responses. Do not return those.
    kind = type(error).__name__
    if kind == "PyiCloudAccountLockedException":
        return "Apple 账号已锁定，请先在 Apple 官方网站恢复账号。"
    if kind == "PyiCloudFailedLoginException":
        return "Apple 拒绝了登录，请检查账号、登录密码和账号区域。这里不能使用 App 专用密码。"
    if kind == "PyiCloudAcceptTermsException":
        return "请先登录 iCloud 官方网站确认更新后的条款，再回来重试。"
    if "SecurityKey" in kind:
        return "此账号需要安全密钥，当前验证码流程暂不支持，请改用 Cookie 导入。"
    if isinstance(error, (TimeoutError, requests.RequestException)) or "Connection" in kind:
        return "连接 Apple 超时或网络不可用，请稍后重试。"
    if isinstance(error, LoginError):
        return str(error)
    return "Apple 登录未完成，可能需要在官方页面完成额外验证。请重试或使用 Cookie 导入。"


class AppleLoginManager:
    TTL = 600
    MAX_FLOWS = 8

    def __init__(self, account_manager, client_factory=create_client, cleanup=True):
        self.accounts = account_manager
        self.client_factory = client_factory
        self.flows = {}
        self.lock = threading.RLock()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="apple-login")
        self.stop = threading.Event()
        if cleanup:
            threading.Thread(target=self._cleanup_loop, daemon=True, name="apple-login-cleanup").start()

    def _cleanup_loop(self):
        while not self.stop.wait(30):
            self.cleanup()

    @staticmethod
    def _dispose(flow):
        client, temporary = flow.client, flow.temporary
        if client is not None:
            client._password_raw = None
            flow.client = None
            try:
                client.session.close()
            except Exception:
                logging.getLogger(__name__).warning("Apple login session close failed")
            finally:
                client.session.cookies.clear()
                # Break the send-wrapper cycle holding this flow and client.
                client.session.__dict__.pop("send", None)
        if temporary is not None:
            try:
                temporary.cleanup()
                flow.temporary = None
            except OSError:
                # Retain the directory for the next cleanup pass (e.g. Windows
                # antivirus briefly holding a session file open).
                logging.getLogger(__name__).warning("Apple login temporary cleanup will be retried")

    def cleanup(self):
        with self.lock:
            for key, flow in list(self.flows.items()):
                with flow.lock:
                    if time.monotonic() >= flow.expires:
                        flow.cancelled = True
                        flow.state = "expired"
                    if not flow.busy and (flow.cancelled or flow.state in ("complete", "failed")):
                        self._dispose(flow)
                        if flow.cancelled and flow.temporary is None:
                            self.flows.pop(key, None)

    def start(self, data):
        apple_id = str(data.get("apple_id") or "").strip()
        password = data.get("password")
        host = data.get("host", "icloud.com")
        if not apple_id or len(apple_id) > 254 or not isinstance(password, str) or not password or len(password) > 1024:
            raise LoginError("请填写 Apple 账号和登录密码。")
        if host not in ("icloud.com", "icloud.com.cn"):
            raise LoginError("请选择正确的账号区域。")
        account_id = str(data.get("account_id") or "")
        if account_id and not self.accounts.get_account(account_id):
            raise LoginError("要重新登录的账号已不存在，请刷新账号列表。", 404)
        self.cleanup()
        with self.lock:
            if len(self.flows) >= self.MAX_FLOWS:
                for key, old in list(self.flows.items()):
                    if not old.busy and old.temporary is None and old.state in ("complete", "failed"):
                        self.flows.pop(key)
                        break
            if len(self.flows) >= self.MAX_FLOWS:
                raise LoginError("等待登录的账号较多，请完成或取消已有登录后再试。", 429)
            flow = LoginFlow(secrets.token_urlsafe(32), str(data.get("name") or "iCloud 登录账号").strip()[:100], apple_id, host, time.monotonic() + self.TTL)
            flow.account_id = account_id
            self.flows[flow.id] = flow
            self.pool.submit(self._run, flow, lambda: self._start(flow, password))
        return self.status(flow.id)

    def _lookup(self, flow_id):
        self.cleanup()
        with self.lock:
            flow = self.flows.get(flow_id)
        if flow is None or flow.cancelled:
            raise LoginError("这次登录已取消或过期，请重新开始。", 410)
        return flow

    def status(self, flow_id):
        flow = self._lookup(flow_id)
        with flow.lock:
            return {"ok": True, "flow_id": flow.id, "state": flow.state,
                    "error": flow.error, "delivery": flow.delivery,
                    "expires_in": max(0, int(flow.expires - time.monotonic())),
                    "account": flow.account}

    def cancel(self, flow_id):
        with self.lock:
            flow = self.flows.get(flow_id)
        if flow is not None:
            with flow.lock:
                flow.cancelled = True
                flow.state = "cancelled"
            self.cleanup()
        return {"ok": True}

    def verify(self, flow_id, code):
        code = str(code or "").strip()
        if not re.fullmatch(r"[0-9]{6}", code):
            raise LoginError("请输入六位数字验证码。")
        flow = self._lookup(flow_id)
        with flow.lock:
            if flow.busy or flow.state != "awaiting_code":
                raise LoginError("当前登录步骤不接受验证码，请等待或重新登录。", 409)
            flow.busy = True
            flow.state = "verifying"
            flow.error = ""
            self.pool.submit(self._run, flow, lambda: self._verify(flow, code))
        return self.status(flow.id)

    def resume(self, flow_id):
        flow = self._lookup(flow_id)
        with flow.lock:
            if flow.busy or flow.state != "awaiting_connection" or not flow.code_accepted:
                raise LoginError("当前登录步骤不能继续连接，请等待或重新登录。", 409)
            flow.busy = True
            flow.state = "connecting"
            flow.error = ""
            self.pool.submit(self._run, flow, lambda: self._resume(flow))
        return self.status(flow.id)

    @staticmethod
    def _check(flow):
        if flow.cancelled or time.monotonic() >= min(flow.expires, flow.deadline):
            raise TimeoutError()

    def _run(self, flow, operation):
        flow.deadline = min(flow.expires, time.monotonic() + 90)
        try:
            self._check(flow)
            operation()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Apple login failed phase=%s region=%s error=%s http_status=%s",
                flow.phase, flow.host, type(exc).__name__, flow.http_status,
            )
            with flow.lock:
                if not flow.cancelled:
                    flow.state = "failed"
                    flow.error = public_error(exc)
                    if flow.code_accepted and connection_error(exc) and time.monotonic() < flow.expires:
                        region = "中国区" if flow.host == "icloud.com.cn" else "国际区"
                        flow.state = "awaiting_connection"
                        flow.resume_step = "finish" if flow.phase == "validate_session" else "trust"
                        flow.error = f"验证码已通过，但连接{region} iCloud 暂时中断。请点击“继续连接”，无需重新输入验证码。"
        finally:
            with flow.lock:
                flow.busy = False
                if flow.cancelled or flow.state in ("complete", "failed"):
                    self._dispose(flow)

    def _start(self, flow, password):
        flow.temporary = tempfile.TemporaryDirectory(prefix="hme-apple-login-")
        flow.client = self.client_factory(flow.apple_id, password, flow.temporary.name, flow.host)
        send = flow.client.session.send

        def bounded_send(request, **kwargs):
            self._check(flow)
            parts = urlsplit(str(getattr(request, "url", "")))
            # Also stop HTTP Location redirects before another region is sent
            # any request. The selected region stays fixed for this flow.
            hostname = parts.hostname or ""
            for region in ("icloud.com", "icloud.com.cn"):
                if (hostname == region or hostname.endswith("." + region)) and region != flow.host:
                    raise region_mismatch(flow.host, region)
            if parts.hostname == "idmsa.apple.com":
                if parts.path.endswith(("/securitycode", "/bridge/code/validate")):
                    flow.phase = "verify_code"
                elif parts.path.endswith("/2sv/trust"):
                    # The library reaches this endpoint only after accepting
                    # the code. Later failures must not count as bad codes.
                    flow.phase = "trust_session"
                    flow.code_accepted = True
            elif parts.hostname in ("setup.icloud.com", "setup.icloud.com.cn"):
                flow.phase = "open_session"
            flow.http_status = 0
            remaining = min(flow.expires, flow.deadline) - time.monotonic()
            kwargs["timeout"] = (min(10, remaining), min(20, remaining))
            response = send(request, **kwargs)
            flow.http_status = getattr(response, "status_code", 0)
            if flow.phase in ("verify_code", "trust_session", "open_session"):
                logging.getLogger(__name__).info(
                    "Apple login response phase=%s region=%s http_status=%s",
                    flow.phase, flow.host, flow.http_status,
                )
            self._check(flow)
            return response

        flow.client.session.send = bounded_send
        flow.client.authenticate()
        self._check(flow)
        if flow.client.requires_2fa:
            self._await_code(flow)
            return
        if flow.client.requires_2sa:
            raise LoginError("此账号使用旧版两步验证，请使用 Cookie 导入。")
        self._finish(flow)

    def _await_code(self, flow):
        if flow.client.two_factor_delivery_method == "security_key":
            raise LoginError("此账号需要安全密钥，请使用 Cookie 导入。")
        # A false delivery result does not mean the device has no code: Apple
        # may have displayed it during sign-in without a supported resend route.
        manual = flow.delivery == "trusted_device_manual"
        if manual or not flow.client.request_2fa_code():
            if flow.client.two_factor_delivery_method == "security_key":
                raise LoginError("此账号需要安全密钥，请使用 Cookie 导入。")
            flow.client.use_existing_trusted_device_code()
            delivery = "trusted_device_manual"
        else:
            delivery = flow.client.two_factor_delivery_method
        self._check(flow)
        with flow.lock:
            flow.delivery = delivery
            flow.state = "awaiting_code"

    def _verify(self, flow, code):
        valid = flow.client.validate_2fa_code(code)
        self._check(flow)
        if not valid or flow.client.requires_2fa:
            if flow.code_accepted:
                raise LoginError("验证码已通过，但 Apple 尚未建立受信任的 iCloud 会话，请在 iCloud 官方网页确认账号状态后重试。")
            if flow.http_status == 412:
                raise LoginError("Apple 要求额外的账号确认，请先在 iCloud 官方网页完成提示的步骤，再回来登录。")
            if flow.http_status == 429 or isinstance(flow.http_status, int) and flow.http_status >= 500:
                raise LoginError("Apple 暂时无法完成验证，请稍后重新登录。")
            flow.attempts += 1
            if flow.attempts >= 5:
                raise LoginError("验证码多次未通过，请重新登录后再试。")
            # Request a fresh modern challenge, but keep existing-device code
            # entry usable when Apple has no automatic delivery route.
            self._await_code(flow)
            with flow.lock:
                flow.error = (
                    "验证码未通过，请输入当前 Apple 账号设备上显示的最新六位验证码。"
                    if flow.delivery == "trusted_device_manual"
                    else "验证码未通过，请输入设备或短信中新收到的验证码。"
                )
            return
        self._finish(flow)

    def _resume(self, flow):
        if flow.resume_step != "finish":
            flow.phase = "trust_session"
            if not flow.client.trust_session() or flow.client.requires_2fa:
                raise LoginError("Apple 尚未建立受信任的 iCloud 会话，请在官方网页确认账号状态后重试。")
            self._check(flow)
        self._finish(flow)

    def _finish(self, flow):
        with flow.lock:
            self._check(flow)
            flow.state = "importing"
        cookies = {}
        for cookie in sorted(flow.client.session.cookies, key=lambda c: len(c.domain)):
            domain = cookie.domain.lstrip(".").lower()
            if domain == flow.host or domain.endswith("." + flow.host):
                cookies[cookie.name] = cookie.value
        if not cookies:
            raise LoginError("Apple 登录尚未生成 iCloud 会话，请在 iCloud 官方网站完成账号初始化后重试。")
        verifier = ICloudHME(cookies, host=flow.host, verbose=False)
        flow.phase = "validate_session"
        try:
            data = verifier.validate_session(timeout=18, max_attempts=1, require_hme=False)
            info = verifier.get_account_info()
        finally:
            verifier.session.close()
        self._check(flow)
        if not info or not info.get("dsid"):
            raise LoginError("未取得有效的 Apple 账号身份，请重新登录。")
        with flow.lock:
            self._check(flow)
            if flow.account_id:
                existing = self.accounts.get_account(flow.account_id)
                if not existing or str(existing.get("dsid") or "") != str(info["dsid"]):
                    raise LoginError("本次登录与选中的账号不一致，请使用原账号登录，或通过“添加账号”连接新账号。")
            account = self.accounts.add_account(
                flow.name, json.dumps(cookies), flow.host, replace_existing=True,
                verified_identity=info,
                hme_available=bool(data.get("webservices", {}).get("premiummailsettings", {}).get("url")),
            )
            flow.account = {key: account.get(key) for key in ("id", "name", "status", "hme_available", "last_error")}
            flow.state = "complete"

    def shutdown(self):
        self.stop.set()
        for flow in list(self.flows.values()):
            self.cancel(flow.id)
        self.pool.shutdown(wait=True)
        self.cleanup()
