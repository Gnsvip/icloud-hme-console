import io
import time
import zipfile

from flask import Blueprint, Response, jsonify, render_template, request, send_file

from app_core import *

bp = Blueprint("accounts", __name__)


@bp.route("/api/accounts/<acc_id>/benefits")
def api_account_benefits(acc_id):
    from services.account_benefits_service import BenefitsError, read_benefits
    try:
        return jsonify(read_benefits(_account_mgr, acc_id))
    except BenefitsError as exc:
        return jsonify(ok=False, error=str(exc)), exc.status


def _record_batch_delete(acc_id, result):
    email = result["email"]
    _account_mgr._remove_local_email(email)
    _remove_alias_cache(email=email)
    if email not in _inventory.load().get("purged_emails", {}):
        _inventory.update_item(email, group="trash", active=False,
                               deleted_at=datetime.now().isoformat(timespec="seconds"),
                               status_type="warn", status_message="云端已无该别名" if result["already_absent"] else "已从 iCloud 删除")


from services.alias_delete_service import AliasDeleteJobs, DeleteJobError
_delete_jobs = AliasDeleteJobs(_account_mgr, _record_batch_delete)


@bp.route("/api/alias-deletions", methods=["POST"])
def api_start_alias_deletion():
    try:
        return jsonify(_delete_jobs.start(request.get_json(silent=True))), 202
    except DeleteJobError as exc:
        return jsonify(ok=False, error=str(exc)), exc.status


@bp.route("/api/alias-deletions/active")
def api_active_alias_deletion():
    return jsonify(_delete_jobs.active())


@bp.route("/api/alias-deletions/<job_id>")
def api_alias_deletion_status(job_id):
    try:
        return jsonify(_delete_jobs.status(job_id))
    except DeleteJobError as exc:
        return jsonify(ok=False, error=str(exc)), exc.status


def _asset_version():
    static_dir = HERE / "static"
    mtimes = []
    for rel in ("css/admin.css", "js/admin.js", "js/inbox.js", "js/code_desk.js"):
        try:
            mtimes.append((static_dir / rel).stat().st_mtime)
        except OSError:
            pass
    return str(int(max(mtimes) if mtimes else time.time()))


@bp.route("/")
@bp.route("/index.html")
@bp.route("/admin")
@bp.route("/admin/")
def index():
    shell = HERE / "static/admin-v2/index.html"
    if shell.is_file():
        return send_file(shell)
    return render_template("admin.html", asset_version=_asset_version())


@bp.route("/api/admin/login", methods=["POST"])
def api_admin_login():
    data = request.get_json(silent=True) or request.form or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    if username != ADMIN_USER or not secrets.compare_digest(password, ADMIN_PASSWORD):
        return jsonify({"ok": False, "error": "账号或密码错误"}), 401
    resp = jsonify({"ok": True})
    resp.set_cookie(
        ADMIN_SESSION_COOKIE,
        _admin_token(),
        max_age=86400 * 30,
        httponly=True,
        samesite="Lax",
        secure=(request.headers.get("X-Forwarded-Proto", "").lower() == "https"),
    )
    return resp


@bp.route("/api/admin/logout", methods=["POST", "GET"])
def api_admin_logout():
    resp = jsonify({"ok": True})
    resp.delete_cookie(ADMIN_SESSION_COOKIE)
    return resp


@bp.route("/logout")
def admin_logout_page():
    resp = Response("", status=302)
    resp.headers["Location"] = "/admin/"
    resp.delete_cookie(ADMIN_SESSION_COOKIE)
    return resp


@bp.route("/api/admin/session")
def api_admin_session():
    return jsonify({"ok": _is_admin_authed(), "user": "admin" if _is_admin_authed() else None})


@bp.route("/api/state")
def api_state():
    summary = _account_mgr.get_summary()
    with _lock:
        state = dict(_global_state); state.update(summary)
        state["cookies_ok"] = summary["active_accounts"] > 0
        state["alias_count"] = summary["total_aliases"]
        state["alias_active"] = summary["total_active_aliases"]
    return jsonify(state)


@bp.route("/api/accounts")
def api_accounts():
    accounts = _account_mgr.list_accounts()
    safe = []
    for a in accounts:
        ac = {k:v for k,v in a.items() if k not in ("cookies", "app_password")}
        ac["has_cookies"] = bool(a.get("cookies"))
        ac["has_app_password"] = bool(a.get("app_password"))
        ac["app_password"] = a.get("app_password","")
        safe.append(ac)
    return jsonify({"accounts":safe,"count":len(safe)})


@bp.route("/api/accounts/add", methods=["POST"])
def api_add_account():
    data = request.get_json() or {}
    name = data.get("name","未命名账号")
    cookie_input = data.get("cookie_input","")
    host = data.get("host","icloud.com")
    icloud_email = (data.get("icloud_email") or "").strip()
    app_password = (data.get("app_password") or "").strip()
    if host not in ("icloud.com", "icloud.com.cn"):
        host = "icloud.com"
    if not cookie_input: return jsonify({"ok":False,"error":"请提供 cookie_input"})
    if icloud_email and not _is_icloud_mail_address(icloud_email):
        return jsonify({
            "ok": False,
            "error": f"iCloud 邮箱不能填 {icloud_email}。Apple ID 可以是这个地址，但 IMAP 收件必须填写 @icloud.com / @me.com / @mac.com 邮箱；不知道就先留空。"
        })
    try:
        _emit_log("info", f"开始校验 iCloud Cookie: {name} ({host})")
        future = _account_executor.submit(_account_mgr.add_account, name, cookie_input, host)
        account = future.result(timeout=75)
        imap_result = None
        if icloud_email:
            account = _account_mgr.update_account(account["id"], icloud_email=icloud_email) or account
        if app_password:
            _account_mgr.set_app_password(account["id"], app_password)
            if icloud_email:
                account = _account_mgr.update_account(account["id"], icloud_email=icloud_email) or account
            try:
                imap_result = _run_imap_with_timeout(lambda: _account_mgr.test_imap_connection(account["id"]), timeout=30)
                if imap_result.get("ok"):
                    account = _account_mgr.update_account(account["id"], last_mail_error=None) or account
                else:
                    account = _account_mgr.update_account(account["id"], last_mail_error=imap_result.get("error", "IMAP 测试失败")) or account
            except Exception as e:
                imap_result = {"ok": False, "error": str(e)}
                account = _account_mgr.update_account(account["id"], last_mail_error=str(e)) or account
        _emit_log("info",f"添加账号: {account.get('name','')} ({account.get('real_email','?')})")
        return jsonify({
            "ok": True,
            "id": account["id"],
            "name": account["name"],
            "real_email": account.get("real_email",""),
            "icloud_email": account.get("icloud_email",""),
            "alias_total": account.get("alias_total",0),
            "alias_active": account.get("alias_active",0),
            "status": account.get("status",""),
            "host": account.get("host",""),
            "last_error": account.get("last_error",""),
            "has_app_password": bool(account.get("app_password")),
            "app_password": account.get("app_password",""),
            "imap_ok": None if imap_result is None else bool(imap_result.get("ok")),
            "imap_error": "" if not imap_result else imap_result.get("error", ""),
            "inbox_count": 0 if not imap_result else imap_result.get("inbox_count", 0),
        })
    except concurrent.futures.TimeoutError:
        _emit_log("warn", f"添加账号超时: {name} ({host})")
        return jsonify({"ok":False,"error":"iCloud 校验超时。请确认 Cookie 是刚登录后生成的，并且地区选择正确；稍后可重试。"}), 504
    except ValueError as e: return jsonify({"ok":False,"error":str(e)})
    except Exception as e: return jsonify({"ok":False,"error":str(e)})


@bp.route("/api/cookie-helper/download")
def api_cookie_helper_download():
    if not COOKIE_HELPER_DIR.exists():
        return jsonify({"ok": False, "error": "Cookie 助手文件不存在"}), 404

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        root_name = "icloud-hme-cookie-helper"
        for path in sorted(COOKIE_HELPER_DIR.rglob("*")):
            if path.is_file():
                rel = path.relative_to(COOKIE_HELPER_DIR).as_posix()
                zf.write(path, f"{root_name}/{rel}")
    resp = Response(buf.getvalue(), mimetype="application/zip")
    resp.headers["Content-Disposition"] = 'attachment; filename="icloud-hme-cookie-helper.zip"'
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return resp


@bp.route("/api/cookie-helper/import", methods=["POST", "OPTIONS"])
def api_cookie_helper_import():
    if request.method == "OPTIONS":
        return Response("", status=204)
    if not _cookie_helper_authorized():
        return jsonify({"ok": False, "error": "Cookie 助手未授权，请从后台重新下载最新助手"}), 401
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or data.get("account_name") or "Cookie 助手导入").strip()
    cookie_input = data.get("cookie_input") or data.get("cookie_header") or ""
    host = (data.get("host") or "icloud.com.cn").strip()
    if host not in ("icloud.com", "icloud.com.cn"):
        host = "icloud.com.cn"
    if not cookie_input:
        return jsonify({"ok": False, "error": "没有收到 iCloud Cookie"})
    try:
        future = _account_executor.submit(_account_mgr.add_account, name, cookie_input, host)
        account = future.result(timeout=75)
        _emit_log("info", f"Cookie 助手导入账号: {account.get('name','')} ({account.get('real_email','?')})")
        return jsonify({
            "ok": True,
            "id": account["id"],
            "name": account.get("name", ""),
            "real_email": account.get("real_email", ""),
            "icloud_email": account.get("icloud_email", ""),
            "alias_total": account.get("alias_total", 0),
            "alias_active": account.get("alias_active", 0),
            "status": account.get("status", ""),
            "host": account.get("host", ""),
            "last_error": account.get("last_error", ""),
        })
    except concurrent.futures.TimeoutError:
        return jsonify({"ok": False, "error": "iCloud 校验超时，请重新生成 Cookie 后再试"}), 504
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


@bp.route("/api/accounts/<acc_id>/remove", methods=["POST"])
def api_remove_account(acc_id):
    ok = _account_mgr.remove_account(acc_id)
    return jsonify({
        "ok": ok,
        "message": "账号已退出，后台数据已隐藏" if ok else "账号不存在",
    })


@bp.route("/api/accounts/<acc_id>/validate", methods=["POST"])
def api_validate_account(acc_id):
    try:
        account = _account_mgr.validate_account(acc_id)
        ok = account.get("status") == "active"
        return jsonify({
            "ok": ok,
            "real_email": account.get("real_email", ""),
            "icloud_email": account.get("icloud_email", ""),
            "alias_total": account.get("alias_total", 0),
            "alias_active": account.get("alias_active", 0),
            "status": account.get("status", ""),
            "error": "" if ok else (account.get("last_error") or "校验失败"),
            "last_error": account.get("last_error", ""),
        })
    except Exception as e: return jsonify({"ok":False,"error":str(e)})


@bp.route("/api/accounts/<acc_id>/rename", methods=["POST"])
def api_rename_account(acc_id):
    data = request.get_json() or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok":False,"error":"名称不能为空"})
    try:
        account = _account_mgr.update_account(acc_id, name=name)
        if not account:
            return jsonify({"ok":False,"error":"账号不存在"})
        return jsonify({"ok":True,"account":{k:v for k,v in account.items() if k!="cookies"}})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})


@bp.route("/api/accounts/<acc_id>/host", methods=["POST"])
def api_update_account_host(acc_id):
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or "").strip().lower()
    if host not in ("icloud.com", "icloud.com.cn"):
        return jsonify({"ok": False, "error": "host 只能是 icloud.com 或 icloud.com.cn"})
    account = _account_mgr.update_account(acc_id, host=host)
    if not account:
        return jsonify({"ok": False, "error": "账号不存在"})
    try:
        account = _account_mgr.validate_account(acc_id)
    except Exception:
        account = _account_mgr.get_account(acc_id) or account
    safe = {k: v for k, v in account.items() if k not in ("cookies", "app_password")}
    safe["has_app_password"] = bool(account.get("app_password"))
    safe["app_password"] = account.get("app_password","")
    safe["has_cookies"] = bool(account.get("cookies"))
    return jsonify({"ok": True, "account": safe})


@bp.route("/api/accounts/<acc_id>/aliases/<path:anonymous_id>/label", methods=["POST"])
def api_update_alias_label(acc_id, anonymous_id):
    data = request.get_json() or {}
    label = (data.get("label") or "").strip()
    email = (data.get("email") or "").strip()
    try:
        ok = _account_mgr.update_alias_label(acc_id, anonymous_id, label, email=email)
        if ok:
            _patch_alias_cache(email=email, anonymous_id=anonymous_id, label=label)
            if email:
                _inventory.update_item(email, label=label, status_type="ok", status_message="标签已同步")
        _emit_log("info", f"更新别名标签: {acc_id} {anonymous_id}")
        return jsonify({"ok": ok})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})


@bp.route("/api/accounts/<acc_id>/aliases/<path:anonymous_id>/delete", methods=["POST"])
def api_delete_alias(acc_id, anonymous_id):
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    if not email:
        for row in _read_alias_cache().get("aliases", []):
            if isinstance(row, dict) and row.get("account_id") == acc_id and row.get("anonymousId") == anonymous_id:
                email = row.get("email", "")
                break
    try:
        result = _account_mgr.delete_alias(acc_id, anonymous_id, email=email)
        email = result["email"]
        message = "此账号的 iCloud 已无该别名，已移入本地垃圾箱" if result["already_absent"] else "已从 iCloud 删除"
        _remove_alias_cache(email=email)
        _inventory.update_item(
            email,
            group="trash",
            active=False,
            deleted_at=datetime.now().isoformat(timespec="seconds"),
            status_type="warn",
            status_message=message,
        )
        _emit_log("info", f"{message}: {acc_id} {anonymous_id}")
        return jsonify({"ok": True, "message": message, **result})
    except Exception as e:
        return jsonify({"ok":False,"error":str(e)})


@bp.route("/api/accounts/<acc_id>/create", methods=["POST"])
def api_create_for_account(acc_id):
    data = request.get_json() or {}
    count = min(int(data.get("count",1)),50)
    label = data.get("label","")
    _update_state(creating=True)
    _emit_log("info",f"手动创建: 账号 {acc_id} x{count}")
    try:
        results = _account_mgr.create_aliases_for_account(acc_id, count, label)
        created = [r["email"] for r in results if r.get("ok")]
        errors = [r["error"] for r in results if not r.get("ok")]
        _update_state(creating=False)
        _increment_state(today_created=len(created), total_created=len(created))
        if created:
            acc = _account_mgr.get_account(acc_id) or {}
            _inventory.sync_aliases([{
                "email": email,
                "account_id": acc_id,
                "account_name": acc.get("name", ""),
                "account_email": acc.get("real_email", ""),
                "icloud_email": acc.get("icloud_email", ""),
                "label": label,
                "source": "local",
            } for email in created])
        if created: _emit_log("success",f"创建完成: {len(created)} 个")
        return jsonify({"ok":len(created)>0,"emails":created,"created":len(created),"errors":len(errors),"error":errors[0] if errors else None})
    except Exception as e:
        _update_state(creating=False)
        return jsonify({"ok":False,"error":str(e)})


def _run_batch_create(account_ids, count, label, create_pickup_links=False):
    try:
        all_results = _account_mgr.create_aliases_batch(
            account_ids,
            count_per_account=count,
            label=label,
        )
        total_created = sum(
            sum(1 for result in results if result.get("ok"))
            for results in all_results.values()
        )
        total_errors = sum(
            sum(1 for result in results if not result.get("ok"))
            for results in all_results.values()
        )
        rows = []
        for acc_id, results in all_results.items():
            acc = _account_mgr.get_account(acc_id) or {}
            for result in results:
                if result.get("ok") and result.get("email"):
                    rows.append({
                        "email": result.get("email"),
                        "account_id": acc_id,
                        "account_name": acc.get("name", ""),
                        "account_email": acc.get("real_email", ""),
                        "icloud_email": acc.get("icloud_email", ""),
                        "label": label,
                        "created_at": result.get("created_at") or datetime.now().isoformat(timespec="seconds"),
                        "source": "local",
                    })
        if rows:
            _inventory.sync_aliases(rows)
        for acc_id, results in all_results.items():
            acc = _account_mgr.get_account(acc_id) or {}
            account_label = acc.get("name") or acc.get("real_email") or acc_id
            for result in results:
                if result.get("ok") and result.get("email"):
                    _emit_log(
                        "success",
                        f"创建别名 [{account_label}] {result['email']}（创建时间 {result.get('created_at') or '-'}）",
                    )
        pickup_created = 0
        if create_pickup_links and rows:
            from services.mail_service import create_pickup_link
            for row in rows:
                record, error = create_pickup_link(row["email"])
                if record:
                    pickup_created += 1
                else:
                    _emit_log("warn", f"生成取码链接失败 [{row['email']}]: {error or '未知错误'}")
        _increment_state(today_created=total_created, total_created=total_created)
        link_suffix = f"，取码链接 {pickup_created} 个" if create_pickup_links else ""
        _emit_log("success", f"批量完成: {total_created} 成功 / {total_errors} 失败{link_suffix}")
        _update_state(
            creating=False,
            current_round_created=total_created,
            round_status=f"手动批量完成 {total_created} 个{link_suffix}",
            last_error=None,
        )
    except Exception as exc:
        _update_state(
            creating=False,
            current_round_created=0,
            round_status="手动批量创建失败",
            last_error=str(exc)[:200],
        )
        _emit_log("error", f"批量创建失败: {str(exc)[:160]}")


@bp.route("/api/create-batch", methods=["POST"])
def api_create_batch():
    data = request.get_json() or {}
    requested_ids = data.get("account_ids", [])
    account_ids = list(dict.fromkeys(str(value or "").strip() for value in requested_ids if value))
    count = max(1, min(int(data.get("count_per_account", 5)), 20))
    label = str(data.get("label", "")).strip()
    create_pickup_links = data.get("create_pickup_links") is True
    if not account_ids: return jsonify({"ok":False,"error":"请选择至少一个账号"})
    active_ids = {
        str(account.get("id") or "") for account in _account_mgr.list_accounts()
        if account.get("status") == "active"
    }
    invalid_ids = [acc_id for acc_id in account_ids if acc_id not in active_ids]
    if invalid_ids:
        return jsonify({"ok": False, "error": "所选账号已失效，请刷新后重新选择"}), 409
    with _lock:
        if _global_state.get("creating"):
            return jsonify({"ok": False, "error": "已有创建任务正在进行"}), 409
        _global_state.update({
            "creating": True,
            "current_round_created": 0,
            "round_status": f"手动批量创建中（{len(account_ids)} 个账号 x {count}）",
            "last_error": None,
        })
    link_suffix = "，同时生成取码链接" if create_pickup_links else ""
    _emit_log("info", f"批量创建已开始: {len(account_ids)} 个账号 x{count}{link_suffix}（后台执行）")
    threading.Thread(
        target=_run_batch_create,
        args=(account_ids, count, label, create_pickup_links),
        daemon=True,
        name="manual-batch-create",
    ).start()
    return jsonify({
        "ok": True,
        "accepted": True,
        "account_count": len(account_ids),
        "count_per_account": count,
        "create_pickup_links": create_pickup_links,
        "message": "批量创建已开始，后台会按节奏执行",
    }), 202


@bp.route("/api/edge-cookie-bridge", methods=["GET", "POST"])
def api_edge_cookie_bridge():
    if request.method == "GET":
        try:
            data = json.loads((HERE / "runtime" / "edge_cookie_bridge.json").read_text(encoding="utf-8"))
            return jsonify({k: v for k, v in data.items() if k != "cookie_header"})
        except (OSError, json.JSONDecodeError):
            return jsonify({"ok": False, "error": "尚未收到插件 Cookie"})
    try:
        payload = save_cookie_bridge_payload(request.get_json(silent=True) or {})
        safe = {k: v for k, v in payload.items() if k != "cookie_header"}
        return jsonify(safe)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

