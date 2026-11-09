#!/usr/bin/env python3
"""
iCloud Mail — IMAP 收件箱检查模块
===================================
通过 Apple 应用专用密码连接 iCloud Mail IMAP，
查询隐私邮箱别名收到的邮件。

用法:
    from icloud_mail import ICloudMail

    mail = ICloudMail("user@icloud.com", "app-specific-password")
    emails = mail.check_inbox(limit=20)
    # 查找某个隐私别名收到的邮件
    alias_mail = mail.find_by_recipient("alias@icloud.com")

前提:
  - 需要在 appleid.apple.com 生成「App 专用密码」
  - iCloud 邮箱已开启 IMAP 访问
"""

import imaplib
from imap_runtime import open_imap, close_imap
import email
import re
import time
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import Optional, Dict, Iterable, List

IMAP_SERVER = "imap.mail.me.com"
IMAP_PORT = 993
IMAP_TIMEOUT = 20
MAX_BODY_CHARS = 50000

IMAP_REGION_CONFIG = {
    "icloud.com": {"server": "imap.mail.me.com", "port": 993, "label": "全球区 iCloud"},
    "icloud.com.cn": {"server": "imap.mail.me.com", "port": 993, "label": "中国区 iCloud"},
}


class ICloudMail:
    """iCloud Mail IMAP 客户端"""

    def __init__(self, apple_id: str, app_password: str, verbose: bool = False,
                 region_host: str = "icloud.com", imap_server: str = ""):
        self.apple_id = apple_id
        self.app_password = app_password
        self.verbose = verbose
        self.region_host = "icloud.com.cn" if str(region_host or "").endswith("icloud.com.cn") else "icloud.com"
        cfg = IMAP_REGION_CONFIG.get(self.region_host, IMAP_REGION_CONFIG["icloud.com"])
        self.imap_server = imap_server or cfg["server"]
        self.imap_port = int(cfg.get("port") or IMAP_PORT)
        self._conn: Optional[imaplib.IMAP4_SSL] = None

    def connect(self) -> bool:
        try:
            self._conn = open_imap(self.imap_server, self.imap_port, timeout=IMAP_TIMEOUT)
            self._conn.login(self.apple_id, self.app_password)
            if self.verbose:
                print(f"[IMAP] Connected as {self.apple_id} via {self.region_host} ({self.imap_server})")
            return True
        except imaplib.IMAP4.error as e:
            self.disconnect()
            msg = str(e)
            if "authentication" in msg.lower() or "login" in msg.lower():
                raise RuntimeError(
                    f"IMAP 登录失败 — 请检查:\n"
                    f"  1. 应用专用密码是否正确\n"
                    f"  2. Apple ID: {self.apple_id}\n"
                    f"  3. 是否已在 appleid.apple.com 生成密码"
                )
            raise RuntimeError(f"IMAP 连接失败: {msg}")
        except Exception as e:
            self.disconnect()
            raise RuntimeError(f"IMAP 连接失败: {e}")

    def disconnect(self):
        if self._conn:
            close_imap(self._conn)
            self._conn = None

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._conn.state == "SELECTED"

    def _ensure_connected(self):
        if not self._conn:
            self.connect()
        if self._conn.state != "SELECTED":
            self._conn.select("INBOX", readonly=True)

    def _select_mailbox(self, mailbox: str) -> bool:
        if not self._conn:
            self.connect()
        box = (mailbox or "INBOX").strip() or "INBOX"
        name = "INBOX" if box.upper() == "INBOX" else f'"{box}"'
        status, _ = self._conn.select(name, readonly=True)
        return status == "OK"

    def list_mailboxes(self) -> List[str]:
        if not self._conn:
            self.connect()
        status, data = self._conn.list()
        if status != "OK" or not data:
            return ["INBOX"]
        boxes: List[str] = []
        for raw in data:
            text = raw.decode(errors="ignore") if isinstance(raw, bytes) else str(raw)
            quoted = re.findall(r'"([^"]+)"', text)
            if not quoted:
                continue
            name = quoted[-1]
            low = name.lower()
            if any(x in low for x in ("sent", "draft", "trash", "deleted", "junk", "spam")):
                continue
            boxes.append(name)
        return ["INBOX"] + [x for x in boxes if x.upper() != "INBOX"]

    def check_inbox(self, limit: int = 50, days: int = 7) -> List[Dict]:
        self._ensure_connected()
        return self._search_and_fetch(None, limit, days)

    def check_unread(self, limit: int = 50, days: int = 7) -> List[Dict]:
        self._ensure_connected()
        return self._search_and_fetch("UNSEEN", limit, days)

    def find_by_recipient(self, recipient: str, limit: int = 20, days: int = 30) -> List[Dict]:
        self._ensure_connected()
        target = str(recipient or "").strip().lower()
        if not target:
            return []

        # Ask IMAP for this recipient first. Scanning only the newest messages
        # misses quieter aliases on accounts that receive a lot of mail.
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = self._conn.uid(
            "SEARCH", None, f'(SINCE "{since}" HEADER TO "{target}")'
        )
        if status == "OK" and data and data[0]:
            uids = self._sort_uids(data[0].split())
            ordered = list(reversed(uids[-max(1, limit):]))
            direct_matches = [
                message for message in self._fetch_headers_uid_batch(ordered)
                if self._message_matches_recipient(message, target)
            ]
            if direct_matches:
                return direct_matches[:limit]

        scan_limit = max(limit * 10, 120)
        all_msgs = self._search_and_fetch(None, scan_limit, days)
        matches = [m for m in all_msgs if self._message_matches_recipient(m, target)]
        if matches:
            return matches[:limit]

        seen = {str(m.get("id") or "") for m in matches}
        for msg in all_msgs[:min(len(all_msgs), 18)]:
            msg_id = str(msg.get("id") or "")
            if not msg_id or msg_id in seen:
                continue
            full = self.fetch_full(msg_id.encode())
            if full:
                merged = dict(msg)
                merged.update(full)
                if self._message_matches_recipient(merged, target):
                    matches.append(merged)
                    seen.add(msg_id)
                    if len(matches) >= limit:
                        break
        return matches[:limit]

    def scan_alias_usage(
        self,
        aliases: Iterable[str],
        limit: int = 1500,
        days: int = 365,
        mailboxes: Optional[List[str]] = None,
        limit_per_alias: int = 10,
        fetch_bodies: int = 80,
    ) -> Dict:
        alias_set = {str(x or "").strip().lower() for x in aliases if str(x or "").strip()}
        if not alias_set:
            return {"by_alias": {}, "scanned": 0, "matched": 0, "body_fetched": 0, "mailboxes": []}
        if not self._conn:
            self.connect()
        boxes = mailboxes or ["INBOX"]
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        by_alias: Dict[str, List[Dict]] = {}
        scanned = 0
        matched = 0
        body_fetched = 0
        used_boxes: List[str] = []
        for box in boxes:
            if not self._select_mailbox(box):
                continue
            used_boxes.append(box)
            status, data = self._conn.uid("SEARCH", None, f'(SINCE "{since}")')
            if status != "OK" or not data or not data[0]:
                continue
            uids = self._sort_uids(data[0].split())
            if limit > 0 and len(uids) > limit:
                uids = uids[-limit:]
            scanned += len(uids)
            ordered = list(reversed(uids))
            headers = self._fetch_headers_uid_batch(ordered)
            for msg in headers:
                hay = " ".join(str(msg.get(k) or "") for k in (
                    "to", "cc", "bcc", "delivered_to", "recipient", "subject"
                )).lower()
                hit_aliases = [alias for alias in alias_set if alias in hay]
                if not hit_aliases:
                    continue
                matched += 1
                msg = dict(msg)
                msg["mailbox"] = box
                if fetch_bodies > 0 and body_fetched < fetch_bodies:
                    full = self.fetch_full(str(msg.get("id") or "").encode())
                    if full:
                        full.update({k: v for k, v in msg.items() if v})
                        msg = full
                        body_fetched += 1
                for alias in hit_aliases:
                    bucket = by_alias.setdefault(alias, [])
                    if len(bucket) < limit_per_alias:
                        bucket.append(dict(msg))
        return {
            "by_alias": by_alias,
            "scanned": scanned,
            "matched": matched,
            "body_fetched": body_fetched,
            "mailboxes": used_boxes,
        }

    def stream_inbox(self, limit: int = 50, days: int = 7):
        self._ensure_connected()
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        full = f'(SINCE "{since}")'
        status, data = self._conn.uid("SEARCH", None, full)
        if status != "OK" or not data[0]:
            return
        uids = self._sort_uids(data[0].split())
        recent = uids[-limit:] if len(uids) > limit else uids
        for uid in reversed(recent):
            try:
                msg = self._fetch_headers_uid(uid)
                if msg:
                    yield msg
            except Exception:
                continue

    def _search_and_fetch(self, criteria: Optional[str], limit: int, days: int) -> List[Dict]:
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        full = f'({criteria} SINCE "{since}")' if criteria else f'(SINCE "{since}")'
        status, data = self._conn.uid("SEARCH", None, full)
        if status != "OK" or not data[0]:
            return []
        uids = self._sort_uids(data[0].split())
        recent = uids[-limit:] if len(uids) > limit else uids
        ordered = list(reversed(recent))
        try:
            batch = self._fetch_headers_uid_batch(ordered)
            if batch:
                return batch
        except Exception:
            pass
        emails: List[Dict] = []
        for uid in ordered:
            try:
                msg = self._fetch_headers_uid(uid)
                if msg:
                    emails.append(msg)
            except Exception:
                continue
        return emails

    def _fetch_headers(self, msg_id: bytes) -> Optional[Dict]:
        status, data = self._conn.fetch(msg_id, "(BODY.PEEK[HEADER])")
        if status != "OK":
            return None
        return self._parse_header_response(data, msg_id)

    def _fetch_headers_uid(self, uid: bytes) -> Optional[Dict]:
        status, data = self._conn.uid("FETCH", uid, "(UID INTERNALDATE BODY.PEEK[HEADER])")
        if status != "OK":
            return None
        msg = self._parse_header_response(data, uid)
        if msg:
            internal_date = self._internaldate_from_fetch_meta(self._extract_fetch_meta(data))
            if internal_date:
                msg["internal_date"] = internal_date
        return msg

    def _fetch_headers_uid_batch(self, uids: List[bytes], chunk_size: int = 20) -> List[Dict]:
        if not uids:
            return []
        by_uid: Dict[str, Dict] = {}
        fields = "(UID INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM TO CC BCC DELIVERED-TO X-ORIGINAL-TO SUBJECT DATE MESSAGE-ID)])"
        for idx in range(0, len(uids), chunk_size):
            chunk = uids[idx:idx + chunk_size]
            uid_set = b",".join(chunk).decode("ascii", errors="ignore")
            if not uid_set:
                continue
            status, data = self._conn.uid("FETCH", uid_set, fields)
            if status != "OK":
                continue
            for item in data:
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                meta, raw = item[0], item[1]
                if not isinstance(raw, bytes):
                    continue
                uid = self._uid_from_fetch_meta(meta)
                if not uid:
                    continue
                msg = self._parse_header_bytes(raw, uid)
                if msg:
                    internal_date = self._internaldate_from_fetch_meta(meta)
                    if internal_date:
                        msg["internal_date"] = internal_date
                    by_uid[uid] = msg
        return [by_uid[uid.decode("ascii", errors="ignore")] for uid in uids if uid.decode("ascii", errors="ignore") in by_uid]

    @staticmethod
    def _sort_uids(uids: List[bytes]) -> List[bytes]:
        def key(uid: bytes) -> int:
            try:
                return int(uid)
            except Exception:
                return 0
        return sorted(uids or [], key=key)

    @staticmethod
    def _uid_from_fetch_meta(meta) -> str:
        if not isinstance(meta, bytes):
            return ""
        match = re.search(rb"\bUID\s+(\d+)\b", meta)
        return match.group(1).decode("ascii") if match else ""

    @staticmethod
    def _extract_fetch_meta(data: list):
        for item in data or []:
            if isinstance(item, tuple) and item and isinstance(item[0], bytes):
                return item[0]
        return b""

    @staticmethod
    def _internaldate_from_fetch_meta(meta) -> str:
        if not isinstance(meta, bytes):
            return ""
        match = re.search(rb'INTERNALDATE\s+"([^"]+)"', meta)
        if not match:
            return ""
        raw = match.group(1).decode("ascii", errors="ignore")
        try:
            return parsedate_to_datetime(raw).isoformat()
        except Exception:
            return raw

    def _parse_header_response(self, data, msg_id: bytes) -> Optional[Dict]:
        raw = self._extract_body(data)
        if not raw:
            return None
        msg_key = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
        return self._parse_header_bytes(raw, msg_key)

    def _parse_header_bytes(self, raw: bytes, msg_id: str) -> Optional[Dict]:
        try:
            msg = email.message_from_bytes(raw + b"\r\n\r\n")
        except Exception:
            return None
        return {
            "id": msg_id,
            "from": self._decode_header(msg.get("From", "")),
            "to": self._decode_header(msg.get("To", "")),
            "cc": self._decode_header(msg.get("Cc", "")),
            "bcc": self._decode_header(msg.get("Bcc", "")),
            "delivered_to": self._decode_header(" ".join(x for x in (msg.get("Delivered-To", ""), msg.get("X-Original-To", "")) if x)),
            "subject": self._decode_header(msg.get("Subject", "")),
            "message_id": self._decode_header(msg.get("Message-ID", "")),
            "date": self._safe_date(msg.get("Date", "")),
            "body_preview": "",
            "size": len(raw),
        }

    @staticmethod
    def _message_matches_recipient(msg: Dict, recipient: str) -> bool:
        target = str(recipient or "").strip().lower()
        if not target:
            return False
        hay = " ".join(str(msg.get(k) or "") for k in (
            "to", "cc", "bcc", "delivered_to", "recipient", "body", "body_preview"
        )).lower()
        return target in hay

    def fetch_body(self, msg_id: bytes) -> Optional[str]:
        self._ensure_connected()
        status, data = self._conn.uid("FETCH", msg_id, "(BODY.PEEK[TEXT])")
        if status != "OK":
            return None
        raw = self._extract_body(data)
        if not raw:
            return None
        try:
            return raw.decode("utf-8", errors="replace")
        except Exception:
            return raw.decode("latin-1", errors="replace")

    def fetch_full(self, msg_id: bytes) -> Optional[Dict]:
        self._ensure_connected()
        msg = self._fetch_full_message(msg_id)
        if not msg:
            return None
        hdr = self._fetch_headers_uid(msg_id)
        if hdr:
            msg.update(hdr)
        return msg

    def _fetch_full_message(self, msg_id: bytes) -> Optional[Dict]:
        status, data = self._conn.uid("FETCH", msg_id, "(BODY.PEEK[])")
        if status != "OK":
            status, data = self._conn.uid("FETCH", msg_id, "(RFC822)")
            if status != "OK":
                return None
        raw = self._extract_body(data)
        if not raw:
            return None
        try:
            em = email.message_from_bytes(raw)
        except Exception:
            return None

        body = ""
        html_body = ""
        if em.is_multipart():
            for part in em.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                ctype = part.get_content_type().split(';')[0].strip().lower()
                try:
                    payload = part.get_payload(decode=True)
                    if not payload:
                        continue
                    charset = part.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                    if ctype == "text/plain" and not body:
                        body = text
                    elif ctype == "text/html" and not html_body:
                        html_body = text
                except Exception:
                    pass
        else:
            try:
                payload = em.get_payload(decode=True)
                if payload:
                    charset = em.get_content_charset() or "utf-8"
                    text = payload.decode(charset, errors="replace")
                    ctype = em.get_content_type().split(';')[0].strip().lower()
                    if ctype == "text/plain":
                        body = text
                    elif ctype == "text/html":
                        html_body = text
                    else:
                        body = text
            except Exception:
                pass

        if not body and html_body:
            body = _strip_html(html_body)

        return {"body": body[:MAX_BODY_CHARS], "content_type": em.get_content_type(),
                "body_truncated": len(body) > MAX_BODY_CHARS}

    @staticmethod
    def _extract_body(data: list) -> Optional[bytes]:
        for item in data:
            if isinstance(item, tuple):
                for sub in item:
                    if isinstance(sub, bytes) and len(sub) > 500:
                        return sub
        for item in data:
            if isinstance(item, bytes) and len(item) > 500:
                return item
        best = None
        for item in data:
            if isinstance(item, bytes):
                if best is None or len(item) > len(best):
                    best = item
            elif isinstance(item, tuple):
                for sub in item:
                    if isinstance(sub, bytes):
                        if best is None or len(sub) > len(best):
                            best = sub
        return best if best and len(best) > 100 else None

    @staticmethod
    def _decode_header(value: str) -> str:
        if not value:
            return ""
        parts = decode_header(value)
        result = []
        for part, charset in parts:
            if isinstance(part, bytes):
                try:
                    result.append(part.decode(charset or "utf-8", errors="replace"))
                except Exception:
                    result.append(part.decode("utf-8", errors="replace"))
            else:
                result.append(str(part))
        return " ".join(result)

    def test_connection(self) -> Dict:
        try:
            self.connect()
            status, data = self._conn.select("INBOX", readonly=True)
            if status != "OK":
                return {"ok": False, "error": "无法选中 INBOX"}
            msg_count = int(data[0]) if data else 0
            self.disconnect()
            return {
                "ok": True,
                "email": self.apple_id,
                "inbox_count": msg_count,
                "region_host": self.region_host,
                "imap_server": self.imap_server,
                "imap_port": self.imap_port,
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:200]}

    @staticmethod
    def _safe_date(date_str: str) -> str:
        try:
            return parsedate_to_datetime(date_str).isoformat()
        except Exception:
            return date_str


def _strip_html(html: str) -> str:
    import re
    html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<(script|style|noscript)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</?(div|p|h[1-6]|li|tr|article|section|header|footer|blockquote|pre|table|hr)[^>]*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', r'\2 (\1)', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<li[^>]*>', '• ', html, flags=re.IGNORECASE)
    html = re.sub(r'<[^>]+>', '', html)
    import html as _html
    text = _html.unescape(html)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s+', '', text, flags=re.MULTILINE)
    return text.strip()


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python icloud_mail.py <apple_id> <app_password> [alias_email]")
        sys.exit(1)
    apple_id, app_pwd = sys.argv[1], sys.argv[2]
    alias = sys.argv[3] if len(sys.argv) > 3 else None
    mail = ICloudMail(apple_id, app_pwd, verbose=True)
    result = mail.test_connection()
    if result["ok"]:
        print(f"连接成功! 收件箱: {result['inbox_count']} 封")
    else:
        print(f"连接失败: {result['error']}")
        sys.exit(1)
    if alias:
        msgs = mail.find_by_recipient(alias, limit=10)
        for m in msgs:
            print(f"  [{m['date'][:19]}] {m['from'][:30]} | {m['subject'][:40]}")
    else:
        msgs = mail.check_inbox(limit=10)
        for m in msgs:
            print(f"  [{m['date'][:19]}] {m['from'][:30]} | {m['subject'][:40]}")
    mail.disconnect()
