"""Adapt only explicitly allowed console actions to background execution."""
from urllib.parse import urlsplit

from services.alias_delete_service import DeleteJobError

ALLOWED = {
    ("POST", "inventory.api_inventory_sync"),
    ("POST", "inventory.api_inventory_check_icloud"),
    ("POST", "inventory.api_inventory_check_forward"),
    ("POST", "inventory.api_inventory_calibrate_cloud"),
    ("POST", "inventory.api_inventory_move"),
    ("POST", "inventory.api_inventory_remark"),
    ("POST", "inventory.api_inventory_purge"),
    ("POST", "accounts.api_update_alias_label"),
    ("POST", "accounts.api_validate_account"),
    ("GET", "inbox.api_inbox"),
    ("GET", "inbox.api_all_inboxes"),
    ("POST", "scheduler.api_auto_stock_run"),
    ("POST", "scheduler.api_logs_cleanup"),
    ("POST", "pickup.api_revoke_pickup_links_batch"),
}


def prepare_operations(app, steps):
    prepared, labels = [], []
    for step in steps:
        if not isinstance(step, dict):
            raise DeleteJobError("任务步骤格式无效")
        path, method, body = step.get("path"), step.get("method", "POST"), step.get("body", {})
        if not isinstance(path, str) or not path.startswith("/api/") or len(path) > 2048 or not isinstance(body, dict):
            raise DeleteJobError("任务地址或参数无效")
        if method not in ("GET", "POST") or urlsplit(path).netloc or urlsplit(path).fragment:
            raise DeleteJobError("不支持此后台操作")
        try:
            with app.test_request_context(path, method=method, json=body) as ctx:
                endpoint, values = ctx.url_adapter.match()
        except Exception:
            raise DeleteJobError("后台操作不存在") from None
        if (method, endpoint) not in ALLOWED:
            raise DeleteJobError("此操作需要在原页面完成")
        label = str(step.get("label") or values.get("email_addr") or values.get("acc_id") or "执行操作")[:254]
        prepared.append((path, method, body, endpoint, values))
        labels.append(label)

    def execute(progress):
        if all(row[3] == "inventory.api_inventory_purge" for row in prepared):
            from services.code_inventory_service import _inventory
            emails = [row[4]["email_addr"].strip().lower() for row in prepared]
            result = {r["label"]: r for r in _inventory.purge_many(emails)}
            for index, email in enumerate(emails):
                progress(index, result[email])
            return
        for index, (path, method, body, endpoint, values) in enumerate(prepared):
            progress(index, {"state": "running"})
            try:
                # Reuse existing validation/business logic without making an HTTP
                # request or granting access to arbitrary routes. Auth is checked
                # on the public task submission route before this is queued.
                with app.test_request_context(path, method=method, json=body):
                    response = app.make_response(app.view_functions[endpoint](**values))
                    result = response.get_json() or {}
                errors = list(result.get("errors") or [])
                for detail in result.get("details") or []:
                    if isinstance(detail, dict):
                        errors.extend(detail.get("errors") or [])
                detail = "；".join(str(e.get("error", e) if isinstance(e, dict) else e) for e in errors)
                error = str(result.get("error") or detail)
                failed = response.status_code >= 400 or result.get("ok") is False or bool(errors)
                progress(index, {"state": "failed" if failed else "complete",
                                 "error": (error or "操作未完成")[:1000] if failed else "",
                                 "message": str(result.get("message") or "")[:300]})
            except Exception:
                progress(index, {"state": "failed", "error": "操作未完成，请刷新数据核对后重试。"})
    return execute, labels
