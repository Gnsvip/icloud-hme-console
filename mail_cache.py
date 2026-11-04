#!/usr/bin/env python3
"""
iCloud HME — 邮件本地缓存
===========================
有期限和容量上限的本地副本，增量更新，去重合并。

存储: results/mail_cache.json
"""

import json
import os
import tempfile
import threading
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
CACHE_FILE = HERE / "results" / "mail_cache.json"
CACHE_RETENTION_DAYS = 30
MAX_ALIAS_MESSAGES = 50
MAX_ACCOUNT_ALIAS_MESSAGES = 5000
MAX_MESSAGE_BODIES = 1000
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_LIST_BYTES = 16 * 1024 * 1024


class MailCache:
    """邮件本地缓存"""

    def __init__(self):
        self._lock = threading.RLock()
        self._data: Dict = {}
        self._dirty = False
        self.revision = 0
        self._last_cleanup = 0.0
        self._load()

    def _load(self):
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if CACHE_FILE.exists():
            try:
                self._data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError("邮件缓存读取失败，已保留原文件，请恢复备份或移走损坏的缓存") from exc
        if not isinstance(self._data, dict) or any(not isinstance(v, dict) for v in self._data.values()):
            raise RuntimeError("邮件缓存格式损坏，已保留原文件")
        self._cleanup()

    def _prune_account(self, acc_id):
        account = self._data[acc_id]
        now = time.time()
        cutoff = now - CACHE_RETENTION_DAYS * 86400
        old_times = account.get("cached_at", {})
        times = {}
        changed = False
        list_bytes = 0

        def keep(key):
            stamp = old_times.get(key, now)
            if stamp < cutoff:
                return False
            times[key] = stamp
            return True

        inbox = account.get("inbox_emails", [])
        kept = []
        for msg in self._sort_messages(inbox)[:500]:
            key = "inbox:" + str(msg.get("id", ""))
            length = len(json.dumps(msg, ensure_ascii=False).encode("utf-8"))
            if list_bytes + length <= MAX_LIST_BYTES and keep(key):
                kept.append(msg)
                list_bytes += length
        changed |= inbox != kept
        account["inbox_emails"] = kept
        aliases = account.get("alias_emails", {})
        candidates = []
        for alias, messages in aliases.items():
            for msg in self._sort_messages(messages)[:MAX_ALIAS_MESSAGES]:
                key = "alias:" + alias + ":" + str(msg.get("id", ""))
                if old_times.get(key, now) >= cutoff:
                    candidates.append((old_times.get(key, now), self._message_ts(msg), alias, msg, key))
        candidates.sort(key=lambda item: item[:2], reverse=True)
        kept_aliases = {}
        for _, _, alias, msg, key in candidates[:MAX_ACCOUNT_ALIAS_MESSAGES]:
            length = len(json.dumps(msg, ensure_ascii=False).encode("utf-8"))
            if list_bytes + length > MAX_LIST_BYTES:
                continue
            list_bytes += length
            kept_aliases.setdefault(alias, []).append(msg)
            keep(key)
        changed |= aliases != kept_aliases
        account["alias_emails"] = kept_aliases
        bodies = account.get("message_bodies", {})
        kept_bodies = {}
        size = 0
        ordered = sorted(bodies, key=lambda uid: (old_times.get("body:" + uid, now), self._message_ts(bodies[uid])), reverse=True)
        for uid in ordered:
            key = "body:" + uid
            if old_times.get(key, now) < cutoff or len(kept_bodies) >= MAX_MESSAGE_BODIES:
                continue
            length = len(json.dumps(bodies[uid], ensure_ascii=False).encode("utf-8"))
            if size + length > MAX_BODY_BYTES:
                continue
            size += length
            kept_bodies[uid] = bodies[uid]
            keep(key)
        changed |= bodies != kept_bodies
        account["message_bodies"] = kept_bodies
        changed |= times != old_times
        account["cached_at"] = times
        self._dirty |= changed
        return changed

    def _cleanup(self):
        self._last_cleanup = time.monotonic()
        for acc_id in self._data:
            self._prune_account(acc_id)
        if self._dirty:
            self._save()

    def _stamp_changed(self, acc_id, prefix, incoming, existing):
        times = self._data[acc_id].setdefault("cached_at", {})
        previous = {str(msg.get("id", "")): msg for msg in existing}
        for msg in incoming:
            uid = str(msg.get("id", ""))
            if previous.get(uid) != msg:
                times[prefix + uid] = time.time()

    def _save(self):
        with self._lock:
            self._dirty = True
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix=".mail-cache-", dir=CACHE_FILE.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self._data, handle, ensure_ascii=False, separators=(",", ":"))
                os.replace(name, CACHE_FILE)
                self._dirty = False
                self.revision += 1
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def _ensure_account(self, acc_id: str):
        if time.monotonic() - self._last_cleanup >= 3600:
            self._cleanup()
        if acc_id not in self._data:
            self._data[acc_id] = {
                "last_checked": None,
                "inbox_emails": [],
                "alias_emails": {},
                "message_bodies": {},
            }
        else:
            self._data[acc_id].setdefault("message_bodies", {})

    @staticmethod
    def _message_ts(msg: Dict) -> float:
        date_str = str(msg.get("internal_date") or msg.get("received_at") or msg.get("date") or "").strip()
        if date_str:
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
            try:
                return parsedate_to_datetime(date_str).timestamp()
            except Exception:
                pass
        try:
            return float(msg.get("id") or 0)
        except Exception:
            return 0.0

    @classmethod
    def _sort_messages(cls, emails: List[Dict]) -> List[Dict]:
        return sorted(
            emails,
            key=lambda m: (cls._message_ts(m), str(m.get("id") or "")),
            reverse=True,
        )

    @classmethod
    def _merge_unique(cls, existing: List[Dict], incoming: List[Dict]) -> List[Dict]:
        by_id: Dict[str, Dict] = {}
        no_id: List[Dict] = []
        for msg in list(existing or []) + list(incoming or []):
            if not isinstance(msg, dict):
                continue
            msg_id = str(msg.get("id") or "").strip()
            if msg_id:
                by_id[msg_id] = msg
            else:
                no_id.append(msg)
        return cls._sort_messages(list(by_id.values()) + no_id)

    def get_inbox(self, acc_id: str) -> List[Dict]:
        with self._lock:
            self._ensure_account(acc_id)
            return self._sort_messages(list(self._data[acc_id].get("inbox_emails", [])))

    def set_inbox(self, acc_id: str, emails: List[Dict]):
        with self._lock:
            self._ensure_account(acc_id)
            self._stamp_changed(acc_id, "inbox:", emails, self._data[acc_id]["inbox_emails"])
            self._data[acc_id]["inbox_emails"] = self._merge_unique(
                self._data[acc_id]["inbox_emails"], emails
            )
            if len(self._data[acc_id]["inbox_emails"]) > 500:
                self._data[acc_id]["inbox_emails"] = \
                    self._data[acc_id]["inbox_emails"][:500]
            self._data[acc_id]["last_checked"] = datetime.now().isoformat()
            self._prune_account(acc_id)
            self._save()

    def get_alias_mail(self, acc_id: str, alias_email: str) -> List[Dict]:
        with self._lock:
            self._ensure_account(acc_id)
            return self._sort_messages(
                list(self._data[acc_id].get("alias_emails", {}).get(alias_email, []))
            )

    def set_alias_mail(self, acc_id: str, alias_email: str, emails: List[Dict]):
        with self._lock:
            self._ensure_account(acc_id)
            if alias_email not in self._data[acc_id]["alias_emails"]:
                self._data[acc_id]["alias_emails"][alias_email] = []
            merged = self._merge_unique(
                self._data[acc_id]["alias_emails"][alias_email], emails
            )
            if merged != self._data[acc_id]["alias_emails"][alias_email]:
                self._stamp_changed(acc_id, "alias:" + alias_email + ":", emails, self._data[acc_id]["alias_emails"][alias_email])
                self._data[acc_id]["alias_emails"][alias_email] = merged
                self._dirty = True
            if self._dirty:
                self._prune_account(acc_id)
                self._save()

    def set_alias_mail_batch(self, acc_id: str, by_alias: Dict[str, List[Dict]]):
        with self._lock:
            self._ensure_account(acc_id)
            changed = False
            for alias, emails in by_alias.items():
                if alias not in self._data[acc_id]["alias_emails"]:
                    self._data[acc_id]["alias_emails"][alias] = []
                merged = self._merge_unique(
                    self._data[acc_id]["alias_emails"][alias], emails
                )
                if merged != self._data[acc_id]["alias_emails"][alias]:
                    self._stamp_changed(acc_id, "alias:" + alias + ":", emails, self._data[acc_id]["alias_emails"][alias])
                    self._data[acc_id]["alias_emails"][alias] = merged
                    changed = True
            if changed or self._dirty:
                self._prune_account(acc_id)
                self._save()

    def get_message(self, acc_id: str, msg_id: str) -> Optional[Dict]:
        with self._lock:
            self._ensure_account(acc_id)
            msg = self._data[acc_id].get("message_bodies", {}).get(str(msg_id))
            return dict(msg) if isinstance(msg, dict) else None

    def set_message(self, acc_id: str, msg_id: str, message: Dict):
        if not message:
            return
        self.set_messages(acc_id, {str(msg_id): message})

    def set_messages(self, acc_id: str, messages: Dict[str, Dict]):
        """Persist a fetched batch once; identical bodies need no disk write."""
        with self._lock:
            self._ensure_account(acc_id)
            bodies = self._data[acc_id]["message_bodies"]
            changed = False
            for msg_id, message in messages.items():
                if message and bodies.get(str(msg_id)) != message:
                    bodies[str(msg_id)] = dict(message)
                    self._data[acc_id].setdefault("cached_at", {})["body:" + str(msg_id)] = time.time()
                    changed = True
            if changed or self._dirty:
                self._prune_account(acc_id)
                self._save()

    def get_all_alias_mail(self, acc_id: str) -> Dict[str, List[Dict]]:
        with self._lock:
            self._ensure_account(acc_id)
            return {
                alias: self._sort_messages(list(emails))
                for alias, emails in self._data[acc_id].get("alias_emails", {}).items()
            }

    def last_checked(self, acc_id: str) -> Optional[str]:
        with self._lock:
            self._ensure_account(acc_id)
            return self._data[acc_id].get("last_checked")

    def cache_age_seconds(self, acc_id: str):
        lc = self.last_checked(acc_id)
        if not lc:
            return None
        try:
            dt = datetime.fromisoformat(lc)
            return (datetime.now() - dt).total_seconds()
        except Exception:
            return None

    def clear_account(self, acc_id: str):
        with self._lock:
            if acc_id in self._data:
                del self._data[acc_id]
                self._save()

    def clear_all(self):
        with self._lock:
            self._data = {}
            self._save()

    def get_stats(self, acc_id: str) -> Dict:
        with self._lock:
            self._ensure_account(acc_id)
            acc = self._data[acc_id]
            inbox_count = len(acc.get("inbox_emails", []))
            alias_count = sum(len(v) for v in acc.get("alias_emails", {}).values())
            return {
                "last_checked": acc.get("last_checked"),
                "cache_age_sec": self.cache_age_seconds(acc_id),
                "inbox_cached": inbox_count,
                "alias_cached": alias_count,
                "alias_count": len(acc.get("alias_emails", {})),
                "body_cached": len(acc.get("message_bodies", {})),
            }


_mail_cache: Optional[MailCache] = None


def get_cache() -> MailCache:
    global _mail_cache
    if _mail_cache is None:
        _mail_cache = MailCache()
    return _mail_cache
