import concurrent.futures
import datetime as dt
import html
import json
import re
import secrets
import threading
from email.utils import parsedate_to_datetime

from app_core import *


_pickup_links_lock = threading.Lock()
_pickup_query_lock = threading.Lock()
_pickup_queries = {}
_pickup_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=16,
    thread_name_prefix="pickup",
)
PICKUP_LINKS_FILE = RESULTS_DIR / "pickup_links.json"
_pickup_email_pattern = re.compile(
    r"^[a-z0-9][a-z0-9._+-]{0,63}@(icloud\.com|icloud\.com\.cn|me\.com|mac\.com)$",
    re.IGNORECASE,
)
_pickup_tag_alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"


def _pickup_utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean_pickup_body(value):
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>|</(?:p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", text)
    text = re.sub(r"\s*\((?:https?://|www\.)[^\s)]*(?:\)|$)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:https?://|www\.)\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^\s*[()<>]+\s*$", "", text)
    return text.strip()


def _read_pickup_links():
    try:
        data = json.loads(PICKUP_LINKS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("links"), dict):
            data.setdefault("next_id", 1000)
            data.setdefault("by_email", {})
            return data
    except (OSError, ValueError, TypeError):
        pass
    return {"next_id": 1000, "links": {}, "by_email": {}}


def _write_pickup_links(data):
    PICKUP_LINKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = PICKUP_LINKS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PICKUP_LINKS_FILE)
    try:
        PICKUP_LINKS_FILE.chmod(0o600)
    except OSError:
        pass


def active_pickup_link_statuses():
    """Return active pickup-link counts grouped by the base iCloud alias."""
    with _pickup_links_lock:
        data = _read_pickup_links()
    grouped = {}
    for link_id, record in data.get("links", {}).items():
        if not isinstance(record, dict) or not record.get("active", True):
            continue
        email = str(record.get("email") or "").strip().lower()
        if not _pickup_email_pattern.fullmatch(email):
            continue
        base_email = base_icloud_email_address(email)
        status = grouped.setdefault(base_email, {
            "has_pickup_link": True,
            "pickup_link_count": 0,
            "pickup_link_emails": [],
            "pickup_link_created_at": "",
        })
        status["pickup_link_count"] += 1
        status["pickup_link_emails"].append(email)
        created_at = str(record.get("created_at") or "")
        if created_at > status["pickup_link_created_at"]:
            status["pickup_link_created_at"] = created_at
    for status in grouped.values():
        status["pickup_link_emails"] = sorted(set(status["pickup_link_emails"]))
    return grouped


def _pickup_link_inventory_item(email):
    base_email = base_icloud_email_address(email)
    readable_account_ids = {
        str(account.get("id") or "")
        for account in _account_mgr.list_accounts()
        if _account_can_read_mail(account)
    }
    rows, _summary = _inventory.list_items(group="all", query=base_email)
    return next((
        row for row in rows
        if str(row.get("email") or "").strip().lower() == base_email
        and row.get("active", True)
        and row.get("lifecycle_status") != "disabled"
        and str(row.get("account_id") or "") in readable_account_ids
    ), None)


def _random_pickup_tag(length=8):
    return "".join(secrets.choice(_pickup_tag_alphabet) for _ in range(length))


def _append_pickup_link_record(data, email):
    link_id = max(1000, int(data.get("next_id") or 1000))
    while str(link_id) in data.get("links", {}):
        link_id += 1
    link_id = str(link_id)
    record = {
        "email": email,
        "token": secrets.token_urlsafe(24),
        "active": True,
        "created_at": _pickup_utc_now(),
    }
    data["links"][link_id] = record
    data["by_email"][email] = link_id
    data["next_id"] = int(link_id) + 1
    result = dict(record)
    result["id"] = link_id
    return result


def create_pickup_link(email, regenerate=False):
    email = str(email or "").strip().lower()
    if not _pickup_email_pattern.fullmatch(email):
        return None, "请填写正确的邮箱地址"
    if not _pickup_link_inventory_item(email):
        return None, "邮箱不在收码台中"

    with _pickup_links_lock:
        data = _read_pickup_links()
        existing_id = str(data.get("by_email", {}).get(email) or "")
        existing = data.get("links", {}).get(existing_id)
        if existing and existing.get("active", True) and not regenerate:
            record = dict(existing)
            record["id"] = existing_id
            return record, ""
        if existing and regenerate:
            existing["active"] = False

        result = _append_pickup_link_record(data, email)
        _write_pickup_links(data)
        _emit_log("info", f"生成取码链接：{email}（链接 ID {result['id']}）")
        return result, ""


def create_random_pickup_links(email, count):
    base_email = base_icloud_email_address(email)
    if not _pickup_email_pattern.fullmatch(base_email):
        return [], "请填写正确的邮箱地址"
    try:
        count = int(count)
    except (TypeError, ValueError):
        return [], "生成数量不正确"
    if count < 1 or count > 100:
        return [], "每个邮箱生成数量必须是 1 到 100"
    if not _pickup_link_inventory_item(base_email):
        return [], "邮箱不在收码台中"

    local, domain = base_email.rsplit("@", 1)
    with _pickup_links_lock:
        data = _read_pickup_links()
        used_emails = {
            str(record.get("email") or "").strip().lower()
            for record in data.get("links", {}).values()
            if isinstance(record, dict)
        }
        candidates = []
        for _ in range(count):
            for _attempt in range(100):
                candidate = f"{local}+{_random_pickup_tag()}@{domain}"
                if _pickup_email_pattern.fullmatch(candidate) and candidate not in used_emails:
                    used_emails.add(candidate)
                    candidates.append(candidate)
                    break
            else:
                return [], "暂时无法生成不重复的随机别名，请重试"

        records = [_append_pickup_link_record(data, candidate) for candidate in candidates]
        _write_pickup_links(data)
    _emit_log("info", f"随机生成取码链接：{base_email} / {len(records)} 个")
    return records, ""


def resolve_pickup_link(link_id, token):
    link_id = str(link_id or "").strip()
    token = str(token or "").strip()
    if not link_id.isdigit() or not token:
        return None
    with _pickup_links_lock:
        record = _read_pickup_links().get("links", {}).get(link_id)
    if not record or not record.get("active", True):
        return None
    expected = str(record.get("token") or "")
    if not expected or not secrets.compare_digest(token, expected):
        return None
    email = str(record.get("email") or "").strip().lower()
    if not _pickup_email_pattern.fullmatch(email):
        return None
    return {"id": link_id, "email": email}


def revoke_pickup_links(link_ids):
    values = link_ids if isinstance(link_ids, list) else [link_ids]
    requested = list(dict.fromkeys(
        str(link_id or "").strip()
        for link_id in values
        if str(link_id or "").strip().isdigit()
    ))
    if not requested:
        return [], []

    revoked = []
    missing = []
    with _pickup_links_lock:
        data = _read_pickup_links()
        links = data.get("links", {})
        by_email = data.get("by_email", {})
        revoked_at = _pickup_utc_now()
        for link_id in requested:
            record = links.get(link_id)
            if not isinstance(record, dict) or not record.get("active", True):
                missing.append(link_id)
                continue
            record["active"] = False
            record["revoked_at"] = revoked_at
            email = str(record.get("email") or "").strip().lower()
            if email and str(by_email.get(email) or "") == link_id:
                by_email.pop(email, None)
            revoked.append(link_id)
        if revoked:
            _write_pickup_links(data)
    return revoked, missing


def api_pickup_link_for_email(email_addr):
    data = request.get_json(silent=True) or {}
    record, error = create_pickup_link(email_addr, regenerate=bool(data.get("regenerate")))
    if not record:
        return jsonify({"ok": False, "error": error}), 404 if error == "邮箱不在收码台中" else 400
    pickup_url = f"/c/{record['id']}?token={record['token']}"
    return jsonify({
        "ok": True,
        "email": record["email"],
        "pickup_url": pickup_url,
    })


def _pickup_batch_entries(raw):
    values = raw if isinstance(raw, list) else [raw]
    entries = []
    seen = set()
    for value in values:
        for chunk in re.split(r"[\s,;，；]+", str(value or "")):
            email = chunk.split("----", 1)[0].strip().lower()
            if not email or email in seen:
                continue
            seen.add(email)
            entries.append(email)
    return entries


def api_pickup_links_batch():
    data = request.get_json(silent=True) or {}
    emails = _pickup_batch_entries(data.get("emails", []))
    if not emails:
        return jsonify({"ok": False, "results": [], "errors": [], "error": "请填写邮箱地址"}), 400

    random_tags = data.get("random_tags") is True
    try:
        per_email = int(data.get("per_email", 1))
    except (TypeError, ValueError):
        per_email = 0
    if per_email < 0 or per_email > 100:
        return jsonify({"ok": False, "results": [], "errors": [], "error": "额外别名数量必须是 0 到 100"}), 400
    generate_random_tags = random_tags and per_email > 0
    if generate_random_tags and len(emails) * (per_email + 1) > 5000:
        return jsonify({"ok": False, "results": [], "errors": [], "error": "单次最多生成 5000 个取码链接"}), 400

    results = []
    errors = []
    if generate_random_tags:
        base_emails = []
        seen_bases = set()
        for email in emails:
            base_email = base_icloud_email_address(email)
            if not _pickup_email_pattern.fullmatch(base_email):
                errors.append({"email": email, "error": "邮箱格式不正确"})
                continue
            if base_email in seen_bases:
                continue
            seen_bases.add(base_email)
            base_emails.append(base_email)
        for base_email in base_emails:
            original, original_error = create_pickup_link(base_email)
            if not original:
                errors.append({"email": base_email, "error": original_error or "原邮箱取码链接生成失败"})
                continue
            results.append({
                "email": original["email"],
                "lookup_email": base_email,
                "pickup_url": f"/c/{original['id']}?token={original['token']}",
            })
            records, error = create_random_pickup_links(base_email, per_email)
            if not records:
                errors.append({"email": base_email, "error": error or "随机别名取码链接生成失败"})
                continue
            results.extend({
                "email": record["email"],
                "lookup_email": base_email,
                "pickup_url": f"/c/{record['id']}?token={record['token']}",
            } for record in records)
    else:
        for email in emails:
            if not _pickup_email_pattern.fullmatch(email):
                errors.append({"email": email, "error": "邮箱格式不正确"})
                continue
            record, error = create_pickup_link(email)
            if not record:
                errors.append({"email": email, "error": error or "取码链接生成失败"})
                continue
            results.append({
                "email": record["email"],
                "lookup_email": base_icloud_email_address(record["email"]),
                "pickup_url": f"/c/{record['id']}?token={record['token']}",
            })

    _emit_log("info", f"批量生成取码链接：{len(results)} 成功 / {len(errors)} 失败")
    return jsonify({
        "ok": bool(results),
        "results": results,
        "errors": errors,
        "count": len(results),
        "failed": len(errors),
        "random_tags": generate_random_tags,
        "per_email": per_email,
    })


def api_pickup_links():
    query = str(request.args.get("q") or "").strip().lower()
    page = max(1, request.args.get("page", 1, type=int))
    page_size = max(1, min(request.args.get("page_size", 100, type=int), 5000))
    with _pickup_links_lock:
        data = _read_pickup_links()

    records = []
    for link_id, record in data.get("links", {}).items():
        if not isinstance(record, dict) or not record.get("active", True):
            continue
        email = str(record.get("email") or "").strip().lower()
        token = str(record.get("token") or "").strip()
        if not _pickup_email_pattern.fullmatch(email) or not str(link_id).isdigit() or not token:
            continue
        if query and query not in email:
            continue
        records.append({
            "id": str(link_id),
            "email": email,
            "pickup_url": f"/c/{link_id}?token={token}",
            "created_at": str(record.get("created_at") or ""),
        })

    records.sort(
        key=lambda row: (row.get("created_at") or "", int(row["id"])),
        reverse=True,
    )
    total = len(records)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, pages)
    start = (page - 1) * page_size
    return jsonify({
        "ok": True,
        "records": records[start:start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
        "query": query,
    })


def api_revoke_pickup_link(link_id):
    revoked, _missing = revoke_pickup_links([link_id])
    if not revoked:
        return jsonify({"ok": False, "error": "链接不存在或已经失效"}), 404
    return jsonify({"ok": True, "revoked": revoked, "count": 1})


def api_revoke_pickup_links_batch():
    data = request.get_json(silent=True) or {}
    link_ids = data.get("link_ids") or []
    if not isinstance(link_ids, list) or not link_ids:
        return jsonify({"ok": False, "error": "请选择需要失效的链接"}), 400
    revoked, missing = revoke_pickup_links(link_ids)
    return jsonify({
        "ok": bool(revoked),
        "revoked": revoked,
        "missing": missing,
        "count": len(revoked),
        "error": "链接不存在或已经失效" if not revoked else "",
    }), 200 if revoked else 404


def _message_matches_pickup_email(message, email):
    target = str(email or "").strip().lower()
    haystack = " ".join(
        str(message.get(key) or "")
        for key in ("to", "cc", "bcc", "delivered_to", "recipient")
    ).lower()
    return bool(target) and target in haystack


def _cached_pickup_messages(acc_id, email):
    messages = list(_account_mgr._cache.get_alias_mail(acc_id, email) or [])
    messages.extend(
        message for message in (_account_mgr._cache.get_inbox(acc_id) or [])
        if _message_matches_pickup_email(message, email)
    )
    unique = {}
    for message in messages:
        key = (str(message.get("mailbox") or "INBOX"), str(message.get("id") or ""))
        current = unique.get(key)
        if current is None or (message.get("body") and not current.get("body")):
            unique[key] = message
    return sorted(unique.values(), key=_message_sort_timestamp, reverse=True)


def _public_pickup_message(message):
    raw_body = str(message.get("body") or message.get("body_preview") or "").strip()
    code_text = "{}\n{}\n{}".format(message.get("subject", ""), raw_body, message.get("body_preview", ""))
    code = extract_verification_code(code_text)
    body = _clean_pickup_body(raw_body)
    return {
        "id": str(message.get("id") or ""),
        "from": str(message.get("from") or ""),
        "subject": str(message.get("subject") or "(无主题)"),
        "date": str(message.get("internal_date") or message.get("received_at") or message.get("date") or ""),
        "body": body[:5000],
        "code": code,
    }


def _pickup_response(email, messages, source, refreshed=False):
    ordered = sorted(messages or [], key=_message_sort_timestamp, reverse=True)[:2]
    public_messages = [_public_pickup_message(message) for message in ordered]
    code = next((message.get("code") for message in public_messages if message.get("code")), "")
    return {
        "ok": True,
        "email": email,
        "code": code,
        "messages": public_messages,
        "count": len(public_messages),
        "source": source,
        "refreshed": bool(refreshed),
        "checked_at": _pickup_utc_now(),
    }


def _latest_six_digit_code_payload(mailbox_id, result):
    messages = result.get("messages") or []
    latest_message = messages[0] if messages else {}
    code_message = next(
        (
            message for message in messages
            if re.fullmatch(r"\d{6}", str(message.get("code") or ""))
        ),
        None,
    )
    display_message = code_message or latest_message
    code = str((code_message or {}).get("code") or "")
    message_id = str(display_message.get("id") or "")
    mail_time = str(display_message.get("date") or "")
    sender = str(display_message.get("from") or "")
    subject = str(display_message.get("subject") or "")
    return {
        "ok": True,
        "status": "ready" if code else "waiting",
        "mailbox_id": str(mailbox_id or ""),
        "email": str(result.get("email") or ""),
        "code": code,
        "message_id": message_id,
        "mail_time": mail_time,
        "sender": sender,
        "subject": subject,
        "message": {
            "id": message_id,
            "time": mail_time,
            "from": sender,
            "subject": subject,
        } if display_message else None,
        "checked_at": str(result.get("checked_at") or _pickup_utc_now()),
    }


def _stored_pickup_code_payload(mailbox_id, email, record=None, status="ready"):
    if record is None:
        with _pickup_links_lock:
            record = _read_pickup_links().get("links", {}).get(str(mailbox_id or ""))
    if not isinstance(record, dict) or not record.get("active", True):
        return None
    code = str(record.get("last_code") or "")
    if not re.fullmatch(r"\d{6}", code):
        return None
    message_id = str(record.get("last_code_message_id") or "")
    mail_time = str(record.get("last_code_mail_time") or "")
    sender = str(record.get("last_code_sender") or "")
    subject = str(record.get("last_code_subject") or "")
    return {
        "ok": status != "retry",
        "status": status,
        "mailbox_id": str(mailbox_id or ""),
        "email": str(email or record.get("email") or ""),
        "code": code,
        "message_id": message_id,
        "mail_time": mail_time,
        "sender": sender,
        "subject": subject,
        "message": {
            "id": message_id,
            "time": mail_time,
            "from": sender,
            "subject": subject,
        },
        "checked_at": str(record.get("last_code_updated_at") or mail_time or _pickup_utc_now()),
        "retained": True,
    }


def _remember_pickup_code_payload(mailbox_id, payload):
    code = str(payload.get("code") or "")
    if not re.fullmatch(r"\d{6}", code):
        return payload
    link_id = str(mailbox_id or "")
    incoming = {
        "last_code": code,
        "last_code_message_id": str(payload.get("message_id") or ""),
        "last_code_mail_time": str(payload.get("mail_time") or ""),
        "last_code_sender": str(payload.get("sender") or ""),
        "last_code_subject": str(payload.get("subject") or ""),
    }
    with _pickup_links_lock:
        data = _read_pickup_links()
        record = data.get("links", {}).get(link_id)
        if not isinstance(record, dict) or not record.get("active", True):
            return payload
        stored_email = str(record.get("email") or "").strip().lower()
        payload_email = str(payload.get("email") or "").strip().lower()
        if not stored_email or stored_email != payload_email:
            return payload
        changed = any(str(record.get(key) or "") != value for key, value in incoming.items())
        if changed:
            record.update(incoming)
            record["last_code_updated_at"] = str(payload.get("checked_at") or _pickup_utc_now())
            _write_pickup_links(data)
        stored = _stored_pickup_code_payload(
            link_id,
            payload.get("email"),
            record=record,
        )
    if stored:
        stored["retained"] = False
        return stored
    return payload


def _tag_account_messages(acc_id, messages):
    account = _account_mgr.get_account(acc_id) or {}
    tagged = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        row = dict(msg)
        row["account_id"] = acc_id
        row["account_icloud_email"] = account.get("icloud_email") or account.get("real_email") or ""
        tagged.append(row)
    return tagged


def _cached_alias_messages_as_inbox(acc_id, limit):
    by_alias = _account_mgr._cache.get_all_alias_mail(acc_id)
    if not by_alias:
        return []
    rows = []
    seen = set()
    for alias_email, messages in by_alias.items():
        for msg in messages or []:
            if not isinstance(msg, dict):
                continue
            row = dict(msg)
            row.setdefault("recipient", alias_email)
            if not row.get("to"):
                row["to"] = f"Hide My Email <{alias_email}>"
            key = str(row.get("id") or "").strip()
            if not key:
                key = "|".join(str(row.get(k) or "") for k in ("date", "subject", "to", "recipient"))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    rows = _attach_cached_bodies(acc_id, rows)
    rows.sort(
        key=lambda m: (
            str(m.get("internal_date") or m.get("received_at") or m.get("date") or ""),
            str(m.get("id") or ""),
        ),
        reverse=True,
    )
    return _tag_account_messages(acc_id, rows[:limit])


def _inbox_account_result(acc_id, limit, refresh=False, cache_only=False):
    account = _account_mgr.get_account(acc_id)
    if not account:
        return {"ok": False, "emails": [], "count": 0, "error": "账号不存在", "account_id": acc_id}
    if not account.get("app_password"):
        return {
            "ok": False,
            "emails": [],
            "count": 0,
            "error": "未设置 App 专用密码",
            "account_id": acc_id,
        }
    if not account.get("icloud_email") and "icloud.com" not in account.get("real_email", ""):
        return {
            "ok": False,
            "emails": [],
            "count": 0,
            "error": "未设置 iCloud 邮箱",
            "account_id": acc_id,
        }

    cached = _account_mgr._cache.get_inbox(acc_id)[:limit]
    if cached and (cache_only or not refresh):
        emails = _tag_account_messages(acc_id, _attach_cached_bodies(acc_id, cached))
        _sync_inventory_from_messages(emails, account_id=acc_id, method="iCloud 收件箱缓存")
        return {
            "ok": True,
            "emails": emails,
            "count": len(emails),
            "cached": _account_mgr._cache.get_stats(acc_id),
            "cache_first": True,
            "source": "inbox_cache",
            "account_id": acc_id,
        }

    alias_cached = _cached_alias_messages_as_inbox(acc_id, limit)
    if cache_only:
        if alias_cached:
            _sync_inventory_from_messages(alias_cached, account_id=acc_id, method="iCloud 查件缓存")
        return {
            "ok": True,
            "emails": alias_cached,
            "count": len(alias_cached),
            "cached": _account_mgr._cache.get_stats(acc_id),
            "cache_first": True,
            "source": "alias_cache" if alias_cached else "empty_cache",
            "account_id": acc_id,
        }

    emails = _run_imap_with_timeout(
        lambda: _account_mgr.check_inbox(acc_id, limit=limit, force=refresh)
    )
    emails = _tag_account_messages(acc_id, _attach_cached_bodies(acc_id, emails))
    if not emails and alias_cached:
        emails = alias_cached
        source = "alias_cache"
    else:
        source = "inbox_refresh" if refresh else "inbox"
    _sync_inventory_from_messages(emails, account_id=acc_id, method="iCloud 收件箱")
    return {
        "ok": True,
        "emails": emails,
        "count": len(emails),
        "cached": _account_mgr._cache.get_stats(acc_id),
        "source": source,
        "refreshed": bool(refresh),
        "account_id": acc_id,
    }


def _message_sort_timestamp(message):
    for field in ("internal_date", "received_at", "date"):
        value = message.get(field)
        if not value:
            continue
        try:
            return parsedate_to_datetime(str(value)).timestamp()
        except Exception:
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
            except Exception:
                pass
    try:
        return float(message.get("id") or 0)
    except Exception:
        return 0


def api_set_app_password(acc_id):
    data = request.get_json() or {}
    pwd = data.get("app_password","").strip()
    icloud_email = data.get("icloud_email","").strip()
    if not pwd: return jsonify({"ok":False,"error":"密码不能为空"})
    if icloud_email and not _is_icloud_mail_address(icloud_email):
        return jsonify({
            "ok": False,
            "saved": False,
            "error": f"iCloud 邮箱不能填 {icloud_email}。这里不是 Apple ID，要填 @icloud.com / @me.com / @mac.com 邮箱。"
        })
    try:
        _account_mgr.set_app_password(acc_id, pwd)
        if icloud_email: _account_mgr.update_account(acc_id, icloud_email=icloud_email)
    except Exception as e:
        return jsonify({"ok":False,"saved":False,"error":str(e)})
    try:
        result = _run_imap_with_timeout(lambda: _account_mgr.test_imap_connection(acc_id), timeout=30)
    except Exception as e:
        result = {"ok": False, "error": str(e)}
    if result.get("ok"):
        _account_mgr.update_account(acc_id, last_mail_error=None)
        result["saved"] = True
        result["app_password"] = pwd
        return jsonify(result)
    err = result.get("error", "连接测试失败")
    _account_mgr.update_account(acc_id, last_mail_error=err)
    return jsonify({"ok":False,"saved":True,"error":err,"app_password":pwd})

def api_inbox(acc_id):
    limit = max(1, min(request.args.get("limit",50,type=int), 200))
    force = request.args.get("force","0")=="1"
    cache_only = request.args.get("cache_only", "0") == "1"
    try:
        return jsonify(_inbox_account_result(acc_id, limit, refresh=force, cache_only=cache_only))
    except Exception as e:
        return jsonify({"ok": False, "emails": [], "count": 0, "error": str(e), "account_id": acc_id})


def api_all_inboxes():
    limit = max(1, min(request.args.get("limit", 50, type=int), 200))
    refresh = request.args.get("refresh", "0") == "1"
    cache_only = request.args.get("cache_only", "0") == "1"
    accounts = [a for a in _account_mgr.list_accounts() if a.get("status") == "active"]
    if not accounts:
        accounts = _account_mgr.list_accounts()

    def load(account):
        acc_id = account.get("id", "")
        try:
            result = _inbox_account_result(acc_id, limit, refresh=refresh, cache_only=cache_only)
        except Exception as exc:
            result = {"ok": False, "emails": [], "count": 0, "error": str(exc), "account_id": acc_id}
        result["account_email"] = account.get("icloud_email") or account.get("real_email") or ""
        return result

    if refresh and len(accounts) > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(accounts))) as pool:
            details = list(pool.map(load, accounts))
    else:
        details = [load(account) for account in accounts]

    messages = []
    for detail in details:
        messages.extend(detail.get("emails") or [])
    messages.sort(key=_message_sort_timestamp, reverse=True)
    messages = messages[:limit]
    errors = [
        f"{detail.get('account_email') or detail.get('account_id')}: {detail.get('error')}"
        for detail in details if detail.get("error")
    ]
    return jsonify({
        "ok": bool(messages) or not errors,
        "emails": messages,
        "count": len(messages),
        "accounts": [{
            "account_id": detail.get("account_id", ""),
            "account_email": detail.get("account_email", ""),
            "count": detail.get("count", 0),
            "error": detail.get("error", ""),
            "cached": detail.get("cached", {}),
        } for detail in details],
        "errors": errors,
        "source": "all_refresh" if refresh else "all_cache",
        "refreshed": refresh,
    })


def _query_pickup_messages(acc_id, lookup_email):
    key = (str(acc_id or ""), str(lookup_email or "").strip().lower())

    def load():
        messages = _account_mgr.check_alias_mail(
            key[0], key[1], limit=2, days=30, force=True
        )
        messages = _fetch_missing_bodies(key[0], messages, max_bodies=2)
        return sorted(messages or [], key=_message_sort_timestamp, reverse=True)[:2]

    with _pickup_query_lock:
        future = _pickup_queries.get(key)
        if future is None:
            future = _pickup_executor.submit(load)
            _pickup_queries[key] = future
    try:
        return future.result()
    finally:
        if future.done():
            with _pickup_query_lock:
                if _pickup_queries.get(key) is future:
                    _pickup_queries.pop(key, None)


def _query_forward_pickup_messages(requested_email, lookup_email):
    requested = str(requested_email or "").strip().lower()
    lookup = str(lookup_email or "").strip().lower()
    # Forwarded mail preserves the original recipient, so tagged aliases must
    # match their full address. Falling back to the base alias would mix mail
    # from separate +tags that happen to share the same iCloud alias.
    targets = [requested or lookup]
    key = ("qq-forward", "|".join(targets))

    def load():
        result = check_forward_mail(targets, limit=100)
        if not result.get("ok"):
            raise RuntimeError(result.get("error") or "转发 IMAP 查询失败")
        return sorted(result.get("messages") or [], key=_message_sort_timestamp, reverse=True)[:2]

    with _pickup_query_lock:
        future = _pickup_queries.get(key)
        if future is None:
            future = _pickup_executor.submit(load)
            _pickup_queries[key] = future
    try:
        return future.result()
    finally:
        if future.done():
            with _pickup_query_lock:
                if _pickup_queries.get(key) is future:
                    _pickup_queries.pop(key, None)


def api_search_inboxes():
    alias = request.args.get("alias", "").strip().lower()
    lookup_alias = base_icloud_email_address(alias)
    limit = max(1, min(request.args.get("limit", 20, type=int), 50))
    if not alias:
        return jsonify({"ok": False, "emails": [], "count": 0, "error": "请输入隐私邮箱地址"})
    candidates = _mail_account_candidates(lookup_alias, "")
    errors = []
    for account in candidates:
        acc_id = account.get("id", "")
        try:
            messages = _run_imap_with_timeout(
                lambda acc_id=acc_id: _account_mgr.check_alias_mail(
                    acc_id, lookup_alias, limit=limit, days=30, force=True
                ),
                timeout=60,
            )
            messages = _fetch_missing_bodies(acc_id, messages, max_bodies=min(5, limit))
            messages = _tag_account_messages(acc_id, messages)
            if messages:
                inventory_email = base_icloud_email_address(alias)
                inventory_messages = _messages_for_inventory(messages, inventory_email)
                _sync_inventory_from_messages(inventory_messages, account_id=acc_id, method="iCloud 指定查件", seed_aliases=[inventory_email])
                return jsonify({
                    "ok": True,
                    "emails": messages,
                    "count": len(messages),
                    "alias": alias,
                    "lookup_alias": lookup_alias,
                    "account_id": acc_id,
                })
        except Exception as exc:
            errors.append(f"{account.get('icloud_email') or account.get('real_email') or acc_id}: {str(exc)[:160]}")
    if any(cfg.get("enabled") for cfg in load_forward_configs(redact=True)):
        try:
            messages = _run_imap_with_timeout(
                lambda: _query_forward_pickup_messages(alias, lookup_alias),
                timeout=60,
            )
            if messages:
                _sync_inventory_from_messages(
                    _messages_for_inventory(messages, lookup_alias),
                    method="转发 IMAP 指定查件",
                    seed_aliases=[lookup_alias],
                )
                return jsonify({
                    "ok": True,
                    "emails": messages[:limit],
                    "count": min(len(messages), limit),
                    "alias": alias,
                    "lookup_alias": lookup_alias,
                    "account_id": "",
                    "source": "qq_imap",
                })
        except Exception as exc:
            errors.append(f"转发 IMAP: {str(exc)[:160]}")
    return jsonify({
        "ok": False,
        "emails": [],
        "count": 0,
        "alias": alias,
        "error": "没有找到发给这个邮箱的邮件" + (("。" + "；".join(errors[:3])) if errors else ""),
    })

def api_inbox_stream(acc_id):
    limit = request.args.get("limit",50,type=int)
    days = request.args.get("days",7,type=int)
    def generate():
        yield f"data: {json.dumps({'type':'start'})}\n\n"
        try: mail = _account_mgr.get_mail_client(acc_id)
        except Exception as e: yield f"data: {json.dumps({'type':'error','error':str(e)[:200]})}\n\n"; return
        try:
            count = 0
            for msg in mail.stream_inbox(limit=limit, days=days):
                count += 1
                msg = _attach_cached_bodies(acc_id, [msg])[0]
                _sync_inventory_from_messages([msg], account_id=acc_id, method="iCloud 收件箱")
                yield f"data: {json.dumps({'type':'email','count':count,'email':msg},ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type':'done','count':count})}\n\n"
        except GeneratorExit: pass
        except Exception as e: yield f"data: {json.dumps({'type':'error','error':str(e)[:200]})}\n\n"
        finally:
            try: mail.disconnect()
            except: pass
    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

def api_message_body(acc_id, msg_id):
    try:
        cached = _account_mgr._cache.get_message(acc_id, msg_id)
        if cached:
            _sync_inventory_from_messages([cached], account_id=acc_id, method="iCloud 邮件正文")
            return jsonify({"ok":True,"message":cached,"cached":True})
        def _load_message():
            mail = _account_mgr.get_mail_client(acc_id)
            try:
                return mail.fetch_full(msg_id.encode() if isinstance(msg_id,str) else msg_id)
            finally:
                mail.disconnect()
        full = _run_imap_with_timeout(_load_message, timeout=30)
        if full:
            _account_mgr._cache.set_message(acc_id, msg_id, full)
            _sync_inventory_from_messages([full], account_id=acc_id, method="iCloud 邮件正文")
        return jsonify({"ok":True,"message":full})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})

def api_prefetch_messages(acc_id):
    data = request.get_json(silent=True) or {}
    ids = [str(x) for x in data.get("ids", []) if str(x).strip()][:30]
    if not ids:
        return jsonify({"ok":True,"prefetched":0})
    try:
        def _prefetch():
            messages = {}
            fetched = {}
            mail = _account_mgr.get_mail_client(acc_id)
            prefetched = 0
            try:
                for msg_id in ids:
                    cached = _account_mgr._cache.get_message(acc_id, msg_id)
                    if cached:
                        messages[msg_id] = cached
                        _sync_inventory_from_messages([cached], account_id=acc_id, method="iCloud 邮件正文")
                        continue
                    full = mail.fetch_full(msg_id.encode())
                    if full:
                        fetched[msg_id] = full
                        messages[msg_id] = full
                        prefetched += 1
                        _sync_inventory_from_messages([full], account_id=acc_id, method="iCloud 邮件正文")
            finally:
                try:
                    if fetched:
                        _account_mgr._cache.set_messages(acc_id, fetched)
                finally:
                    mail.disconnect()
            return prefetched, messages
        count, messages = _run_imap_with_timeout(_prefetch, timeout=45)
        return jsonify({"ok":True,"prefetched":count,"messages":messages})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})

def api_specific_alias_mail(acc_id, alias_email):
    requested_alias = str(alias_email or "").strip().lower()
    lookup_alias = base_icloud_email_address(requested_alias)
    limit = request.args.get("limit",20,type=int)
    days = request.args.get("days",30,type=int)
    force = request.args.get("force","0")=="1"
    try:
        msgs = _run_imap_with_timeout(lambda: _account_mgr.check_alias_mail(acc_id, lookup_alias, limit=limit, days=days, force=force))
        msgs = _fetch_missing_bodies(acc_id, msgs, max_bodies=min(5, max(1, limit)))
        inventory_email = lookup_alias
        inventory_msgs = _messages_for_inventory(msgs, inventory_email)
        _sync_inventory_from_messages(inventory_msgs, account_id=acc_id, method="iCloud 指定查件", seed_aliases=[inventory_email])
        stats = _account_mgr._cache.get_stats(acc_id)
        return jsonify({"emails":msgs,"count":len(msgs),"alias":requested_alias,"lookup_alias":lookup_alias,"cached":stats})
    except Exception as e: return jsonify({"emails":[],"count":0,"error":str(e)})

def get_public_pickup_result(email):
    email = str(email or "").strip().lower()
    if not _pickup_email_pattern.fullmatch(email):
        return {"ok": False, "error": "请填写正确的邮箱地址", "messages": [], "count": 0}, 400
    lookup_email = base_icloud_email_address(email)

    candidate_accounts = _mail_account_candidates(lookup_email, "")
    forward_enabled = any(cfg.get("enabled") for cfg in load_forward_configs(redact=True))
    if not candidate_accounts and not forward_enabled:
        return {
            "ok": False,
            "error": "当前没有可读取邮件的 iCloud 或转发 IMAP 账号",
            "email": email,
            "messages": [],
            "count": 0,
        }, 503
    cached_messages = []
    for account in candidate_accounts:
        acc_id = account.get("id", "")
        if not acc_id:
            continue
        messages = _cached_pickup_messages(acc_id, lookup_email)
        if messages:
            cached_messages = _fetch_missing_bodies(acc_id, messages[:2], max_bodies=0)
            break
    errors = []
    for account in candidate_accounts:
        acc_id = account.get("id", "")
        if not acc_id:
            continue
        try:
            messages = _query_pickup_messages(acc_id, lookup_email)
            if not messages:
                continue
            inventory_email = lookup_email
            inventory_messages = _messages_for_inventory(messages, inventory_email)
            _sync_inventory_from_messages(
                inventory_messages,
                account_id=acc_id,
                method="邮箱取码",
                seed_aliases=[inventory_email],
            )
            return _pickup_response(email, messages, "imap", refreshed=True), 200
        except Exception as exc:
            errors.append(str(exc))

    if forward_enabled:
        try:
            messages = _run_imap_with_timeout(
                lambda: _query_forward_pickup_messages(email, lookup_email),
                timeout=60,
            )
            if messages:
                _sync_inventory_from_messages(
                    _messages_for_inventory(messages, lookup_email),
                    method="转发 IMAP 取码",
                    seed_aliases=[lookup_email],
                )
                return _pickup_response(email, messages, "qq_imap", refreshed=True), 200
        except Exception as exc:
            errors.append(str(exc))

    if cached_messages:
        result = _pickup_response(email, cached_messages, "cache_fallback", refreshed=True)
        result["warning"] = "实时刷新失败，当前显示缓存邮件"
        return result, 200
    return {
        "ok": False,
        "error": "没有找到发给这个邮箱的邮件" if not errors else "暂时无法查询邮件，请稍后重试",
        "email": email,
        "messages": [],
        "count": 0,
    }, 404 if not errors else 503


def api_public_latest_code(mailbox_id, token):
    record = resolve_pickup_link(mailbox_id, token)
    if not record:
        return jsonify({
            "ok": False,
            "status": "unauthorized",
            "error": "无权限",
            "mailbox_id": str(mailbox_id or ""),
            "code": "",
        }), 403
    result, status = get_public_pickup_result(record["email"])
    if status == 404:
        result = {
            "ok": True,
            "email": record["email"],
            "messages": [],
            "checked_at": _pickup_utc_now(),
        }
        payload = _latest_six_digit_code_payload(mailbox_id, result)
        stored = _stored_pickup_code_payload(mailbox_id, record["email"])
        return jsonify(stored or payload), 200
    if status != 200 or not result.get("ok"):
        stored = _stored_pickup_code_payload(
            mailbox_id,
            record["email"],
            status="retry",
        )
        payload = stored or {
            "ok": False,
            "status": "retry",
            "error": result.get("error") or "接口异常，请重试",
            "mailbox_id": str(mailbox_id or ""),
            "email": record["email"],
            "code": "",
            "checked_at": _pickup_utc_now(),
        }
        payload["error"] = result.get("error") or "接口异常，请重试"
        return jsonify(payload), status
    payload = _latest_six_digit_code_payload(mailbox_id, result)
    if payload.get("code"):
        payload = _remember_pickup_code_payload(mailbox_id, payload)
    else:
        payload = _stored_pickup_code_payload(mailbox_id, record["email"]) or payload
    return jsonify(payload), 200

def api_mail_by_email():
    email = request.args.get("email","").strip().lower()
    alias = request.args.get("alias","").strip().lower()
    limit = request.args.get("limit",20,type=int)
    days = request.args.get("days",30,type=int)
    force = request.args.get("force","0")=="1"
    if not email: return jsonify({"error":"请提供 email 参数"})
    acc_id = None
    for a in _account_mgr.list_accounts():
        if a.get("icloud_email","").lower()==email or a.get("real_email","").lower()==email: acc_id=a["id"]; break
    if not acc_id: return jsonify({"error":f"未找到邮箱对应的账号: {email}"})
    try:
        if alias:
            lookup_alias = base_icloud_email_address(alias)
            msgs = _run_imap_with_timeout(lambda: _account_mgr.check_alias_mail(acc_id, lookup_alias, limit=limit, days=days, force=force))
            msgs = _fetch_missing_bodies(acc_id, msgs, max_bodies=min(5, max(1, limit)))
            inventory_msgs = _messages_for_inventory(msgs, lookup_alias)
            _sync_inventory_from_messages(inventory_msgs, account_id=acc_id, method="iCloud 指定查件", seed_aliases=[lookup_alias])
            return jsonify({"emails":msgs,"count":len(msgs),"alias":alias,"lookup_alias":lookup_alias,"account":email})
        else:
            by_alias = _run_imap_with_timeout(lambda: _account_mgr.check_all_aliases_mail(acc_id, limit_per=limit, days=days, force=force))
            by_alias = _attach_cached_bodies_by_alias(acc_id, by_alias)
            inventory_msgs = []
            seed_aliases = []
            for alias_email, alias_msgs in by_alias.items():
                seed_aliases.append(alias_email)
                inventory_msgs.extend(_messages_for_inventory(alias_msgs, alias_email))
            _sync_inventory_from_messages(inventory_msgs, account_id=acc_id, method="iCloud 全部查件", seed_aliases=seed_aliases)
            total = sum(len(v) for v in by_alias.values())
            return jsonify({"by_alias":by_alias,"total":total,"account":email})
    except Exception as e: return jsonify({"error":str(e)})

def api_alias_mail(acc_id):
    force = request.args.get("force","0")=="1"
    limit = max(1, min(request.args.get("limit",20,type=int), 50))
    max_aliases = max(0, min(request.args.get("max_aliases",0,type=int), 500))
    mail_limit = max(1, min(request.args.get("mail_limit",100,type=int), 500))
    try:
        by_alias = _run_imap_with_timeout(
            lambda: _account_mgr.check_all_aliases_mail(
                acc_id,
                limit_per=limit,
                force=force,
                max_aliases=max_aliases,
                mail_limit=mail_limit,
            )
        )
        by_alias = _attach_cached_bodies_by_alias(acc_id, by_alias)
        inventory_msgs = []
        seed_aliases = []
        for alias_email, alias_msgs in by_alias.items():
            seed_aliases.append(alias_email)
            inventory_msgs.extend(_messages_for_inventory(alias_msgs, alias_email))
        _sync_inventory_from_messages(inventory_msgs, account_id=acc_id, method="iCloud 全部查件", seed_aliases=seed_aliases)
        total = sum(len(v) for v in by_alias.values())
        stats = _account_mgr._cache.get_stats(acc_id)
        return jsonify({"by_alias":by_alias,"total":total,"cached":stats})
    except Exception as e: return jsonify({"by_alias":{},"total":0,"error":str(e)})
