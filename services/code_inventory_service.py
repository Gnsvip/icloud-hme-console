from app_core import *
from inventory_manager import base_icloud_email_address
from services.status_model import CodeStatus, inventory_group_to_mailbox_status

ALIAS_SYNC_TIMEOUT_SECONDS = 25


def _code_status_for_item(item):
    group = item.get("group") or "unused"
    if group == "trash":
        return CodeStatus.TRASH.value
    if group == "finished" or item.get("code") or item.get("last_received_at"):
        return CodeStatus.USED.value
    if item.get("last_checked_at") or item.get("status_message"):
        return CodeStatus.UNUSED_CHECKED.value
    return CodeStatus.UNCALIBRATED.value


def _attach_status_model(rows):
    out = []
    for item in rows or []:
        row = dict(item)
        checked = bool(row.get("last_checked_at") or row.get("last_received_at") or row.get("status_message"))
        row["mailbox_status"] = inventory_group_to_mailbox_status(row.get("group") or "unused", checked=checked)
        row["code_status"] = _code_status_for_item(row)
        out.append(row)
    return out


def _attach_pickup_link_status(rows):
    from services.mail_service import active_pickup_link_statuses

    statuses = active_pickup_link_statuses()
    inventory_rows, _summary = _inventory.list_items(group="all")
    lifecycle_by_email = {
        str(item.get("email") or "").strip().lower(): item
        for item in inventory_rows
        if isinstance(item, dict) and item.get("email")
    }
    lifecycle_fields = (
        "lifecycle_status",
        "lifecycle_reason",
        "deactivated_at",
        "deactivation_alias",
        "deactivation_subject",
        "deactivation_sender",
        "deactivation_message_id",
        "deactivation_message_date",
        "deactivation_source",
    )
    out = []
    for item in rows or []:
        row = dict(item)
        lifecycle = lifecycle_by_email.get(str(row.get("email") or "").strip().lower())
        if lifecycle:
            for field in lifecycle_fields:
                row[field] = lifecycle.get(field, row.get(field, ""))
        base_email = base_icloud_email_address(row.get("email", ""))
        status = statuses.get(base_email)
        if status:
            row.update(status)
        else:
            row.update({
                "has_pickup_link": False,
                "pickup_link_count": 0,
                "pickup_link_emails": [],
                "pickup_link_created_at": "",
            })
        out.append(row)
    return out


def _attach_item_status(item):
    return _attach_status_model([item])[0] if item else item


def _attach_pickup_query(rows, query):
    requested = str(query or "").strip().lower()
    base_email = base_icloud_email_address(requested)
    if not requested or base_email == requested:
        return rows
    out = []
    for item in rows or []:
        row = dict(item)
        if str(row.get("email") or "").strip().lower() == base_email:
            row["pickup_email"] = requested
        out.append(row)
    return out


def _account_alias_label(account):
    return str(
        account.get("icloud_email")
        or account.get("real_email")
        or account.get("name")
        or account.get("id")
        or "未知账号"
    )


def _fetch_account_aliases(account):
    account_id = str(account.get("id") or "")
    client = _account_mgr.get_client(account_id, verbose=False)
    aliases = client.list_aliases(timeout=12, max_attempts=1)
    rows = []
    for alias in aliases or []:
        row = dict(alias)
        row["account_id"] = account_id
        row["account_name"] = account.get("name", "")
        row["account_email"] = account.get("real_email", "")
        row["icloud_email"] = account.get("icloud_email", "")
        rows.append(row)
    return rows


def _replace_account_alias_cache(fetched_by_account):
    replaced_ids = set(fetched_by_account)
    cached = [
        row for row in _read_alias_cache().get("aliases", [])
        if isinstance(row, dict) and str(row.get("account_id") or "") not in replaced_ids
    ]
    for rows in fetched_by_account.values():
        cached.extend(rows)
    _write_alias_cache(cached)
    return cached

def api_aliases():
    account_id = str(request.args.get("account_id") or "").strip()
    accounts = [a for a in _account_mgr.list_accounts() if a.get("id")]
    by_id = {str(account.get("id")): account for account in accounts}
    if account_id and account_id not in by_id:
        return jsonify({"ok": False, "aliases": [], "count": 0, "error": "账号不存在"}), 404
    targets = [by_id[account_id]] if account_id else accounts
    if not targets:
        return jsonify({"ok": True, "aliases": [], "count": 0, "synced_count": 0, "errors": []})

    fetched = {}
    errors = []
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(targets)))
    futures = {pool.submit(_fetch_account_aliases, account): account for account in targets}
    done, pending = concurrent.futures.wait(
        futures,
        timeout=ALIAS_SYNC_TIMEOUT_SECONDS,
    )
    for future in done:
        account = futures[future]
        try:
            fetched[str(account.get("id"))] = future.result()
        except Exception as exc:
            errors.append({
                "account_id": str(account.get("id") or ""),
                "account": _account_alias_label(account),
                "error": str(exc)[:180],
            })
    for future in pending:
        account = futures[future]
        future.cancel()
        errors.append({
            "account_id": str(account.get("id") or ""),
            "account": _account_alias_label(account),
            "error": f"同步超时 ({ALIAS_SYNC_TIMEOUT_SECONDS}s)",
        })
    pool.shutdown(wait=False, cancel_futures=True)

    cached = _replace_account_alias_cache(fetched) if fetched else _read_alias_cache().get("aliases", [])
    active_ids = _active_account_ids()
    aliases = [
        row for row in cached
        if isinstance(row, dict) and str(row.get("account_id") or "") in active_ids
    ]
    if fetched:
        changed_rows = [row for rows in fetched.values() for row in rows]
        _sync_inventory_from_known(changed_rows)
    aliases = _attach_pickup_link_status(aliases)
    synced_count = sum(len(rows) for rows in fetched.values())
    if not fetched and errors:
        detail = "；".join(f"{item['account']}: {item['error']}" for item in errors)
        return jsonify({
            "ok": False,
            "aliases": aliases,
            "count": len(aliases),
            "synced_count": 0,
            "errors": errors,
            "error": detail or "云端同步失败",
            "account_id": account_id,
        })
    return jsonify({
        "ok": True,
        "aliases": aliases,
        "count": len(aliases),
        "synced_count": synced_count,
        "synced_accounts": list(fetched),
        "errors": errors,
        "partial": bool(errors),
        "account_id": account_id,
    })

def api_aliases_cache():
    active_ids = _active_account_ids()
    if not active_ids:
        return jsonify({"aliases": [], "count": 0})
    aliases = [
        a for a in _read_alias_cache().get("aliases", [])
        if isinstance(a, dict) and str(a.get("account_id") or "") in active_ids
    ]
    aliases = _attach_pickup_link_status(aliases)
    return jsonify({"aliases": aliases, "count": len(aliases)})

def api_emails():
    limit = request.args.get("limit",0,type=int)
    active_ids = _active_account_ids()
    if not active_ids:
        return jsonify({"emails": [], "count": 0, "source": "active"})
    emails = _read_inventory_email_rows(limit=limit, account_ids=active_ids)
    if not emails:
        local_rows = _read_local_email_rows(limit=0)
        emails = [e for e in local_rows if str(e.get("account_id") or "") in active_ids]
        if limit > 0:
            emails = emails[:limit]
        _inventory.sync_aliases(emails)
    emails = _attach_pickup_link_status(_attach_status_model(emails))
    return jsonify({"emails": emails, "count": len(emails), "source": "active"})

def api_inventory():
    group = request.args.get("group", "all")
    query = request.args.get("q", "")
    lookup_query = base_icloud_email_address(query)
    account_id = request.args.get("account_id", "")
    try:
        active_ids = _active_account_ids()
        if account_id and account_id not in active_ids:
            return jsonify({"ok": True, "items": [], "summary": _inventory_summary_from_items([]), "count": 0})
        if not account_id and not active_ids:
            return jsonify({"ok": True, "items": [], "summary": _inventory_summary_from_items([]), "count": 0})
        aliases = [
            a for a in _read_alias_cache().get("aliases", [])
            if isinstance(a, dict) and str(a.get("account_id") or "") in active_ids
        ]
        _sync_inventory_from_known(aliases)
        _sync_inventory_from_mail_cache()
        items, summary = _inventory.list_items(group=group, query=lookup_query, account_id=account_id)
        if not account_id:
            items = [i for i in items if str(i.get("account_id") or "") in active_ids]
        summary = _inventory_summary_from_items(items)
        count = len(items)
        page_size = max(1, min(request.args.get("page_size", 50, type=int), 200))
        pages = max(1, (count + page_size - 1) // page_size)
        page = max(1, min(request.args.get("page", 1, type=int), pages))
        if "page" in request.args or "page_size" in request.args:
            items = items[(page - 1) * page_size:page * page_size]
        items = _attach_status_model(items)
        items = _attach_pickup_query(items, query)
        return jsonify({"ok": True, "items": items, "summary": summary, "count": count,
                        "page": page, "page_size": page_size, "pages": pages})
    except Exception as e:
        return jsonify({"ok": False, "items": [], "summary": {}, "error": str(e)})

def api_inventory_sync():
    live = bool((request.get_json(silent=True) or {}).get("live"))
    try:
        active_ids = _active_account_ids()
        if not active_ids:
            return jsonify({"ok": True, "items": [], "summary": _inventory_summary_from_items([]), "changed": 0})
        aliases = _account_mgr.get_all_aliases() if live else _read_alias_cache().get("aliases", [])
        aliases = [a for a in aliases if isinstance(a, dict) and str(a.get("account_id") or "") in active_ids]
        if live:
            _write_alias_cache(aliases)
        result = _sync_inventory_from_known(aliases)
        _sync_inventory_from_mail_cache(force=True)
        items, summary = _inventory.list_items(group="all")
        items = [i for i in items if str(i.get("account_id") or "") in active_ids]
        summary = _inventory_summary_from_items(items)
        items = _attach_status_model(items)
        return jsonify({"ok": True, "items": items, "summary": summary, "changed": result.get("changed", 0)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_move(email_addr):
    data = request.get_json(silent=True) or {}
    try:
        item = _inventory.move(email_addr, data.get("group", "unused"))
        return jsonify({"ok": True, "item": _attach_item_status(item)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_remark(email_addr):
    data = request.get_json(silent=True) or {}
    try:
        item = _inventory.update_item(email_addr, remark=(data.get("remark") or "").strip())
        return jsonify({"ok": True, "item": _attach_item_status(item)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_mark_read(email_addr):
    try:
        return jsonify({"ok": True, "item": _attach_item_status(_inventory.mark_read(email_addr))})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_trash(email_addr):
    try:
        item = _inventory.move(email_addr, "trash")
        return jsonify({"ok": True, "item": _attach_item_status(item)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_purge(email_addr):
    try:
        return jsonify({"ok": _inventory.purge(email_addr)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_export():
    group = request.args.get("group", "all")
    active_ids = _active_account_ids()
    rows, _summary = _inventory.list_items(group=group)
    rows = [r for r in rows if str(r.get("account_id") or "") in active_ids]
    headers = ["email", "group", "code", "label", "remark", "account_name", "account_email", "last_subject", "last_seen_at"]
    csv_lines = [",".join(headers)]
    for row in rows:
        values = []
        for key in headers:
            val = str(row.get(key, "") or "").replace('"', '""')
            values.append(f'"{val}"' if any(c in val for c in ',\n"') else val)
        csv_lines.append(",".join(values))
    csv_text = "\n".join(csv_lines)
    return Response(
        "\ufeff" + csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=inventory_{group}.csv"},
    )

def api_inventory_check_icloud():
    data = request.get_json(silent=True) or {}
    if data.get("calibrate") or data.get("cloud_calibrate"):
        return _api_inventory_calibrate_cloud_impl(data)
    acc_id = (data.get("account_id") or "").strip()
    limit = max(1, min(int(data.get("limit") or 30), 500))
    force = bool(data.get("force", True))
    accounts = [_account_mgr.get_account(acc_id)] if acc_id else _account_mgr.list_accounts()
    checked = 0
    deactivated = 0
    errors = []
    try:
        active_ids = _active_account_ids()
        if acc_id and acc_id not in active_ids:
            return jsonify({"ok": True, "updated": 0, "errors": [], "items": [], "summary": _inventory_summary_from_items([])})
        if not acc_id and not active_ids:
            return jsonify({"ok": True, "updated": 0, "errors": [], "items": [], "summary": _inventory_summary_from_items([])})
        _sync_inventory_from_known()
        for acc in accounts:
            if not acc:
                continue
            if not acc.get("app_password") or not (acc.get("icloud_email") or "icloud.com" in acc.get("real_email", "")):
                continue
            try:
                msgs = _run_imap_with_timeout(lambda acc_id=acc["id"]: _account_mgr.check_inbox(acc_id, limit=limit, force=force), timeout=45)
                if force:
                    msgs = _fetch_missing_bodies(acc["id"], msgs, max_bodies=min(20, max(1, limit)))
                else:
                    msgs = _attach_cached_bodies(acc["id"], msgs)
                result = _inventory.apply_messages(msgs, account_id=acc["id"], method="iCloud IMAP")
                checked += result.get("count", 0)
                deactivated += result.get("deactivated", 0)
            except Exception as e:
                errors.append(f"{acc.get('name') or acc.get('real_email') or acc.get('id')}: {str(e)[:120]}")
        items, summary = _inventory.list_items(group="all")
        items = [i for i in items if str(i.get("account_id") or "") in active_ids]
        summary = _inventory_summary_from_items(items)
        items = _attach_status_model(items)
        return jsonify({
            "ok": not errors or checked > 0,
            "updated": checked,
            "deactivated": deactivated,
            "errors": errors,
            "items": items,
            "summary": summary,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_calibrate_cloud():
    data = request.get_json(silent=True) or {}
    return _api_inventory_calibrate_cloud_impl(data)

def _api_inventory_calibrate_cloud_impl(data):
    acc_id = (data.get("account_id") or "").strip()
    days = max(1, min(int(data.get("days") or 365), 3650))
    limit = max(0, min(int(data.get("limit") or 1500), 10000))
    fetch_bodies = max(0, min(int(data.get("fetch_bodies") or 80), 300))
    all_mailboxes = bool(data.get("all_mailboxes", True))
    limit_per_alias = max(1, min(int(data.get("limit_per_alias") or 10), 50))
    try:
        active_ids = _active_account_ids()
        if acc_id and acc_id not in active_ids:
            return jsonify({"ok": False, "error": "账号不存在或已退出"})
        if not acc_id and not active_ids:
            return jsonify({"ok": False, "error": "没有可校准的账号，请先添加账号"})
        _sync_inventory_from_known()
        all_rows, _ = _inventory.list_items(group="all")
        all_rows = [r for r in all_rows if str(r.get("account_id") or "") in active_ids]
        accounts = [_account_mgr.get_account(acc_id)] if acc_id else _account_mgr.list_accounts()
        accounts = [a for a in accounts if a]
        usable_accounts = [
            a for a in accounts
            if a.get("app_password") and (a.get("icloud_email") or "icloud.com" in a.get("real_email", ""))
        ]
        if not usable_accounts:
            return jsonify({"ok": False, "error": "没有可校准的账号，请先设置 iCloud 邮箱和 App 专用密码"})
        only_id = usable_accounts[0]["id"] if len(usable_accounts) == 1 else ""
        aliases_by_account = {a["id"]: set() for a in usable_accounts}
        for row in all_rows:
            email_addr = str(row.get("email") or "").strip().lower()
            if not email_addr or row.get("group") == "trash":
                continue
            row_acc = str(row.get("account_id") or "").strip()
            if acc_id and row_acc and row_acc != acc_id:
                continue
            target_acc = row_acc or acc_id or only_id
            if target_acc in aliases_by_account:
                aliases_by_account[target_acc].add(email_addr)
        scanned = matched = body_fetched = updated = matched_aliases = 0
        details = []
        errors = []
        for acc in usable_accounts:
            alias_list = sorted(aliases_by_account.get(acc["id"], set()))
            if not alias_list:
                details.append({"account_id": acc["id"], "aliases": 0, "scanned": 0, "matched_aliases": 0})
                continue
            try:
                result = _run_imap_with_timeout(
                    lambda acc=acc, alias_list=alias_list: _account_mgr.calibrate_alias_usage(
                        acc["id"],
                        alias_list,
                        limit=limit,
                        days=days,
                        all_mailboxes=all_mailboxes,
                        limit_per_alias=limit_per_alias,
                        fetch_bodies=fetch_bodies,
                    ),
                    timeout=240,
                )
                by_alias = result.get("by_alias") or {}
                inventory_msgs = []
                for alias_email, alias_msgs in by_alias.items():
                    inventory_msgs.extend(_messages_for_inventory(alias_msgs, alias_email))
                applied = _apply_inventory_messages(
                    inventory_msgs,
                    account_id=acc["id"],
                    method="云端校准",
                    seed_aliases=by_alias.keys(),
                )
                scanned += int(result.get("scanned") or 0)
                matched += int(result.get("matched") or 0)
                body_fetched += int(result.get("body_fetched") or 0)
                updated += int(applied.get("count") or 0)
                matched_aliases += len(by_alias)
                details.append({
                    "account_id": acc["id"],
                    "account": acc.get("icloud_email") or acc.get("real_email") or acc.get("name") or acc["id"],
                    "aliases": len(alias_list),
                    "scanned": int(result.get("scanned") or 0),
                    "matched": int(result.get("matched") or 0),
                    "matched_aliases": len(by_alias),
                    "body_fetched": int(result.get("body_fetched") or 0),
                    "mailboxes": result.get("mailboxes") or [],
                })
            except Exception as e:
                errors.append(f"{acc.get('icloud_email') or acc.get('real_email') or acc.get('id')}: {str(e)[:160]}")
        items, summary = _inventory.list_items(group="all")
        items = [i for i in items if str(i.get("account_id") or "") in active_ids]
        summary = _inventory_summary_from_items(items)
        items = _attach_status_model(items)
        return jsonify({
            "ok": not errors or matched_aliases > 0,
            "scanned": scanned,
            "matched": matched,
            "matched_aliases": matched_aliases,
            "body_fetched": body_fetched,
            "updated": updated,
            "details": details,
            "errors": errors,
            "items": items,
            "summary": summary,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_inventory_check_forward():
    data = request.get_json(silent=True) or {}
    limit = min(int(data.get("limit") or 100), 300)
    try:
        active_ids = _active_account_ids()
        if not active_ids:
            return jsonify({"ok": True, "updated": 0, "mail_count": 0, "items": [], "summary": _inventory_summary_from_items([])})
        targets_by_account = {account_id: _inventory_target_emails([account_id]) for account_id in active_ids}
        targets_by_account[""] = _inventory_target_emails(active_ids)
        result = _run_imap_with_timeout(lambda: check_forward_mail(targets_by_account, limit=limit), timeout=90)
        if not result.get("ok"):
            return jsonify(result)
        applied = _inventory.apply_messages(result.get("messages", []), method="转发邮箱")
        items, summary = _inventory.list_items(group="all")
        items = [i for i in items if str(i.get("account_id") or "") in active_ids]
        summary = _inventory_summary_from_items(items)
        items = _attach_status_model(items)
        return jsonify({"ok": True, "updated": applied.get("count", 0), "deactivated": applied.get("deactivated", 0), "mail_count": result.get("count", 0), "items": items, "summary": summary})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

def api_forward_config():
    if request.method == "GET":
        return jsonify({"ok": True, "configs": load_forward_configs(redact=True)})
    try:
        data = request.get_json(silent=True) or {}
        cfg = save_forward_config(data)
        if data.get("test") and cfg.get("enabled"):
            try:
                test_result = _run_imap_with_timeout(
                    lambda: test_forward_mail_connection(profile_id=str(cfg.get("id") or "")),
                    timeout=45,
                )
            except Exception as exc:
                test_result = {"ok": False, "error": str(exc)}
            if not test_result.get("ok"):
                _emit_log("warn", f"转发 IMAP 连接失败: {test_result.get('error') or '未知错误'}")
                return jsonify({"ok": False, "saved": True, "config": cfg, "error": test_result.get("error") or "转发 IMAP 连接失败"})
            _emit_log("success", f"转发 IMAP 已连接: {test_result.get('username')} / {test_result.get('message_count', 0)} 封")
            return jsonify({"ok": True, "saved": True, "config": cfg, "test": test_result})
        return jsonify({"ok": True, "saved": True, "config": cfg})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


def api_forward_config_delete(profile_id):
    if delete_forward_config(profile_id):
        _emit_log("info", f"已删除转发 IMAP 配置: {profile_id}")
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "配置不存在"}), 404


def api_forward_microsoft_start(profile_id):
    try:
        return jsonify(start_microsoft_device_auth(profile_id))
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})


def api_forward_microsoft_poll(profile_id):
    try:
        data = request.get_json(silent=True) or {}
        result = poll_microsoft_device_auth(profile_id, str(data.get("device_code") or ""))
        if result.get("authorized"):
            _emit_log("success", f"Microsoft IMAP OAuth2 授权成功: {profile_id}")
        return jsonify(result)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)})
