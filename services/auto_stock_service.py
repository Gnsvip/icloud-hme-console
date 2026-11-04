from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import jsonify, request

from app_core import _account_mgr, _inventory, _sync_inventory_from_known
from inventory_manager import load_auto_stock_config, save_auto_stock_config


BEIJING_TZ = ZoneInfo("Asia/Shanghai")


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _beijing_now():
    return datetime.now(timezone.utc).astimezone(BEIJING_TZ)


def _active_accounts():
    return [a for a in _account_mgr.list_accounts() if a.get("status") == "active"]


def _account_ids(value):
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(account_id or "").strip() for account_id in value if str(account_id or "").strip()))


def _stock_accounts(account_ids=None, all_accounts=False):
    active_accounts = _active_accounts()
    if all_accounts:
        return active_accounts
    selected = set(_account_ids(account_ids))
    return [account for account in active_accounts if str(account.get("id") or "") in selected]


def _public_config(cfg):
    out = dict(cfg or {})
    out["all_accounts"] = bool(out.get("all_accounts"))
    out["account_ids"] = [] if out["all_accounts"] else _account_ids(out.get("account_ids"))
    out.pop("account_id", None)
    return out


def get_auto_stock_config_response():
    return jsonify({"ok": True, "config": _public_config(load_auto_stock_config())})


def save_auto_stock_config_response():
    try:
        data = request.get_json(silent=True) or {}
        cfg = load_auto_stock_config()
        cfg.update({
            key: data[key]
            for key in ("enabled", "all_accounts", "account_ids", "prefix", "target", "batch")
            if key in data
        })
        cfg["all_accounts"] = bool(cfg.get("all_accounts"))
        cfg["account_ids"] = [] if cfg["all_accounts"] else _account_ids(cfg.get("account_ids"))
        if not cfg["all_accounts"] and not cfg["account_ids"]:
            return jsonify({"ok": False, "error": "请至少勾选一个自动补货账号"}), 400
        active_ids = {str(account.get("id") or "") for account in _active_accounts()}
        invalid_ids = [account_id for account_id in cfg["account_ids"] if account_id not in active_ids]
        if invalid_ids:
            return jsonify({"ok": False, "error": "所选账号已失效，请刷新后重新选择"}), 409
        cfg = save_auto_stock_config(cfg)
        return jsonify({"ok": True, "config": _public_config(cfg)})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


def run_auto_stock(data=None):
    data = data or {}
    cfg = load_auto_stock_config()
    cfg.update({k: v for k, v in data.items() if k in ("all_accounts", "account_ids", "prefix", "target", "batch", "enabled")})
    cfg = _public_config(cfg)
    if not cfg.get("enabled", False):
        return {"ok": True, "enabled": False, "created": 0, "message": "自动补货未启用", "config": cfg}
    target = max(0, int(cfg.get("target") or 0))
    batch = max(1, min(int(cfg.get("batch") or 5), 5))
    try:
        _sync_inventory_from_known()
        if not cfg["all_accounts"] and not cfg["account_ids"]:
            return {"ok": False, "enabled": True, "error": "请至少选择一个自动补货账号", "config": cfg}
        stock_accounts = _stock_accounts(cfg["account_ids"], cfg["all_accounts"])
        if not stock_accounts:
            return {"ok": False, "enabled": True, "error": "所选自动补货账号当前不可用", "config": cfg}
        if target <= 0:
            cfg["last_run"] = _utc_now_iso()
            cfg["last_error"] = ""
            save_auto_stock_config(cfg)
            return {"ok": True, "enabled": True, "created": 0, "message": "本轮创建数量为 0", "details": [], "config": cfg}
        all_created = []
        email_accounts = {}
        details_by_account = {}
        label = f"{cfg.get('prefix') or 'stock'} {_beijing_now().strftime('%m%d%H%M')}"
        for account in stock_accounts:
            account_id = account["id"]
            details_by_account[account_id] = {
                "account_id": account_id,
                "account": account.get("icloud_email") or account.get("real_email") or account.get("name") or account_id,
                "requested": 0,
                "created": 0,
                "errors": [],
            }
        available_accounts = list(stock_accounts)
        while len(all_created) < target and available_accounts:
            made_progress = False
            for account in list(available_accounts):
                if len(all_created) >= target:
                    break
                account_id = account["id"]
                create_count = min(batch, target - len(all_created))
                detail = details_by_account[account_id]
                detail["requested"] += create_count
                results = _account_mgr.create_aliases_for_account(account_id, create_count, label)
                created = [r.get("email") for r in results if r.get("ok") and r.get("email")]
                errors = [r.get("error") for r in results if not r.get("ok") and r.get("error")]
                if created:
                    _inventory.sync_aliases([{
                        "email": email,
                        "account_id": account_id,
                        "account_name": account.get("name", ""),
                        "account_email": account.get("real_email", ""),
                        "icloud_email": account.get("icloud_email", ""),
                        "label": label,
                        "source": "local",
                    } for email in created])
                    all_created.extend(created)
                    for email in created:
                        email_accounts[email] = account_id
                    detail["created"] += len(created)
                    made_progress = True
                if errors:
                    detail["errors"].extend(errors[:3])
                if not created:
                    available_accounts.remove(account)
            if not made_progress:
                break
        details = list(details_by_account.values())
        if not all_created:
            cfg["last_run"] = _utc_now_iso()
            cfg["last_error"] = ""
            save_auto_stock_config(cfg)
            message = "本轮没有创建成功"
            return {"ok": True, "enabled": True, "created": 0, "message": message, "details": details, "config": cfg}
        cfg["last_run"] = _utc_now_iso()
        cfg["last_error"] = ""
        save_auto_stock_config(cfg)
        return {
            "ok": True,
            "enabled": True,
            "created": len(all_created),
            "emails": all_created,
            "email_accounts": email_accounts,
            "details": details,
            "message": f"本轮创建 {len(all_created)} / {target} 个",
            "already_recorded": True,
            "config": cfg,
        }
    except Exception as e:
        cfg["last_error"] = str(e)
        save_auto_stock_config(cfg)
        return {"ok": False, "enabled": True, "error": str(e), "config": cfg}


def run_auto_stock_response():
    return jsonify(run_auto_stock(request.get_json(silent=True) or {}))
