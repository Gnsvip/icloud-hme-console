#!/usr/bin/env python3
"""
iCloud HME — 邮件本地缓存
===========================
一次拉取终身存储，增量更新，去重合并。

存储: results/mail_cache.json
"""

import json
import os
import tempfile
import threading
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
CACHE_FILE = HERE / "results" / "mail_cache.json"


class MailCache:
    """邮件本地缓存"""

    def __init__(self):
        self._lock = threading.RLock()
        self._data: Dict = {}
        self._dirty = False
        self._load()

    def _load(self):
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        if CACHE_FILE.exists():
            try:
                self._data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            except Exception:
                self._data = {}

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
            finally:
                if os.path.exists(name):
                    os.unlink(name)

    def _ensure_account(self, acc_id: str):
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
            self._data[acc_id]["inbox_emails"] = self._merge_unique(
                self._data[acc_id]["inbox_emails"], emails
            )
            if len(self._data[acc_id]["inbox_emails"]) > 500:
                self._data[acc_id]["inbox_emails"] = \
                    self._data[acc_id]["inbox_emails"][:500]
            self._data[acc_id]["last_checked"] = datetime.now().isoformat()
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
                self._data[acc_id]["alias_emails"][alias_email] = merged
                self._dirty = True
            if self._dirty:
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
                    self._data[acc_id]["alias_emails"][alias] = merged
                    changed = True
            if changed or self._dirty:
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
                    changed = True
            if changed or self._dirty:
                self._save()

    def get_all_alias_mail(self, acc_id: str) -> Dict[str, List[Dict]]:
        with self._lock:
            self._ensure_account(acc_id)
            return {
                alias: self._sort_messages(list(emails))
                for alias, emails in self._data[acc_id].get("alias_emails", {}).items()
            }

    def last_checked(self, acc_id: str) -> Optional[str]:
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
