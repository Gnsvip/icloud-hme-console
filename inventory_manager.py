#!/usr/bin/env python3
"""Inventory and code-desk helpers for the iCloud HME web UI."""
from __future__ import annotations

import email
import html
import imaplib
import json
import copy
import os
import tempfile
from collections import OrderedDict
import re
import ssl
import threading
import time
import uuid
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import requests

from services.deactivation_service import detect_deactivation_notice
from imap_runtime import open_imap, close_imap


HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
INVENTORY_FILE = RESULTS_DIR / "inventory.json"
FORWARD_CONFIG_FILE = HERE / "mail-forward.config.json"
AUTO_STOCK_FILE = RESULTS_DIR / "auto_stock.json"
COOKIE_BRIDGE_FILE = HERE / "runtime" / "edge_cookie_bridge.json"
_FORWARD_CONFIG_LOCK = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _email_key(value: str) -> str:
    return (value or "").strip().lower()


def base_icloud_email_address(value: str) -> str:
    email_addr = _email_key(value)
    if "@" not in email_addr:
        return email_addr
    local, domain = email_addr.rsplit("@", 1)
    if domain not in {"icloud.com", "icloud.com.cn", "me.com", "mac.com"} or "+" not in local:
        return email_addr
    base_local, _tag = local.split("+", 1)
    return f"{base_local}@{domain}" if base_local else email_addr


def _to_iso(value: Any) -> str:
    if not value:
        return ""
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1000000000000:
            ts = ts / 1000
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        except (OSError, OverflowError, ValueError):
            return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except Exception:
        return text[:32]


def _clean_body_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"[ \t\r\f\v]+", " ", text).replace("\n ", "\n").strip()


def _normalize_code(value: str) -> str:
    return re.sub(r"[\s\-_:：]+", "", value or "").strip().upper()


def _bad_code(value: str) -> bool:
    code = _normalize_code(value)
    if len(code) < 4 or len(code) > 12:
        return True
    if len(set(code)) == 1:
        return True
    if code.isdigit() and 1900 <= int(code) <= 2099:
        return True
    bad_words = {
        "HTTP", "HTTPS", "HTML", "APPLE", "ICLOUD", "TOKEN", "LOGIN",
        "EMAIL", "OPENAI", "CHATGPT", "OUTLOOK", "MICROSOFT", "HELP",
    }
    if code in bad_words:
        return True
    if code.isalpha():
        return True
    return False


_verification_context_pattern = re.compile(
    r"验证码|驗證碼|校验码|验证代码|驗證代碼|登录代码|登入代碼|安全代码|動態碼|动态码|一次性代码|临时验证码|"
    r"一時ログインコード|確認コード|認証コード|인증\s*코드|로그인\s*코드|"
    r"verification(?:\s+code)?|verify(?:ing|ication)?|security\s+code|login\s+code|"
    r"one[- ]time(?:\s+(?:password|code))?|passcode|temporary\s+code|"
    r"authentication\s+code|confirmation\s+code|\botp\b|"
    r"\b(?:your|this)\s+(?:[a-z0-9]+\s+){0,2}code\b",
    re.IGNORECASE,
)
_non_verification_code_pattern = re.compile(
    r"\b(?:discount|promo|coupon|referral|redeem|gift|status|error|source)\s+code\b",
    re.IGNORECASE,
)
_verification_candidate_pattern = re.compile(
    r"\b(?:[A-Z0-9]{3,6}[\s-]){1,2}[A-Z0-9]{3,6}\b|\b[A-Z0-9]{4,12}\b",
    re.IGNORECASE,
)


def has_verification_context(text: Any) -> bool:
    scan = _non_verification_code_pattern.sub(" ", _clean_body_text(text))
    return bool(_verification_context_pattern.search(scan))


def _code_candidates(fragment: str, reverse: bool = False) -> Iterable[str]:
    values = [match.group(0) for match in _verification_candidate_pattern.finditer(fragment)]
    return reversed(values) if reverse else values


def extract_verification_code(text: Any) -> str:
    """Extract a code only when it appears next to explicit verification language."""
    raw = _clean_body_text(text)
    if not raw:
        return ""
    raw = re.sub(
        r"(?im)^(DKIM-Signature|Received|Authentication-Results|ARC-|X-|Content-|MIME-|Return-Path|Delivered-To):.*(?:\n[ \t].*)*",
        " ",
        raw,
    )
    scan = re.sub(r"https?://\S+", " ", raw)
    scan = _non_verification_code_pattern.sub(" ", scan)
    for context in _verification_context_pattern.finditer(scan):
        after_lines = scan[context.end():context.end() + 96].splitlines()
        before_lines = scan[max(0, context.start() - 64):context.start()].splitlines()
        # Verification mails commonly put the instruction and code on
        # consecutive lines. Keep the window tight to avoid unrelated numbers.
        after = "\n".join(after_lines[:3])
        before = before_lines[-1] if before_lines else ""
        for candidate in list(_code_candidates(after)) + list(_code_candidates(before, reverse=True)):
            code = _normalize_code(candidate)
            if not _bad_code(code):
                return code
    return ""


class InventoryManager:
    def __init__(self, path: Path = INVENTORY_FILE) -> None:
        self.path = path
        self.lock = threading.RLock()
        self._snapshot = None
        self._signature = None
        self._queries = OrderedDict()
        self._alias_sync = None

    def _file_signature(self):
        try:
            stat = self.path.stat()
            return (stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
        except FileNotFoundError:
            return None

    def _empty(self) -> Dict[str, Any]:
        return {"version": 1, "updated_at": _now(), "items": {}}

    def _normalize_usage_groups(self, data: Dict[str, Any]) -> bool:
        changed = False
        for item in data.get("items", {}).values():
            if not isinstance(item, dict):
                continue
            message_text = f"{item.get('subject') or ''}\n{item.get('preview') or ''}"
            if item.get("code") and message_text.strip() and not has_verification_context(message_text):
                item["code"] = ""
                item["status_type"] = "warn"
                item["status_message"] = "收到邮件，未识别验证码"
                changed = True
            if item.get("group") == "trash":
                continue
            if item.get("lifecycle_status") == "disabled":
                continue
            if (item.get("code") or item.get("last_received_at")) and item.get("group", "unused") != "finished":
                item["group"] = "finished"
                changed = True
            if item.get("code") and item.get("status_message") != "收到验证码":
                item["status_type"] = "ok"
                item["status_message"] = "收到验证码"
                changed = True
        return changed

    def load(self) -> Dict[str, Any]:
        with self.lock:
            return copy.deepcopy(self._load_locked())

    def _load_locked(self) -> Dict[str, Any]:
        signature = self._file_signature()
        if self._snapshot is not None and signature == self._signature:
            return self._snapshot
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            if self._snapshot is not None:
                raise RuntimeError("库存文件意外消失，已停止写入，请恢复备份")
            data = self._empty()
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("库存文件读取失败，已保留原文件并停止写入，请检查文件或恢复备份") from exc
        if not isinstance(data, dict):
            raise RuntimeError("库存文件格式损坏，已停止写入，请恢复备份")
        items = data.get("items")
        if isinstance(items, list):
            items = {str(x.get("email", "")).lower(): x for x in items if isinstance(x, dict) and x.get("email")}
        if not isinstance(items, dict):
            raise RuntimeError("库存 items 格式损坏，已停止写入，请恢复备份")
        if any(not isinstance(item, dict) for item in items.values()):
            raise RuntimeError("库存记录格式损坏，已停止写入，请恢复备份")
        if not isinstance(data.get("purged_emails", {}), dict):
            raise RuntimeError("永久删除记录格式损坏，已停止写入，请恢复备份")
        data["items"] = items
        data.setdefault("version", 1)
        data.setdefault("updated_at", "")
        if self._normalize_usage_groups(data):
            self.save(data)
        else:
            self._snapshot = data
            self._signature = signature
            self._queries.clear()
        return data

    def save(self, data: Dict[str, Any]) -> None:
        with self.lock:
            self._normalize_usage_groups(data)
            data["updated_at"] = _now()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".inventory-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(name, self.path)
                self._snapshot = copy.deepcopy(data)
                self._signature = self._file_signature()
                self._queries.clear()
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def _default_item(self, email_addr: str) -> Dict[str, Any]:
        return {
            "email": email_addr,
            "account_id": "",
            "account_name": "",
            "account_email": "",
            "icloud_email": "",
            "label": "",
            "anonymousId": "",
            "active": True,
            "group": "unused",
            "remark": "",
            "code": "",
            "subject": "",
            "preview": "",
            "last_received_at": "",
            "last_checked_at": "",
            "last_method": "",
            "unread": False,
            "status_type": "idle",
            "status_message": "",
            "source": "local",
            "created_at": "",
            "created_ts": 0,
            "deleted_at": "",
            "lifecycle_status": "active",
            "lifecycle_reason": "",
            "deactivated_at": "",
            "deactivation_alias": "",
            "deactivation_subject": "",
            "deactivation_sender": "",
            "deactivation_message_id": "",
            "deactivation_message_date": "",
            "deactivation_source": "",
        }

    def sync_aliases(self, rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        with self.lock:
            rows = list(rows or [])
            self._load_locked()
            if self._alias_sync is not None:
                signature, previous, summary = self._alias_sync
                if signature == self._signature and rows == previous:
                    return {"ok": True, "changed": 0, "summary": dict(summary)}
            data = self.load()
            items = data["items"]
            changed = 0
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                email_addr = _email_key(row.get("email", ""))
                if not email_addr or email_addr in data.get("purged_emails", {}):
                    continue
                item = dict(items.get(email_addr) or self._default_item(email_addr))
                created = row.get("createdAt") or row.get("created_at") or item.get("created_ts") or item.get("created_at")
                created_iso = _to_iso(created)
                item.update({
                    "email": email_addr,
                    "account_id": row.get("account_id", item.get("account_id", "")) or "",
                    "account_name": row.get("account_name", item.get("account_name", "")) or "",
                    "account_email": row.get("account_email", item.get("account_email", "")) or "",
                    "icloud_email": row.get("icloud_email", item.get("icloud_email", "")) or "",
                    "label": row.get("label", item.get("label", "")) or "",
                    "anonymousId": row.get("anonymousId", row.get("anonymous_id", item.get("anonymousId", ""))) or "",
                    "active": row.get("active", item.get("active", True)),
                    "source": row.get("source", item.get("source", "cloud")) or "cloud",
                    "created_at": created_iso or item.get("created_at", ""),
                    "created_ts": row.get("createdAt", item.get("created_ts", 0)) or 0,
                })
                if items.get(email_addr) != item:
                    items[email_addr] = item
                    changed += 1
            if changed:
                self.save(data)
            summary = self.summary(data)
            self._alias_sync = (self._signature, copy.deepcopy(rows), dict(summary))
            return {"ok": True, "changed": changed, "summary": summary}

    def summary(self, data: Dict[str, Any] | None = None) -> Dict[str, Any]:
        data = data or self.load()
        items = list(data.get("items", {}).values())
        counts = {"all": 0, "unused": 0, "finished": 0, "trash": 0, "disabled": 0, "unread": 0, "with_code": 0}
        for item in items:
            group = item.get("group") or "unused"
            counts["all"] += 1
            if group in counts:
                counts[group] += 1
            if group != "trash" and item.get("lifecycle_status") == "disabled":
                counts["disabled"] += 1
            if item.get("unread"):
                counts["unread"] += 1
            if item.get("code"):
                counts["with_code"] += 1
        return counts

    def list_items(self, group: str = "", query: str = "", account_id: str = "") -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        with self.lock:
            data = self._load_locked()
            key = (group, query.strip().lower(), account_id)
            if key not in self._queries:
                self._queries[key] = self._filter_items(data, group, query, account_id)
                if len(self._queries) > 32:
                    self._queries.popitem(last=False)
            self._queries.move_to_end(key)
            rows, summary = self._queries[key]
            return [dict(row) for row in rows], dict(summary)

    def _filter_items(self, data, group, query, account_id):
        q = (query or "").strip().lower()
        base_query = base_icloud_email_address(q)
        query_values = {base_query or q}
        group = (group or "").strip()
        account_id = (account_id or "").strip()
        rows = []
        for item in data.get("items", {}).values():
            if group == "disabled":
                if item.get("group") == "trash" or item.get("lifecycle_status") != "disabled":
                    continue
            elif group and group != "all" and item.get("group", "unused") != group:
                continue
            if account_id and item.get("account_id") != account_id:
                continue
            if q:
                hay = " ".join(str(item.get(k, "")) for k in ("email", "label", "remark", "code", "subject", "account_email")).lower()
                if not any(value in hay for value in query_values):
                    continue
            rows.append(item)

        def score(item: Dict[str, Any]) -> Tuple[int, str, str]:
            if item.get("group") == "finished":
                primary = item.get("last_received_at") or item.get("created_at") or ""
            elif item.get("group") == "trash":
                primary = item.get("deleted_at") or item.get("created_at") or ""
            else:
                primary = item.get("created_at") or ""
            return (1 if item.get("unread") else 0, primary, item.get("email", ""))

        rows.sort(key=score, reverse=True)
        return rows, self.summary(data)

    def update_item(self, email_addr: str, **updates: Any) -> Dict[str, Any]:
        key = _email_key(email_addr)
        with self.lock:
            data = self.load()
            if key in data.get("purged_emails", {}):
                raise ValueError("该记录已永久删除，请刷新列表。")
            item = dict(data["items"].get(key) or self._default_item(key))
            item.update(updates)
            if item.get("group") != "trash" and (item.get("code") or item.get("last_received_at")):
                item["group"] = "finished"
            data["items"][key] = item
            self.save(data)
            return item

    def move(self, email_addr: str, group: str) -> Dict[str, Any]:
        group = group if group in {"unused", "finished", "trash"} else "unused"
        updates: Dict[str, Any] = {"group": group, "status_message": ""}
        if group == "trash":
            updates["deleted_at"] = _now()
        return self.update_item(email_addr, **updates)

    def mark_read(self, email_addr: str) -> Dict[str, Any]:
        return self.update_item(email_addr, unread=False)

    def purge(self, email_addr: str) -> bool:
        key = _email_key(email_addr)
        with self.lock:
            data = self.load()
            item = data["items"].get(key)
            if item is None:
                return key in data.get("purged_emails", {})
            if item.get("group") != "trash":
                raise ValueError("只能永久删除垃圾箱中的记录，请先移入垃圾箱。")
            # Keep only the address and deletion time so cached/cloud/message
            # imports cannot recreate a record the user permanently removed.
            data.setdefault("purged_emails", {})[key] = _now()
            del data["items"][key]
            self.save(data)
            return True

    def purge_many(self, emails):
        """Remove trash in one atomic write, retaining each address's tombstone."""
        with self.lock:
            data = self.load()
            results, changed = [], False
            for key in dict.fromkeys(_email_key(email) for email in emails):
                item = data["items"].get(key)
                error = ""
                if item is None and key not in data.get("purged_emails", {}):
                    error = "记录不存在，请刷新列表。"
                elif item is not None and item.get("group") != "trash":
                    error = "只能永久删除垃圾箱中的记录，请先移入垃圾箱。"
                elif item is not None:
                    data.setdefault("purged_emails", {})[key] = _now()
                    del data["items"][key]
                    changed = True
                results.append({"label": key, "state": "failed" if error else "complete", "error": error})
            if changed:
                self.save(data)
            return results

    def apply_messages(self, messages: Iterable[Dict[str, Any]], account_id: str = "", method: str = "iCloud IMAP") -> Dict[str, Any]:
        with self.lock:
            data = self.load()
            items = data["items"]
            aliases = list(items.keys())
            updated = []
            for msg in messages or []:
                if not isinstance(msg, dict):
                    continue
                subject = str(msg.get("subject") or "")
                body = str(msg.get("body") or msg.get("body_preview") or msg.get("preview") or "")
                to_text = " ".join(str(msg.get(k) or "") for k in ("to", "cc", "bcc", "delivered_to", "recipient"))
                hay = f"{to_text}\n{subject}\n{body}".lower()
                matched = [alias for alias in aliases if alias and alias in hay]
                deactivation = detect_deactivation_notice(msg, aliases)
                if deactivation and deactivation["email"] not in matched:
                    matched.append(deactivation["email"])
                if not matched:
                    continue
                code = extract_verification_code(f"{subject}\n{body}")
                verification_context = has_verification_context(f"{subject}\n{body}")
                preview = _clean_body_text(body).replace("\n", " ")
                if len(preview) > 240:
                    preview = preview[:240] + "..."
                received_at = _to_iso(msg.get("internal_date") or msg.get("received_at") or msg.get("date") or msg.get("ts") or time.time())
                for alias in matched:
                    item = dict(items.get(alias) or self._default_item(alias))
                    if account_id and not item.get("account_id"):
                        item["account_id"] = account_id
                    current_received = str(item.get("last_received_at") or "")
                    is_newer = not current_received or str(received_at) >= current_received
                    if is_newer:
                        merged_code = code or (item.get("code", "") if verification_context else "")
                        item.update({
                            "code": merged_code,
                            "subject": subject,
                            "preview": preview,
                            "last_received_at": received_at,
                            "last_checked_at": _now(),
                            "last_method": method,
                            "unread": True if str(received_at) != current_received else item.get("unread", False),
                            "status_type": "ok" if merged_code else "warn",
                            "status_message": "收到验证码" if merged_code else "收到邮件，未识别验证码",
                        })
                    else:
                        item["last_checked_at"] = _now()
                        item["last_method"] = method
                        if code:
                            if not item.get("code"):
                                item["code"] = code
                            item["status_type"] = "ok"
                            item["status_message"] = "收到验证码"
                    if item.get("group") != "trash":
                        item["group"] = "finished"
                    if deactivation and alias == deactivation["email"]:
                        item.update({
                            "lifecycle_status": "disabled",
                            "lifecycle_reason": deactivation["reason"],
                            "deactivated_at": deactivation["detected_at"],
                            "deactivation_alias": deactivation["detected_email"],
                            "deactivation_subject": deactivation["subject"],
                            "deactivation_sender": deactivation["sender"],
                            "deactivation_message_id": deactivation["message_id"],
                            "deactivation_message_date": deactivation["message_date"],
                            "deactivation_source": method,
                            "status_type": "error",
                            "status_message": "ChatGPT 访问权限已停用",
                        })
                    items[alias] = item
                    updated.append(dict(item))
            if updated:
                self.save(data)
            return {
                "ok": True,
                "updated": updated,
                "count": len(updated),
                "deactivated": sum(1 for item in updated if item.get("lifecycle_status") == "disabled"),
                "summary": self.summary(data),
            }

    def export_rows(self, group: str = "") -> str:
        rows, _ = self.list_items(group=group or "all")
        header = ["email", "group", "label", "remark", "code", "account", "last_received_at", "subject"]
        lines = [",".join(header)]
        for row in rows:
            vals = [str(row.get(k, "")).replace('"', '""') for k in header]
            lines.append(",".join(f'"{v}"' for v in vals))
        return "\n".join(lines) + "\n"


def _forward_profile_defaults() -> Dict[str, Any]:
    return {
        "id": "",
        "account_id": "",
        "enabled": False,
        "provider": "qq",
        "host": "imap.qq.com",
        "port": 993,
        "secure": True,
        "auth_type": "password",
        "username": "",
        "password": "",
        "mailbox": "INBOX",
        "limit": 100,
        "client_id": "",
        "tenant": "consumers",
        "refresh_token": "",
    }


def _normalize_forward_profile(data: Dict[str, Any], current: Dict[str, Any] | None = None) -> Dict[str, Any]:
    clean = _forward_profile_defaults()
    if current:
        clean.update(current)
    for key in (
        "id", "account_id", "enabled", "provider", "host", "port", "secure",
        "auth_type", "username", "mailbox", "limit", "client_id", "tenant",
    ):
        if key in data:
            clean[key] = data[key]
    for secret in ("password", "refresh_token"):
        if data.get(secret):
            clean[secret] = str(data[secret])
    clean["id"] = str(clean.get("id") or f"forward_{uuid.uuid4().hex[:12]}")
    clean["account_id"] = str(clean.get("account_id") or "").strip()
    clean["enabled"] = bool(clean.get("enabled"))
    clean["username"] = str(clean.get("username") or "").strip().lower()
    clean["mailbox"] = str(clean.get("mailbox") or "INBOX").strip() or "INBOX"
    clean["limit"] = max(1, min(int(clean.get("limit") or 100), 300))
    provider = str(clean.get("provider") or "qq").strip().lower()
    if provider in {"microsoft", "outlook", "hotmail", "live"}:
        clean.update({
            "provider": "microsoft",
            "host": "outlook.office365.com",
            "port": 993,
            "secure": True,
            "auth_type": "oauth2",
            "tenant": str(clean.get("tenant") or "consumers").strip() or "consumers",
            "client_id": str(clean.get("client_id") or "").strip(),
        })
        clean["password"] = ""
    else:
        clean.update({
            "provider": "qq",
            "host": "imap.qq.com",
            "port": 993,
            "secure": True,
            "auth_type": "password",
            "client_id": "",
            "tenant": "consumers",
            "refresh_token": "",
        })
    return clean


def _read_forward_config_data() -> Dict[str, Any]:
    try:
        data = json.loads(FORWARD_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 2, "profiles": []}
    if not isinstance(data, dict):
        return {"version": 2, "profiles": []}
    if isinstance(data.get("profiles"), list):
        profiles = [_normalize_forward_profile(item) for item in data["profiles"] if isinstance(item, dict)]
        return {"version": 2, "profiles": profiles}
    if any(data.get(key) for key in ("username", "password", "enabled", "host")):
        legacy = dict(data)
        legacy["id"] = str(legacy.get("id") or "forward_legacy")
        legacy["account_id"] = str(legacy.get("account_id") or "")
        return {"version": 2, "profiles": [_normalize_forward_profile(legacy)]}
    return {"version": 2, "profiles": []}


def _write_forward_config_data(root: Dict[str, Any]) -> None:
    FORWARD_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 2, "profiles": root.get("profiles") or []}
    temp = FORWARD_CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(FORWARD_CONFIG_FILE)
    try:
        FORWARD_CONFIG_FILE.chmod(0o600)
    except OSError:
        pass


def _redact_forward_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    clean = dict(profile)
    clean["has_password"] = bool(clean.get("password"))
    clean["has_refresh_token"] = bool(clean.get("refresh_token"))
    clean["password"] = ""
    clean["refresh_token"] = ""
    return clean


def load_forward_configs(redact: bool = True) -> List[Dict[str, Any]]:
    with _FORWARD_CONFIG_LOCK:
        profiles = _read_forward_config_data().get("profiles") or []
        return [(_redact_forward_profile(item) if redact else dict(item)) for item in profiles]


def load_forward_config(redact: bool = True, profile_id: str = "", account_id: str = "") -> Dict[str, Any]:
    profiles = load_forward_configs(redact=redact)
    selected = next((p for p in profiles if profile_id and p.get("id") == profile_id), None)
    if selected is None:
        selected = next((p for p in profiles if account_id and p.get("account_id") == account_id), None)
    if selected is None:
        selected = next((p for p in profiles if p.get("enabled")), None) or (profiles[0] if profiles else None)
    result = dict(selected or _forward_profile_defaults())
    result["profiles"] = profiles
    result["any_enabled"] = any(p.get("enabled") for p in profiles)
    return result


def save_forward_config(data: Dict[str, Any]) -> Dict[str, Any]:
    with _FORWARD_CONFIG_LOCK:
        root = _read_forward_config_data()
        profiles = root.get("profiles") or []
        profile_id = str(data.get("id") or "").strip()
        account_id = str(data.get("account_id") or "").strip()
        index = next((i for i, p in enumerate(profiles) if profile_id and p.get("id") == profile_id), -1)
        if index < 0 and account_id:
            index = next((i for i, p in enumerate(profiles) if p.get("account_id") == account_id), -1)
        current = profiles[index] if index >= 0 else None
        clean = _normalize_forward_profile(data, current=current)
        if index >= 0:
            profiles[index] = clean
        else:
            profiles.append(clean)
        root["profiles"] = profiles
        _write_forward_config_data(root)
    return _redact_forward_profile(clean)


def delete_forward_config(profile_id: str) -> bool:
    with _FORWARD_CONFIG_LOCK:
        root = _read_forward_config_data()
        profiles = root.get("profiles") or []
        kept = [p for p in profiles if str(p.get("id") or "") != str(profile_id or "")]
        if len(kept) == len(profiles):
            return False
        root["profiles"] = kept
        _write_forward_config_data(root)
        return True


def _update_forward_profile_secrets(profile_id: str, **secrets: str) -> Dict[str, Any]:
    with _FORWARD_CONFIG_LOCK:
        root = _read_forward_config_data()
        for index, profile in enumerate(root.get("profiles") or []):
            if profile.get("id") != profile_id:
                continue
            updated = dict(profile)
            for key, value in secrets.items():
                if value:
                    updated[key] = value
            root["profiles"][index] = _normalize_forward_profile(updated)
            _write_forward_config_data(root)
            return dict(root["profiles"][index])
    raise ValueError("转发邮箱配置不存在")


def _microsoft_token_endpoint(tenant: str) -> str:
    return f"https://login.microsoftonline.com/{tenant or 'consumers'}/oauth2/v2.0/token"


def start_microsoft_device_auth(profile_id: str) -> Dict[str, Any]:
    cfg = load_forward_config(redact=False, profile_id=profile_id)
    if cfg.get("provider") != "microsoft":
        return {"ok": False, "error": "这条配置不是 Microsoft 邮箱"}
    if not cfg.get("client_id") or not cfg.get("username"):
        return {"ok": False, "error": "请先填写 Microsoft 邮箱和应用客户端 ID"}
    tenant = str(cfg.get("tenant") or "consumers")
    response = requests.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/devicecode",
        data={
            "client_id": cfg["client_id"],
            "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access openid email",
        },
        timeout=20,
    )
    payload = response.json()
    if response.status_code >= 400:
        return {"ok": False, "error": payload.get("error_description") or payload.get("error") or "Microsoft 授权启动失败"}
    return {
        "ok": True,
        "profile_id": profile_id,
        "device_code": payload.get("device_code"),
        "user_code": payload.get("user_code"),
        "verification_uri": payload.get("verification_uri") or payload.get("verification_url"),
        "verification_uri_complete": payload.get("verification_uri_complete"),
        "expires_in": int(payload.get("expires_in") or 900),
        "interval": int(payload.get("interval") or 5),
        "message": payload.get("message") or "",
    }


def poll_microsoft_device_auth(profile_id: str, device_code: str) -> Dict[str, Any]:
    cfg = load_forward_config(redact=False, profile_id=profile_id)
    if cfg.get("provider") != "microsoft" or not cfg.get("client_id"):
        return {"ok": False, "error": "Microsoft 配置不完整"}
    response = requests.post(
        _microsoft_token_endpoint(str(cfg.get("tenant") or "consumers")),
        data={
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": cfg["client_id"],
            "device_code": str(device_code or ""),
        },
        timeout=20,
    )
    payload = response.json()
    if response.status_code >= 400:
        if payload.get("error") in {"authorization_pending", "slow_down"}:
            return {"ok": True, "pending": True, "error": payload.get("error")}
        return {"ok": False, "error": payload.get("error_description") or payload.get("error") or "Microsoft 授权失败"}
    refresh_token = str(payload.get("refresh_token") or "")
    if not refresh_token:
        return {"ok": False, "error": "Microsoft 未返回长期授权令牌"}
    _update_forward_profile_secrets(profile_id, refresh_token=refresh_token)
    return {"ok": True, "authorized": True}


def _microsoft_access_token(cfg: Dict[str, Any]) -> str:
    if not cfg.get("client_id") or not cfg.get("refresh_token"):
        raise RuntimeError("Microsoft 邮箱尚未完成 OAuth2 授权")
    response = requests.post(
        _microsoft_token_endpoint(str(cfg.get("tenant") or "consumers")),
        data={
            "grant_type": "refresh_token",
            "client_id": cfg["client_id"],
            "refresh_token": cfg["refresh_token"],
            "scope": "https://outlook.office.com/IMAP.AccessAsUser.All offline_access",
        },
        timeout=20,
    )
    payload = response.json()
    if response.status_code >= 400 or not payload.get("access_token"):
        raise RuntimeError(payload.get("error_description") or payload.get("error") or "Microsoft OAuth2 刷新失败")
    if payload.get("refresh_token") and payload["refresh_token"] != cfg.get("refresh_token"):
        _update_forward_profile_secrets(str(cfg.get("id") or ""), refresh_token=str(payload["refresh_token"]))
    return str(payload["access_token"])


def _open_forward_connection(cfg: Dict[str, Any]):
    host, port = str(cfg.get("host") or ""), int(cfg.get("port") or 993)
    if not host or not cfg.get("username"):
        raise RuntimeError("转发邮箱配置不完整")
    conn = open_imap(host, port, secure=cfg.get("secure", True), ssl_context=ssl.create_default_context())
    try:
        if cfg.get("provider") == "microsoft":
            token = _microsoft_access_token(cfg)
            auth = f"user={cfg['username']}\x01auth=Bearer {token}\x01\x01".encode("utf-8")
            conn.authenticate("XOAUTH2", lambda _challenge: auth)
        else:
            if not cfg.get("password"):
                raise RuntimeError("请填写 QQ 邮箱和 IMAP 授权码")
            conn.login(str(cfg["username"]), str(cfg["password"]))
        return conn
    except Exception:
        close_imap(conn)
        raise


def test_forward_mail_connection(profile_id: str = "", account_id: str = "") -> Dict[str, Any]:
    cfg = load_forward_config(redact=False, profile_id=profile_id, account_id=account_id)
    if not cfg.get("enabled"):
        return {"ok": False, "error": "请先启用这条转发 IMAP 配置"}
    conn = _open_forward_connection(cfg)
    try:
        mailbox = str(cfg.get("mailbox") or "INBOX").split(",", 1)[0].strip() or "INBOX"
        typ, data = conn.select(f'"{mailbox}"', readonly=True)
        if typ != "OK":
            return {"ok": False, "error": f"无法打开文件夹 {mailbox}"}
        try:
            message_count = int((data or [b"0"])[0] or 0)
        except (TypeError, ValueError):
            message_count = 0
        return {
            "ok": True,
            "profile_id": cfg.get("id"),
            "account_id": cfg.get("account_id"),
            "provider": cfg.get("provider"),
            "username": cfg.get("username"),
            "mailbox": mailbox,
            "message_count": message_count,
        }
    finally:
        close_imap(conn)


def _decode_mime(value: str) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except Exception:
        return value or ""


def _extract_message_body(msg: email.message.Message) -> str:
    parts: List[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp or ctype not in ("text/plain", "text/html"):
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            charset = part.get_content_charset() or "utf-8"
            try:
                parts.append(payload.decode(charset, errors="replace"))
            except LookupError:
                parts.append(payload.decode("utf-8", errors="replace"))
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            try:
                parts.append(payload.decode(charset, errors="replace"))
            except LookupError:
                parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _message_from_raw(raw: bytes) -> Dict[str, Any]:
    msg = email.message_from_bytes(raw)
    body = _extract_message_body(msg)
    return {
        "subject": _decode_mime(msg.get("Subject", "")),
        "from": _decode_mime(msg.get("From", "")),
        "to": _decode_mime(msg.get("To", "")),
        "cc": _decode_mime(msg.get("Cc", "")),
        "delivered_to": _decode_mime(" ".join(x for x in (msg.get("Delivered-To", ""), msg.get("X-Original-To", "")) if x)),
        "date": msg.get("Date", ""),
        "message_id": _decode_mime(msg.get("Message-ID", "")),
        "body": body,
        "body_preview": _clean_body_text(body)[:320],
    }


def check_forward_mail(target_emails: Iterable[str] | Dict[str, Iterable[str]], limit: int = 100) -> Dict[str, Any]:
    profiles = [p for p in load_forward_configs(redact=False) if p.get("enabled")]
    if not profiles:
        return {"ok": False, "error": "未启用转发邮箱"}
    target_map = target_emails if isinstance(target_emails, dict) else None
    all_targets = [] if target_map is not None else list(target_emails)
    messages: List[Dict[str, Any]] = []
    details: List[Dict[str, Any]] = []
    errors: List[str] = []
    successful_profiles = 0
    for cfg in profiles:
        source_targets = target_map.get(str(cfg.get("account_id") or ""), []) if target_map is not None else all_targets
        target_set = {_email_key(x) for x in source_targets if _email_key(x)}
        if not target_set:
            continue
        conn = None
        matched = 0
        try:
            conn = _open_forward_connection(cfg)
            mailboxes = [x.strip() for x in str(cfg.get("mailbox") or "INBOX").split(",") if x.strip()]
            per_box_limit = max(1, min(int(limit or cfg.get("limit") or 100), 300))
            for box in mailboxes:
                typ, _ = conn.select(f'"{box}"', readonly=True)
                if typ != "OK":
                    continue
                typ, data = conn.search(None, "ALL")
                if typ != "OK" or not data:
                    continue
                ids = data[0].split()[-per_box_limit:]
                for msg_id in reversed(ids):
                    typ, fetched = conn.fetch(msg_id, "(RFC822)")
                    if typ != "OK" or not fetched:
                        continue
                    raw = next((part[1] for part in fetched if isinstance(part, tuple)), b"")
                    if not raw:
                        continue
                    parsed = _message_from_raw(raw)
                    hay = f"{parsed.get('to','')}\n{parsed.get('cc','')}\n{parsed.get('body','')}".lower()
                    if any(alias in hay for alias in target_set):
                        raw_id = msg_id.decode(errors="ignore")
                        parsed["id"] = f"{cfg.get('id')}:{box}:{raw_id}"
                        parsed["mailbox"] = box
                        parsed["account_id"] = str(cfg.get("account_id") or "")
                        parsed["forward_profile_id"] = str(cfg.get("id") or "")
                        parsed["forward_provider"] = str(cfg.get("provider") or "")
                        messages.append(parsed)
                        matched += 1
            successful_profiles += 1
            details.append({
                "profile_id": cfg.get("id"),
                "account_id": cfg.get("account_id"),
                "provider": cfg.get("provider"),
                "username": cfg.get("username"),
                "matched": matched,
            })
        except Exception as exc:
            errors.append(f"{cfg.get('username') or cfg.get('id')}: {str(exc)[:180]}")
        finally:
            close_imap(conn)
    if not successful_profiles:
        return {"ok": False, "error": "; ".join(errors) or "没有可检查的目标邮箱", "errors": errors}
    return {
        "ok": True,
        "messages": messages,
        "count": len(messages),
        "profiles_checked": successful_profiles,
        "details": details,
        "errors": errors,
    }


def _auto_stock_account_ids(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(account_id or "").strip() for account_id in value if str(account_id or "").strip()))


def load_auto_stock_config() -> Dict[str, Any]:
    defaults = {
        "enabled": False,
        "all_accounts": True,
        "account_ids": [],
        "prefix": "stock",
        "target": 20,
        "batch": 5,
        "last_run": "",
        "last_error": "",
    }
    data: Dict[str, Any] = {}
    try:
        data = json.loads(AUTO_STOCK_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update(data)
        else:
            data = {}
    except (OSError, json.JSONDecodeError):
        pass
    if "account_ids" in data or "all_accounts" in data:
        defaults["account_ids"] = _auto_stock_account_ids(defaults.get("account_ids"))
        defaults["all_accounts"] = bool(defaults.get("all_accounts", not defaults["account_ids"]))
    else:
        legacy_account_id = str(data.get("account_id") or "").strip()
        defaults["account_ids"] = [legacy_account_id] if legacy_account_id else []
        defaults["all_accounts"] = not bool(legacy_account_id)
    defaults.pop("account_id", None)
    return defaults


def save_auto_stock_config(data: Dict[str, Any]) -> Dict[str, Any]:
    cfg = load_auto_stock_config()
    for key in ("enabled", "all_accounts", "account_ids", "prefix", "target", "batch", "last_run", "last_error"):
        if key in data:
            cfg[key] = data[key]
    cfg["all_accounts"] = bool(cfg.get("all_accounts"))
    cfg["account_ids"] = [] if cfg["all_accounts"] else _auto_stock_account_ids(cfg.get("account_ids"))
    cfg["target"] = max(0, int(cfg.get("target") or 0))
    cfg["batch"] = max(1, min(int(cfg.get("batch") or 5), 5))
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    AUTO_STOCK_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def save_cookie_bridge_payload(data: Dict[str, Any]) -> Dict[str, Any]:
    cookies = data.get("cookies") or data.get("cookie") or data.get("cookieHeader") or data.get("header") or []
    pairs: List[Tuple[str, str]] = []
    if isinstance(cookies, dict):
        pairs = [(str(k), str(v)) for k, v in cookies.items()]
    elif isinstance(cookies, list):
        for item in cookies:
            if isinstance(item, dict) and item.get("name"):
                pairs.append((str(item.get("name")), str(item.get("value", ""))))
    elif isinstance(cookies, str):
        for part in cookies.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                pairs.append((k.strip(), v.strip()))
    apple_pairs = [(k, v) for k, v in pairs if k.upper().startswith(("X-APPLE", "DES", "DS", "WEB")) or "APPLE" in k.upper()]
    header = "; ".join(f"{k}={v}" for k, v in (apple_pairs or pairs))
    payload = {
        "ok": bool(header),
        "updated_at": _now(),
        "host": data.get("host") or data.get("domain") or "icloud.com.cn",
        "count": len(pairs),
        "apple_count": len(apple_pairs),
        "cookie_header": header,
    }
    COOKIE_BRIDGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    COOKIE_BRIDGE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload
