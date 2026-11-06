#!/usr/bin/env python3
"""
iCloud HME — 多账号管理器
===========================
管理多组 iCloud 账号及其隐私邮箱别名。

功能:
  - 账号 CRUD (增删改查)
  - Cookie 导入解析 (Header String / JSON)
  - 批量会话校验
  - 别名按账号归属索引
  - 跨账号并发/轮询创建

用法:
    from account_manager import AccountManager

    mgr = AccountManager()
    mgr.add_account("主号", cookie_header_string)
    mgr.create_aliases_batch(["acc_xxx", "acc_yyy"], count_per_account=5)
"""

import json
import random
import re
import time
import uuid
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

HERE = Path(__file__).resolve().parent
ACCOUNTS_FILE = HERE / "accounts.json"
OLD_COOKIES_FILE = HERE / "cookies.json"
RESULTS_DIR = HERE / "results"
LATEST_EMAILS = RESULTS_DIR / "latest_emails.txt"
ICLOUD_MAIL_DOMAINS = ("@icloud.com", "@me.com", "@mac.com", "@icloud.com.cn")
BATCH_ALIAS_DELAY_RANGE = (15.0, 45.0)
BATCH_ACCOUNT_DELAY_RANGE = (120.0, 300.0)
COOKIE_KEEP_NAMES = {
    "dslang",
    "site",
    "X-Apple-GCBD-Cookie",
    "X-APPLE-GCBD-Cookie",
    "X-APPLE-DS-WEB-SESSION-TOKEN",
    "X-APPLE-UNIQUE-CLIENT-ID",
    "X-APPLE-WEB-ID",
    "SESSION_TOKEN",
    "aosappleid",
    "appleId",
    "dsid",
}
COOKIE_KEEP_PREFIXES = (
    "X-APPLE-WEBAUTH",
    "X_APPLE_WEB_KB",
)

from mail_cache import get_cache  # noqa: E402
from services.status_model import AccountStatus  # noqa: E402


class AccountManager:
    """多账号管理器"""

    def __init__(self):
        self.accounts: Dict[str, Dict] = {}
        self._lock = threading.RLock()
        self._cache = get_cache()
        self._load()

    def _load(self):
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        if OLD_COOKIES_FILE.exists() and not ACCOUNTS_FILE.exists():
            try:
                self._migrate_old_cookies()
            except Exception:
                pass

        if ACCOUNTS_FILE.exists():
            try:
                data = json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))
                self.accounts = data.get("accounts", {})
                if self._sanitize_loaded_account_cookies():
                    self._save()
            except (json.JSONDecodeError, OSError):
                self.accounts = {}

    def _save(self):
        with self._lock:
            ACCOUNTS_FILE.write_text(
                json.dumps({
                    "accounts": self.accounts,
                    "updated_at": datetime.now().isoformat(),
                }, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )

    def _migrate_old_cookies(self):
        try:
            old = json.loads(OLD_COOKIES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(old, dict) or not old:
            return
        if {"version", "url", "data"}.issubset(old.keys()):
            return

        acc_id = self._generate_id()
        self.accounts[acc_id] = {
            "id": acc_id,
            "name": "默认账号",
            "real_email": "",
            "cookies": old,
            "host": "icloud.com",
            "status": "active",
            "alias_total": 0,
            "alias_active": 0,
            "last_validated": None,
            "last_error": None,
            "created_at": datetime.now().isoformat(),
        }
        self._save()
        try:
            OLD_COOKIES_FILE.rename(OLD_COOKIES_FILE.with_suffix(".json.bak"))
        except OSError:
            pass

    def _generate_id(self) -> str:
        return "acc_" + uuid.uuid4().hex[:8]

    @staticmethod
    def sanitize_cookies(cookies: Dict[str, Any]) -> Dict[str, str]:
        cleaned: Dict[str, str] = {}
        for raw_name, raw_value in (cookies or {}).items():
            name = str(raw_name or "").strip()
            value = str(raw_value or "").strip()
            if not name or not value:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            keep = name in COOKIE_KEEP_NAMES or any(name.startswith(prefix) for prefix in COOKIE_KEEP_PREFIXES)
            if keep:
                cleaned[name] = value
        return cleaned or {str(k): str(v).strip() for k, v in (cookies or {}).items() if k and v}

    def _sanitize_loaded_account_cookies(self) -> bool:
        changed = False
        for account in self.accounts.values():
            cookies = account.get("cookies")
            if not isinstance(cookies, dict):
                continue
            sanitized = self.sanitize_cookies(cookies)
            if sanitized != cookies:
                account["cookies"] = sanitized
                changed = True
        return changed

    @staticmethod
    def parse_cookie_input(raw: str) -> Dict[str, str]:
        def clean_cookie_value(value: Any) -> str:
            text = str(value).strip()
            if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
                return text[1:-1]
            return text

        raw = raw.strip()
        if not raw:
            raise ValueError("空白输入 — 请粘贴 Cookie Header String 或 JSON")

        cookie_header = re.search(r"(?im)^\s*cookie\s*:\s*(.+?)\s*$", raw)
        if not cookie_header:
            cookie_header = re.search(r"""(?is)-H\s+['"]cookie\s*:\s*(.+?)['"]""", raw)
        if cookie_header:
            raw = cookie_header.group(1).strip()

        if raw.startswith("{"):
            try:
                cookies = json.loads(raw)
                if isinstance(cookies, dict):
                    if {"version", "url", "data"}.issubset(cookies.keys()):
                        raise ValueError(
                            "这是 Cookie Manager 的加密备份格式，不能直接导入。"
                            "请复制 Request Headers 里的 Cookie: ...，或导出 Header String。"
                        )
                    return AccountManager.sanitize_cookies({k: clean_cookie_value(v) for k, v in cookies.items() if v})
            except json.JSONDecodeError:
                pass

        cookies: Dict[str, str] = {}
        for part in raw.split(";"):
            part = part.strip()
            if "=" in part:
                name, value = part.split("=", 1)
                name = name.strip()
                value = clean_cookie_value(value)
                if name:
                    cookies[name] = value

        if not cookies:
            raise ValueError(
                "无法解析 Cookie 输入。\n"
                "请提供 Header String 格式 (name=value; ...) 或 JSON 格式"
            )

        return AccountManager.sanitize_cookies(cookies)

    def add_account(
        self,
        name: str,
        cookie_input: str,
        host: str = "icloud.com",
        sync_aliases: bool = False,
        replace_existing: bool = False,
        verified_identity: Dict | None = None,
        hme_available: bool | None = None,
    ) -> Dict:
        from icloud_hme import ICloudHME

        cookies = self.parse_cookie_input(cookie_input)
        acc_id = self._generate_id()

        account: Dict[str, Any] = {
            "id": acc_id,
            "name": name,
            "dsid": "",
            "real_email": "",
            "icloud_email": "",
            "cookies": cookies,
            "host": host,
            "status": "active",
            "alias_total": 0,
            "alias_active": 0,
            "last_validated": None,
            "last_error": None,
            "created_at": datetime.now().isoformat(),
        }

        client = None
        try:
            if verified_identity is None or sync_aliases:
                client = ICloudHME(cookies, host=host, verbose=False)
            if verified_identity is None:
                client.validate_session(timeout=18, max_attempts=1)
                info = client.get_account_info()
            else:
                # Only the server-side Apple login flow supplies this identity,
                # after independently validating its exported iCloud cookies.
                info = verified_identity
            if info:
                account["dsid"] = str(info.get("dsid", "") or "")
                account["real_email"] = (
                    info.get("appleId", "")
                    or info.get("primaryEmail", "")
                )
                account["icloud_email"] = self._derive_icloud_email(info)
                if name.strip() in ("", "未命名账号", "iCloud 登录账号"):
                    account["name"] = account["icloud_email"] or account["real_email"] or name

            expected_email = name.strip().lower()
            validated_real = str(account.get("real_email") or "").strip().lower()
            validated_icloud = str(account.get("icloud_email") or "").strip().lower()
            if "@" in expected_email and expected_email not in (validated_real, validated_icloud):
                raise ValueError(
                    f"Cookie 校验出来是 {account.get('real_email') or account.get('icloud_email') or '未知账号'}，"
                    f"不是你输入的 {name}。请先在浏览器切换到正确 Apple ID 后重新生成 Cookie。"
                )

            if sync_aliases:
                try:
                    aliases = client.list_aliases()
                    account["alias_total"] = len(aliases)
                    account["alias_active"] = sum(
                        1 for a in aliases if a.get("active")
                    )
                except Exception:
                    pass

            account["last_validated"] = datetime.now().isoformat()
            account["last_error"] = None
            if hme_available is not None:
                account["hme_available"] = hme_available
                account["login_method"] = "apple"
                if not hme_available:
                    account["status"] = "warning"
                    account["last_error"] = "已登录 Apple，尚未检测到隐藏邮件地址服务。开通或家庭共享 iCloud+ 后请重新校验。"
        except Exception as e:
            if verified_identity is not None or (isinstance(e, ValueError) and "Cookie 校验出来" in str(e)):
                raise
            account["status"] = "error"
            account["last_error"] = str(e)[:300]
        finally:
            if client is not None:
                client.session.close()

        with self._lock:
            duplicate_id = None
            dsid = str(account.get("dsid") or "").strip()
            real_email = str(account.get("real_email") or "").strip().lower()
            if dsid or real_email:
                for existing_id, existing in self.accounts.items():
                    existing_dsid = str(existing.get("dsid") or "").strip()
                    existing_real = str(existing.get("real_email") or "").strip().lower()
                    if dsid and existing_dsid and dsid == existing_dsid:
                        duplicate_id = existing_id
                        break
                    if real_email and real_email == existing_real:
                        duplicate_id = existing_id
                        break
            if duplicate_id:
                if not replace_existing:
                    existing = self.accounts.get(duplicate_id, {})
                    raise ValueError(
                        f"账号已存在: {existing.get('real_email') or real_email}。"
                        "如果要添加新账号，请确认浏览器已切换到新的 Apple ID 后重新导出 Cookie。"
                    )
                existing = dict(self.accounts.get(duplicate_id, {}))
                if verified_identity is not None:
                    if not sync_aliases:
                        account["alias_total"] = existing.get("alias_total", 0)
                        account["alias_active"] = existing.get("alias_active", 0)
                    if existing.get("icloud_email"):
                        account["icloud_email"] = existing["icloud_email"]
                    if name.strip() in ("", "未命名账号", "iCloud 登录账号"):
                        account["name"] = existing.get("name") or account["name"]
                preserved_password = existing.get("app_password")
                preserved_created = existing.get("created_at")
                existing.update(account)
                existing["id"] = duplicate_id
                existing["created_at"] = preserved_created or account.get("created_at")
                if preserved_password and not existing.get("app_password"):
                    existing["app_password"] = preserved_password
                self.accounts[duplicate_id] = existing
                account = existing
            else:
                self.accounts[acc_id] = account
            self._save()
        return account

    def remove_account(self, acc_id: str) -> bool:
        if acc_id in self.accounts:
            del self.accounts[acc_id]
            self._save()
            return True
        return False

    def get_account(self, acc_id: str) -> Optional[Dict]:
        return self.accounts.get(acc_id)

    def list_accounts(self) -> List[Dict]:
        status_order = {
            AccountStatus.ACTIVE.value: 0,
            AccountStatus.WARNING.value: 1,
            AccountStatus.ERROR.value: 2,
        }
        return sorted(
            self.accounts.values(),
            key=lambda a: (status_order.get(a.get("status"), 3), a.get("created_at", "")),
        )

    def update_account(self, acc_id: str, **kwargs) -> Optional[Dict]:
        with self._lock:
            if acc_id in self.accounts:
                self.accounts[acc_id].update(kwargs)
                self._save()
                return dict(self.accounts[acc_id])
            return None

    @staticmethod
    def _is_icloud_mail_address(email_addr: str) -> bool:
        value = str(email_addr or "").strip().lower()
        return bool(value) and value.endswith(ICLOUD_MAIL_DOMAINS)

    @classmethod
    def _derive_icloud_email(cls, info: Dict) -> str:
        primary = str(info.get("primaryEmail", "") or "").strip()
        apple_id = str(info.get("appleId", "") or "").strip()

        if cls._is_icloud_mail_address(primary):
            return primary

        if cls._is_icloud_mail_address(apple_id):
            return apple_id

        if "@" in apple_id:
            local = apple_id.split("@", 1)[0].strip()
            if local:
                return f"{local}@icloud.com"

        return ""

    @staticmethod
    def _is_transient_account_error(error: str) -> bool:
        text = str(error or "").lower()
        return any(
            keyword in text
            for keyword in (
                "超时",
                "timeout",
                "timed out",
                "read timed out",
                "connect timeout",
                "connection aborted",
                "temporarily",
                "temporary",
                "network",
                "connection reset",
                "connection refused",
                "remote end closed",
            )
        )

    def validate_account(self, acc_id: str) -> Dict:
        from icloud_hme import ICloudHME

        account = self.accounts.get(acc_id)
        if not account:
            raise KeyError(f"账号不存在: {acc_id}")

        try:
            client = ICloudHME(
                account["cookies"],
                host=account.get("host", "icloud.com"),
                verbose=False,
            )
            client.validate_session()
            info = client.get_account_info()
            if info:
                account["dsid"] = str(info.get("dsid", "") or account.get("dsid", "") or "")
                account["real_email"] = (
                    info.get("appleId", "")
                    or info.get("primaryEmail", "")
                )
                existing = account.get("icloud_email", "")
                if not self._is_icloud_mail_address(existing):
                    account["icloud_email"] = self._derive_icloud_email(info)

            aliases = client.list_aliases()
            account["alias_total"] = len(aliases)
            account["alias_active"] = sum(
                1 for a in aliases if a.get("active")
            )
            account["status"] = "active"
            account["hme_available"] = True
            account["last_validated"] = datetime.now().isoformat()
            account["last_error"] = None
        except Exception as e:
            error_text = str(e)[:300]
            account["status"] = "warning" if self._is_transient_account_error(error_text) else "error"
            account["last_error"] = error_text

        self._save()
        return account

    def validate_all(self) -> List[Dict]:
        results: List[Dict] = []
        for acc_id in list(self.accounts.keys()):
            try:
                account = self.validate_account(acc_id)
                results.append({
                    "id": acc_id,
                    "ok": account.get("status") == "active",
                    "email": account.get("real_email", ""),
                    "alias_total": account.get("alias_total", 0),
                })
            except Exception as e:
                results.append({
                    "id": acc_id,
                    "ok": False,
                    "error": str(e)[:200],
                })
        return results

    def get_client(self, acc_id: str, verbose: bool = False):
        from icloud_hme import ICloudHME

        account = self.accounts.get(acc_id)
        if not account:
            raise KeyError(f"账号不存在: {acc_id}")
        return ICloudHME(
            account["cookies"],
            host=account.get("host", "icloud.com"),
            verbose=verbose,
        )

    def set_app_password(self, acc_id: str, app_password: str):
        with self._lock:
            if acc_id not in self.accounts:
                raise KeyError(f"账号不存在: {acc_id}")
            self.accounts[acc_id]["app_password"] = app_password
            self._save()

    def get_mail_client(self, acc_id: str, verbose: bool = False):
        from icloud_mail import ICloudMail

        account = self.accounts.get(acc_id)
        if not account:
            raise KeyError(f"账号不存在: {acc_id}")
        app_pwd = account.get("app_password", "")
        imap_email = account.get("icloud_email", "")
        if imap_email and not self._is_icloud_mail_address(imap_email):
            raise ValueError(
                "iCloud 邮箱填写不正确。\n"
                "{} 不是 iCloud Mail 地址，不能用于 IMAP 收件。\n"
                "这里要填 @icloud.com / @me.com / @mac.com 邮箱，Apple ID 可以继续是 {}。".format(
                    imap_email,
                    account.get("real_email", "?"),
                )
            )
        if not imap_email:
            real = account.get("real_email", "")
            if self._is_icloud_mail_address(real):
                imap_email = real
            else:
                raise ValueError(
                    "未设置 iCloud 邮箱。\n"
                    "Apple ID ({}) 不是 iCloud 地址，\n"
                    "请点击下方按钮输入你的 @icloud.com 邮箱".format(
                        account.get("real_email", "?")
                    )
                )
        if not app_pwd:
            raise ValueError(
                "未设置 App 专用密码。\n"
                "请点击下方按钮，输入 @icloud.com 邮箱和应用密码"
            )
        return ICloudMail(
            imap_email,
            app_pwd,
            verbose=verbose,
            region_host=account.get("host", "icloud.com"),
        )

    def check_inbox(self, acc_id: str, limit: int = 50, days: int = 7,
                    force: bool = False) -> List[Dict]:
        cached = self._cache.get_inbox(acc_id)
        age = self._cache.cache_age_seconds(acc_id)

        if not force and cached and age < 300:
            return cached[:limit]

        mail = None
        try:
            mail = self.get_mail_client(acc_id)
            new_msgs = mail.check_inbox(limit=limit, days=days)
        except Exception:
            if cached:
                return cached[:limit]
            raise
        finally:
            if mail is not None:
                mail.disconnect()

        if new_msgs:
            self._cache.set_inbox(acc_id, new_msgs)

        return self._cache.get_inbox(acc_id)[:limit]

    def check_alias_mail(self, acc_id: str, alias_email: str,
                         limit: int = 20, days: int = 30,
                         force: bool = False) -> List[Dict]:
        cached = self._cache.get_alias_mail(acc_id, alias_email)
        age = self._cache.cache_age_seconds(acc_id)

        if not force and cached and age < 300:
            return cached[:limit]

        mail = None
        try:
            mail = self.get_mail_client(acc_id)
            new_msgs = mail.find_by_recipient(alias_email, limit=limit, days=days)
        except Exception:
            if cached:
                return cached[:limit]
            raise
        finally:
            if mail is not None:
                mail.disconnect()

        if new_msgs:
            self._cache.set_alias_mail(acc_id, alias_email, new_msgs)

        return self._cache.get_alias_mail(acc_id, alias_email)[:limit]

    def check_all_aliases_mail(self, acc_id: str, limit_per: int = 5,
                               days: int = 14,
                               force: bool = False,
                               max_aliases: int = 0,
                               mail_limit: int = 100) -> Dict[str, List[Dict]]:
        cached = self._cache.get_all_alias_mail(acc_id)
        age = self._cache.cache_age_seconds(acc_id)

        if not force and cached and age < 300:
            results = {}
            for alias, msgs in list(cached.items())[:max_aliases or None]:
                results[alias] = msgs[:limit_per]
            return results

        from icloud_hme import ICloudHME

        try:
            client = self.get_client(acc_id, verbose=False)
            aliases = client.list_aliases()
            if max_aliases and max_aliases > 0:
                aliases = aliases[:max_aliases]
        except Exception:
            if cached:
                return {
                    alias: msgs[:limit_per]
                    for alias, msgs in list(cached.items())[:max_aliases or None]
                }
            raise

        alias_set = {a.get("email", "").lower() for a in aliases if a.get("email")}
        if not alias_set:
            return cached if cached else {}

        try:
            mail = self.get_mail_client(acc_id)
            try:
                scan = mail.scan_alias_usage(
                    alias_set,
                    limit=mail_limit,
                    days=days,
                    mailboxes=["INBOX"],
                    limit_per_alias=limit_per,
                    fetch_bodies=min(80, max(10, mail_limit)),
                )
            finally:
                mail.disconnect()
        except Exception:
            if cached:
                return {
                    alias: msgs[:limit_per]
                    for alias, msgs in list(cached.items())[:max_aliases or None]
                }
            raise

        results: Dict[str, List[Dict]] = scan.get("by_alias", {}) if isinstance(scan, dict) else {}

        if results:
            self._cache.set_alias_mail_batch(acc_id, results)

        return results

    def calibrate_alias_usage(
        self,
        acc_id: str,
        aliases: List[str],
        limit: int = 1500,
        days: int = 365,
        all_mailboxes: bool = True,
        limit_per_alias: int = 10,
        fetch_bodies: int = 80,
    ) -> Dict:
        aliases = [str(x or "").strip().lower() for x in aliases if str(x or "").strip()]
        if not aliases:
            return {"by_alias": {}, "scanned": 0, "matched": 0, "body_fetched": 0, "mailboxes": []}
        mail = self.get_mail_client(acc_id)
        try:
            mailboxes = mail.list_mailboxes() if all_mailboxes else ["INBOX"]
            result = mail.scan_alias_usage(
                aliases,
                limit=limit,
                days=days,
                mailboxes=mailboxes,
                limit_per_alias=limit_per_alias,
                fetch_bodies=fetch_bodies,
            )
        finally:
            mail.disconnect()
        by_alias = result.get("by_alias") or {}
        if by_alias:
            self._cache.set_alias_mail_batch(acc_id, by_alias)
            for msgs in by_alias.values():
                for msg in msgs or []:
                    if msg.get("id") and msg.get("body"):
                        self._cache.set_message(acc_id, str(msg["id"]), msg)
        return result

    def test_imap_connection(self, acc_id: str) -> Dict:
        try:
            mail = self.get_mail_client(acc_id)
            result = mail.test_connection()
            mail.disconnect()
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    def create_aliases_for_account(
        self,
        acc_id: str,
        count: int = 1,
        label: str = "",
        delay_range: Optional[tuple[float, float]] = None,
    ) -> List[Dict]:
        from icloud_hme import ICloudHME

        account = self.accounts.get(acc_id)
        if not account:
            raise KeyError(f"账号不存在: {acc_id}")

        client = ICloudHME(
            account["cookies"],
            host=account.get("host", "icloud.com"),
            verbose=False,
        )

        results: List[Dict] = []
        for i in range(count):
            try:
                alias_label = label or (
                    f"{account.get('name', acc_id)} "
                    f"{datetime.now().strftime('%m%d%H%M')}-{i + 1}"
                )
                result = client.create_alias(label=alias_label, max_retries=3)
                email = result.get("email", "")
                if email:
                    results.append({
                        "email": email,
                        "account_id": acc_id,
                        "ok": True,
                        "created_at": result.get("created_at") or datetime.now().isoformat(timespec="seconds"),
                    })
                    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
                    with open(str(LATEST_EMAILS), "a", encoding="utf-8") as f:
                        f.write(f"{email}\t{acc_id}\n")
                    account["alias_total"] = account.get("alias_total", 0) + 1
                    account["alias_active"] = account.get("alias_active", 0) + 1
                else:
                    results.append({
                        "email": None,
                        "account_id": acc_id,
                        "ok": False,
                        "error": "create_alias 返回空邮箱",
                    })
            except Exception as e:
                err_str = str(e)
                results.append({
                    "email": None,
                    "account_id": acc_id,
                    "ok": False,
                    "error": err_str[:200],
                })
                lower = err_str.lower()
                if any(kw in lower for kw in (
                    "limit", "exceeded", "maximum", "quota", "429",
                    "too many", "rate", "throttle",
                )):
                    break
            if i < count - 1 and delay_range:
                low, high = delay_range
                time.sleep(random.uniform(max(0.0, low), max(low, high)))

        self._save()
        return results

    def create_aliases_batch(
        self,
        account_ids: List[str],
        count_per_account: int = 1,
        interval_sec: Optional[float] = None,
        label: str = "",
        alias_delay_range: tuple[float, float] = BATCH_ALIAS_DELAY_RANGE,
        account_delay_range: tuple[float, float] = BATCH_ACCOUNT_DELAY_RANGE,
    ) -> Dict[str, List[Dict]]:
        all_results: Dict[str, List[Dict]] = {}
        for i, acc_id in enumerate(account_ids):
            if acc_id not in self.accounts:
                all_results[acc_id] = [{
                    "email": None, "account_id": acc_id,
                    "ok": False, "error": "账号不存在",
                }]
                continue
            if self.accounts[acc_id].get("status") != "active":
                all_results[acc_id] = [{
                    "email": None, "account_id": acc_id,
                    "ok": False, "error": "账号不可用",
                }]
                continue

            results = self.create_aliases_for_account(
                acc_id,
                count_per_account,
                label,
                delay_range=alias_delay_range,
            )
            all_results[acc_id] = results

            if i < len(account_ids) - 1:
                low, high = account_delay_range
                time.sleep(random.uniform(max(0.0, low), max(low, high)))

        return all_results

    def get_aliases_for_account(self, acc_id: str) -> List[Dict]:
        try:
            client = self.get_client(acc_id, verbose=False)
            return client.list_aliases()
        except Exception:
            return []

    def get_all_aliases(self) -> List[Dict]:
        all_aliases: List[Dict] = []
        for acc_id, account in self.accounts.items():
            for alias in self.get_aliases_for_account(acc_id):
                alias["account_id"] = acc_id
                alias["account_name"] = account.get("name", "")
                alias["account_email"] = account.get("real_email", "")
                all_aliases.append(alias)
        return all_aliases

    def _remove_local_email(self, email: str) -> None:
        email = (email or "").strip().lower()
        if not email or not LATEST_EMAILS.exists():
            return
        try:
            lines = LATEST_EMAILS.read_text(encoding="utf-8").splitlines()
            kept = []
            for line in lines:
                first = line.split("\t", 1)[0].strip().lower()
                if first != email:
                    kept.append(line)
            LATEST_EMAILS.write_text(("\n".join(kept) + ("\n" if kept else "")), encoding="utf-8")
        except OSError:
            pass

    def _resolve_alias_identity(
        self, client: Any, anonymous_id: str = "", email: str = ""
    ) -> Dict:
        anonymous_id = (anonymous_id or "").strip()
        email = (email or "").strip().lower()
        if not email and anonymous_id:
            return {"anonymousId": anonymous_id}

        for alias in client.list_aliases():
            if anonymous_id and alias.get("anonymousId") == anonymous_id:
                return alias
            if email and str(alias.get("email", "")).strip().lower() == email:
                return alias

        if anonymous_id:
            return {"anonymousId": anonymous_id, "email": email}
        raise ValueError("缺少 anonymousId，请先从 iCloud 云端同步别名")

    def update_alias_label(
        self, acc_id: str, anonymous_id: str, label: str, email: str = ""
    ) -> bool:
        client = self.get_client(acc_id, verbose=False)
        alias = self._resolve_alias_identity(client, anonymous_id, email)
        alias_id = alias.get("anonymousId") or anonymous_id
        if not alias_id:
            raise ValueError("缺少 anonymousId，请先从 iCloud 云端同步别名")
        ok = client.update_label(
            alias_id,
            label,
            note=alias.get("note", ""),
            email=alias.get("email", email),
        )
        if ok:
            self.validate_account(acc_id)
        return ok

    def delete_alias(self, acc_id: str, anonymous_id: str, email: str = "") -> Dict:
        """Resolve the current account's alias before any destructive request."""
        client = self.get_client(acc_id, verbose=False)
        email = (email or "").strip().lower()
        anonymous_id = (anonymous_id or "").strip()
        try:
            aliases = client.list_aliases()
            by_id = next((a for a in aliases if anonymous_id and a.get("anonymousId") == anonymous_id), None)
            if by_id and email and by_id.get("email", "").lower() != email:
                raise ValueError("邮箱地址与云端标识不一致，请先同步云端列表。")
            alias = next((a for a in aliases if a.get("email", "").lower() == email), None) if email else by_id
            if alias is None:
                if not email:
                    raise ValueError("该别名已不在此账号的 iCloud 列表中，请先同步云端列表。")
                self._remove_local_email(email)
                return {"deleted": False, "already_absent": True, "email": email}
            alias_id = alias.get("anonymousId")
            if not alias_id:
                raise ValueError("缺少 anonymousId，请先从 iCloud 云端同步别名")
            if client.delete(alias_id, active=alias["active"]) is not True:
                raise RuntimeError("Apple 未确认删除，工作台记录已保留。")
            email = alias["email"]
            self._remove_local_email(email)
            self.validate_account(acc_id)
            return {"deleted": True, "already_absent": False, "email": email}
        finally:
            client.session.close()

    def get_summary(self) -> Dict:
        total_aliases = sum(
            a.get("alias_total", 0) for a in self.accounts.values()
        )
        total_active = sum(
            a.get("alias_active", 0) for a in self.accounts.values()
        )
        active_accounts = sum(
            1 for a in self.accounts.values() if a.get("status") == "active"
        )
        warning_accounts = sum(
            1 for a in self.accounts.values() if a.get("status") == "warning"
        )
        error_accounts = sum(
            1 for a in self.accounts.values() if a.get("status") == "error"
        )
        return {
            "account_count": len(self.accounts),
            "active_accounts": active_accounts,
            "warning_accounts": warning_accounts,
            "error_accounts": error_accounts,
            "total_aliases": total_aliases,
            "total_active_aliases": total_active,
        }


if __name__ == "__main__":
    print("AccountManager 自测")
    mgr = AccountManager()
    summary = mgr.get_summary()
    print(f"当前账号数: {summary['account_count']}")
    
    header = "X_APPLE_WEB_KB=abc123; SESSION_TOKEN=xyz789"
    parsed = mgr.parse_cookie_input(header)
    print(f"Header String → {len(parsed)} 个 cookie")
    
    json_in = '{"X_APPLE_WEB_KB":"abc123","SESSION_TOKEN":"xyz789"}'
    parsed2 = mgr.parse_cookie_input(json_in)
    print(f"JSON → {len(parsed2)} 个 cookie")
    
    print("自测完成 ✓")
