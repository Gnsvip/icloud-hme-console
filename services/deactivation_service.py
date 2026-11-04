"""Detect provider access-deactivation notices without changing mailbox data."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable


_EMAIL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9._%+-])([A-Za-z0-9][A-Za-z0-9._%+\-]{0,63}"
    r"@(?:icloud\.com|icloud\.com\.cn|me\.com|mac\.com))(?![A-Za-z0-9._%+-])",
    re.IGNORECASE,
)
_DEACTIVATION_PATTERN = re.compile(
    r"访问权限已停用|账号已停用|帐户已停用|账户已停用|账户被停用|帐户被停用|"
    r"access\s+(?:to\s+(?:your\s+)?account\s+)?(?:has\s+been\s+)?deactivated|"
    r"account\s+(?:has\s+been\s+)?deactivated|access\s+deactivated|"
    r"your\s+account\s+has\s+been\s+(?:disabled|suspended)",
    re.IGNORECASE,
)
_OPENAI_PATTERN = re.compile(r"(?:@(?:tm\.)?openai\.com\b|\bopenai\b|\bchatgpt\b)", re.IGNORECASE)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _base_email(value: str) -> str:
    email = _text(value).lower()
    if "@" not in email:
        return email
    local, domain = email.rsplit("@", 1)
    if domain not in {"icloud.com", "icloud.com.cn", "me.com", "mac.com"} or "+" not in local:
        return email
    base_local, _tag = local.split("+", 1)
    return f"{base_local}@{domain}" if base_local else email


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _message_text(message: dict[str, Any]) -> str:
    return "\n".join(
        _text(message.get(key))
        for key in ("subject", "from", "to", "cc", "bcc", "delivered_to", "recipient", "body", "body_preview", "preview")
    )


def _known_alias_for_candidate(candidate: str, known: dict[str, str]) -> tuple[str, str] | None:
    normalized = candidate.lower()
    if normalized in known:
        return known[normalized], candidate
    base = _base_email(normalized)
    if base in known:
        return known[base], candidate
    return None


def detect_deactivation_notice(message: dict[str, Any], known_aliases: Iterable[str]) -> dict[str, Any] | None:
    """Resolve the exact +tag address while storing the real inventory key."""
    subject = _text(message.get("subject"))
    sender = _text(message.get("from") or message.get("sender"))
    body = _text(message.get("body") or message.get("body_preview") or message.get("preview"))
    combined = "\n".join((subject, sender, body))
    if not _DEACTIVATION_PATTERN.search(combined):
        return None
    if not _OPENAI_PATTERN.search("\n".join((subject, sender, body[:1200]))):
        return None

    known = {}
    for value in known_aliases or []:
        email = _text(value).lower()
        if "@" in email:
            known[email] = email
    if not known:
        return None

    resolved = None
    for match in _EMAIL_PATTERN.finditer(_message_text(message)):
        resolved = _known_alias_for_candidate(match.group(1), known)
        if resolved:
            break
    if not resolved:
        return None

    inventory_email, detected_email = resolved
    return {
        "email": inventory_email,
        "base_email": _base_email(detected_email),
        "detected_email": detected_email.lower(),
        "reason": "chatgpt_access_deactivated",
        "detected_at": _now(),
        "message_id": _text(message.get("message_id") or message.get("id")),
        "message_date": _text(message.get("date") or message.get("received_at") or message.get("internal_date")),
        "sender": sender,
        "subject": subject,
    }
