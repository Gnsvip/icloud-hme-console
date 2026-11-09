#!/usr/bin/env python3
"""iCloud HME Web UI — 多账号聚合管理平台 — Flask single-page app."""
import concurrent.futures, hashlib, sys, os, json, time, queue, secrets, threading, re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path: sys.path.insert(0, str(HERE))

from flask import Response, request, jsonify, render_template_string, current_app
from icloud_hme import ICloudHME, extract_chrome_cookies
from account_manager import AccountManager
from imap_runtime import MailExecutor, wait_for_mail
from inventory_manager import (
    InventoryManager,
    base_icloud_email_address,
    check_forward_mail,
    delete_forward_config,
    extract_verification_code,
    load_auto_stock_config,
    load_forward_config,
    load_forward_configs,
    poll_microsoft_device_auth,
    save_auto_stock_config,
    save_cookie_bridge_payload,
    save_forward_config,
    start_microsoft_device_auth,
    test_forward_mail_connection,
)

# ---- config ----
RESULTS_DIR = HERE / "results"
LOGS_DIR = HERE / "logs"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
RUNTIME_LOG_FILE = LOGS_DIR / "runtime.log"
RUNTIME_LOG_RETENTION_DAYS = 14
RUNTIME_LOG_MAX_BYTES = 5 * 1024 * 1024
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
ALIASES_CACHE_FILE = RESULTS_DIR / "aliases_cache.json"
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
ADMIN_SESSION_COOKIE = "icloud_hme_admin"
ADMIN_SECRET_FILE = RESULTS_DIR / "admin_secret.key"
COOKIE_HELPER_DIR = HERE / "cookie-helper-extension"
COOKIE_HELPER_TOKEN_FILE = RESULTS_DIR / "cookie_helper_token.key"

def _load_admin_secret():
    env_secret = os.environ.get("ADMIN_SECRET_KEY")
    if env_secret:
        return env_secret
    try:
        secret = ADMIN_SECRET_FILE.read_text(encoding="utf-8").strip()
        if secret:
            return secret
    except OSError:
        pass
    secret = secrets.token_hex(32)
    ADMIN_SECRET_FILE.write_text(secret, encoding="utf-8")
    return secret


def _load_cookie_helper_token():
    try:
        token = COOKIE_HELPER_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(32)
    COOKIE_HELPER_TOKEN_FILE.write_text(token, encoding="utf-8")
    return token

def _cookie_helper_authorized():
    token = request.headers.get("X-HME-Helper-Token", "")
    return bool(token) and secrets.compare_digest(token, _load_cookie_helper_token())

def _admin_token():
    raw = f"{ADMIN_USER}\0{ADMIN_PASSWORD}\0{current_app.secret_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def _is_admin_authed():
    token = request.cookies.get(ADMIN_SESSION_COOKIE, "")
    return bool(token) and secrets.compare_digest(token, _admin_token())

def _is_public_path(path):
    if request.method == "OPTIONS":
        return True
    if path.startswith("/static/"):
        return True
    if path.rstrip("/") in {"/pickup", "/code"}:
        return True
    if path in {"/logout", "/admin/clear-cache", "/clear-cache", "/api/admin/login", "/api/admin/logout", "/api/admin/session", "/api/cookie-helper/import", "/favicon.ico"}:
        return True
    return path.startswith("/api/public/") or path.startswith("/c/")

def _admin_no_cache_headers(resp):
    path = request.path
    if path.startswith("/static/admin-v2/assets/") and resp.status_code == 200:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp
    is_admin_asset = path in {"/", "/index.html", "/admin", "/admin/", "/logout", "/admin/clear-cache", "/clear-cache"} or path.startswith("/static/")
    is_admin_api = path.startswith("/api/") and not path.startswith("/api/public/")
    is_pickup = path.startswith("/c/") or path.startswith("/api/public/")
    if is_admin_asset or is_admin_api or is_pickup:
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0, s-maxage=0"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        resp.headers["Surrogate-Control"] = "no-store"
        resp.headers["CDN-Cache-Control"] = "no-store"
        resp.headers["Cloudflare-CDN-Cache-Control"] = "no-store"
        resp.headers["Vary"] = "Cookie"
    if path.startswith("/c/"):
        resp.headers["Referrer-Policy"] = "no-referrer"
    if path.startswith("/api/cookie-helper/"):
        origin = request.headers.get("Origin", "")
        if origin.startswith("chrome-extension://"):
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-HME-Helper-Token"
            resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return resp

def _admin_login_page():
    html = render_template_string(r"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>后台登录 · iCloud HME</title>
  <style>
    :root{--blue:#007aff;--blue-2:#36a7ff;--ink:#101828;--muted:#667085;--line:#d8e7f6;--soft:#f5fbff;--danger:#d92d20;--ok:#188038;--shadow:rgba(44,92,140,.18);--sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","PingFang SC","Microsoft YaHei","Segoe UI",sans-serif}
    *{box-sizing:border-box}html,body{margin:0;min-height:100%;font-family:var(--sans);color:var(--ink)}
    body{display:grid;place-items:center;padding:28px;background:linear-gradient(135deg,#eaf7ff 0%,#f7fffb 100%)}
    .box{width:min(430px,100%);border:1px solid var(--line);border-radius:22px;background:rgba(255,255,255,.78);box-shadow:0 28px 80px var(--shadow);backdrop-filter:blur(18px);padding:30px}
    .brand{display:flex;align-items:center;gap:12px;margin-bottom:24px;font-weight:800;font-size:20px}
    .mark{width:32px;height:22px;border-radius:999px;background:linear-gradient(135deg,var(--blue-2),var(--blue));box-shadow:0 12px 28px rgba(0,122,255,.22);flex:0 0 auto}
    h1{font-size:30px;line-height:1.12;margin:0 0 8px;font-weight:850;letter-spacing:0}
    p{margin:0 0 22px;color:var(--muted);font-size:14px;line-height:1.7}
    label{display:block;margin:14px 0 7px;font-size:13px;font-weight:750;color:#5d718a}
    input{width:100%;height:46px;border:1px solid #cfdced;border-radius:12px;background:rgba(255,255,255,.86);color:var(--ink);padding:0 14px;font-size:15px;outline:none}
    input:focus{border-color:#7cbdff;box-shadow:0 0 0 4px rgba(0,122,255,.12);background:#fff}
    .actions{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-top:24px}
    .msg{min-height:22px;font-size:13px;color:var(--danger)}
    button{height:44px;border:1px solid var(--blue);border-radius:12px;background:var(--blue);color:#fff;font-size:15px;font-weight:800;padding:0 28px;cursor:pointer;box-shadow:0 13px 28px rgba(0,122,255,.24)}
    button:hover{filter:brightness(.96)}button:disabled{opacity:.52;cursor:not-allowed}
    .hint{margin-top:18px;color:#8aa0b8;font-size:12px;line-height:1.7}
  </style>
</head>
<body>
  <main class="box">
    <div class="brand"><span class="mark"></span><span>iCloud HME</span></div>
    <h1>后台登录</h1>
    <p>登录后可以管理账号、创建邮箱和查看后台接口；专属取码链接不受影响。</p>
    <form id="loginForm">
      <label>账号</label>
      <input id="username" name="username" autocomplete="username" placeholder="输入后台账号" autofocus>
      <label>密码</label>
      <input id="password" name="password" type="password" autocomplete="current-password">
      <div class="actions">
        <div id="msg" class="msg"></div>
        <button id="submit" type="submit">登录</button>
      </div>
    </form>
    <div class="hint">带 token 的专属取码链接保持公开，后台操作需要登录。</div>
  </main>
<script>
document.getElementById('loginForm').addEventListener('submit',async function(e){
  e.preventDefault();
  var btn=document.getElementById('submit'),msg=document.getElementById('msg');
  btn.disabled=true;msg.textContent='登录中...';
  try{
    var res=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:username.value.trim(),password:password.value})});
    var data=await res.json();
    if(!data.ok){msg.textContent=data.error||'账号或密码错误';return}
    msg.style.color='var(--green)';msg.textContent='登录成功';
    setTimeout(function(){location.reload()},180);
  }catch(err){msg.textContent=err.message||'网络错误'}
  finally{btn.disabled=false}
});
</script>
</body>
</html>
    """)
    return Response(html, mimetype="text/html; charset=utf-8")

def _require_admin_auth():
    if _is_public_path(request.path):
        return None
    if _is_admin_authed():
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "请先登录后台"}), 401
    if request.path in {"/", "/index.html", "/admin", "/admin/"} and (HERE / "static/admin-v2/index.html").is_file():
        return None  # The shell contains no account data; APIs remain protected.
    return _admin_login_page()

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

def api_admin_logout():
    resp = jsonify({"ok": True})
    resp.delete_cookie(ADMIN_SESSION_COOKIE)
    return resp

def admin_logout_page():
    resp = Response("", status=302)
    resp.headers["Location"] = "/admin/"
    resp.delete_cookie(ADMIN_SESSION_COOKIE)
    return resp

def api_admin_session():
    return jsonify({"ok": _is_admin_authed(), "user": "admin" if _is_admin_authed() else None})
_log_queue = queue.Queue(maxsize=2000)
_log_file_lock = threading.Lock()
_last_log_cleanup = 0.0
_today_key = datetime.now(timezone.utc).astimezone(BEIJING_TZ).strftime("%Y%m%d")
_global_state = {"running":False,"creating":False,"round_status":"","total_created":0,"today_created":0,"current_round_created":0,"next_trigger":None,"last_error":None,"cookies_ok":False,"alias_count":0,"alias_active":0}
_lock = threading.Lock()
_scheduler_thread = None
_stop_event = threading.Event()
_account_mgr = AccountManager()
_inventory = InventoryManager()

_RATE_LIMIT_KW = ["limit","exceeded","maximum","quota","429","too many","try again","unavailable","上限","超过","过多","频繁","rate limit","throttle","blocked"]

def _is_limit_error(err: str) -> bool: return any(kw in err.lower() for kw in _RATE_LIMIT_KW)

_imap_executor = MailExecutor(max_workers=4, max_pending=4, name="imap")
_account_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="account")
_inventory_cache_sync_ts = 0.0
_inventory_cache_sync_revision = None

def _clear_backend_caches():
    global _inventory_cache_sync_ts
    cleared = []
    errors = []
    try:
        _account_mgr._cache.clear_all()
        cleared.append("mail_cache")
    except Exception as e:
        errors.append(f"mail_cache: {e}")
    try:
        if ALIASES_CACHE_FILE.exists():
            ALIASES_CACHE_FILE.unlink()
        cleared.append("aliases_cache")
    except Exception as e:
        errors.append(f"aliases_cache: {e}")
    _inventory_cache_sync_ts = 0.0
    return cleared, errors

def api_clear_cache():
    cleared, errors = _clear_backend_caches()
    _emit_log("info", "已清理后台缓存: " + ", ".join(cleared or ["无"]))
    return jsonify({"ok": not errors, "cleared": cleared, "errors": errors})

def admin_clear_cache_page():
    cleared, errors = ([], [])
    if _is_admin_authed():
        cleared, errors = _clear_backend_caches()
    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>清理缓存 · iCloud HME</title>
  <style>
    :root{{--blue:#007aff;--ink:#101828;--muted:#667085;--line:#d8e7f6;--shadow:rgba(44,92,140,.18);--sans:-apple-system,BlinkMacSystemFont,"SF Pro Display","PingFang SC","Microsoft YaHei","Segoe UI",sans-serif}}
    *{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:grid;place-items:center;padding:24px;background:linear-gradient(135deg,#eaf7ff 0%,#f7fffb 100%);font-family:var(--sans);color:var(--ink)}}
    .box{{width:min(440px,100%);border:1px solid var(--line);border-radius:22px;background:rgba(255,255,255,.82);box-shadow:0 28px 80px var(--shadow);backdrop-filter:blur(18px);padding:30px}}
    .brand{{display:flex;align-items:center;gap:12px;margin-bottom:18px;font-weight:850;font-size:20px}}
    .mark{{width:32px;height:22px;border-radius:999px;background:linear-gradient(135deg,#36a7ff,#007aff);box-shadow:0 12px 28px rgba(0,122,255,.22)}}
    h1{{margin:0 0 8px;font-size:28px;letter-spacing:0}}p{{margin:0;color:var(--muted);line-height:1.7;font-size:14px}}
    .status{{margin-top:18px;padding:12px 14px;border-radius:14px;background:#f5fbff;border:1px solid var(--line);font-size:13px;color:#516177;line-height:1.7}}
  </style>
</head>
<body>
  <main class="box">
    <div class="brand"><span class="mark"></span><span>iCloud HME</span></div>
    <h1>正在清理缓存</h1>
    <p>正在清掉这个域名下的旧页面脚本、本地页面状态和浏览器缓存，马上回到后台。</p>
    <div class="status" id="status">后端缓存: {", ".join(cleared) if cleared else "未登录或无需清理"}{"；错误: " + "; ".join(errors) if errors else ""}</div>
  </main>
<script>
(async function(){{
  var status=document.getElementById('status');
  try{{ localStorage.clear(); }}catch(e){{}}
  try{{ sessionStorage.clear(); }}catch(e){{}}
  try{{
    if('caches' in window){{
      var keys=await caches.keys();
      await Promise.all(keys.map(function(k){{return caches.delete(k)}}));
      status.textContent += '；浏览器缓存已清理';
    }}
  }}catch(e){{ status.textContent += '；浏览器缓存清理失败: '+e.message; }}
  try{{
    if(navigator.serviceWorker){{
      var regs=await navigator.serviceWorker.getRegistrations();
      await Promise.all(regs.map(function(r){{return r.unregister()}}));
    }}
  }}catch(e){{}}
  setTimeout(function(){{ location.replace('/admin/?cache_cleared='+Date.now()); }}, 900);
}})();
</script>
</body>
</html>"""
    resp = Response(html, mimetype="text/html; charset=utf-8")
    resp.headers["Clear-Site-Data"] = '"cache", "storage"'
    return resp

def _valid_account_id(acc_id):
    acc_id = (acc_id or "").strip()
    return acc_id if acc_id and _account_mgr.get_account(acc_id) else ""

def _is_icloud_mail_address(email_addr):
    value = str(email_addr or "").strip().lower()
    return bool(value) and value.endswith(("@icloud.com", "@me.com", "@mac.com", "@icloud.com.cn"))

def _account_can_read_mail(account):
    if not isinstance(account, dict) or not account.get("id"):
        return False
    if not account.get("app_password"):
        return False
    imap_email = str(account.get("icloud_email") or "").strip().lower()
    real_email = str(account.get("real_email") or "").strip().lower()
    return _is_icloud_mail_address(imap_email) or _is_icloud_mail_address(real_email)

def _mail_account_candidates(email_addr, preferred=""):
    """Return readable accounts with the known email owner first."""
    email_addr = (email_addr or "").strip().lower()
    preferred = (preferred or "").strip()
    seen = set()
    candidates = []

    def add(acc_id):
        acc_id = (acc_id or "").strip()
        if not acc_id or acc_id in seen:
            return
        account = _account_mgr.get_account(acc_id)
        if not account or not _account_can_read_mail(account):
            return
        seen.add(acc_id)
        candidates.append(account)

    add(preferred)
    add(_find_alias_account_id(email_addr, ""))

    for account in _account_mgr.list_accounts():
        if not account or account.get("id") in seen:
            continue
        # Prefer exact mailbox owner before generic readable accounts.
        imap_email = str(account.get("icloud_email") or "").strip().lower()
        real_email = str(account.get("real_email") or "").strip().lower()
        if email_addr and email_addr in {imap_email, real_email}:
            add(account.get("id"))

    for account in _account_mgr.list_accounts():
        add(account.get("id"))

    return candidates

def _find_alias_account_id(email_addr, preferred=""):
    email_addr = (email_addr or "").strip().lower()
    lookup_emails = {email_addr, base_icloud_email_address(email_addr)}
    preferred = (preferred or "").strip()
    if _valid_account_id(preferred):
        return preferred
    try:
        rows, _summary = _inventory.list_items(group="all")
        for row in rows:
            if str(row.get("email") or "").strip().lower() in lookup_emails:
                acc_id = _valid_account_id(row.get("account_id"))
                if acc_id:
                    return acc_id
    except Exception:
        pass
    for row in _read_alias_cache().get("aliases", []):
        if str(row.get("email") or "").strip().lower() in lookup_emails:
            acc_id = _valid_account_id(row.get("account_id"))
            if acc_id:
                return acc_id
    for row in _read_local_email_rows():
        if str(row.get("email") or "").strip().lower() in lookup_emails:
            acc_id = _valid_account_id(row.get("account_id"))
            if acc_id:
                return acc_id
    active = [a for a in _account_mgr.list_accounts() if a.get("status") == "active"]
    return active[0]["id"] if len(active) == 1 else ""

def _read_alias_cache():
    try:
        data = json.loads(ALIASES_CACHE_FILE.read_text(encoding="utf-8"))
        aliases = data.get("aliases", [])
        if not isinstance(aliases, list):
            aliases = []
        return {
            "aliases": aliases,
            "count": len(aliases),
            "updated_at": data.get("updated_at"),
            "ok": True,
        }
    except (OSError, json.JSONDecodeError):
        return {"aliases": [], "count": 0, "updated_at": None, "ok": True}

def _write_alias_cache(aliases):
    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        ALIASES_CACHE_FILE.write_text(
            json.dumps(
                {"aliases": aliases or [], "updated_at": datetime.now().isoformat()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

def _patch_alias_cache(email="", anonymous_id="", **updates):
    cached = _read_alias_cache().get("aliases", [])
    email = (email or "").strip().lower()
    anonymous_id = (anonymous_id or "").strip()
    changed = False
    for row in cached:
        if not isinstance(row, dict):
            continue
        if (anonymous_id and row.get("anonymousId") == anonymous_id) or (
            email and str(row.get("email", "")).strip().lower() == email
        ):
            row.update(updates)
            changed = True
    if changed:
        _write_alias_cache(cached)

def _remove_alias_cache(email="", anonymous_id=""):
    cached = _read_alias_cache().get("aliases", [])
    email = (email or "").strip().lower()
    anonymous_id = (anonymous_id or "").strip()
    kept = []
    changed = False
    for row in cached:
        if isinstance(row, dict) and (
            (anonymous_id and row.get("anonymousId") == anonymous_id)
            or (email and str(row.get("email", "")).strip().lower() == email)
        ):
            changed = True
            continue
        kept.append(row)
    if changed:
        _write_alias_cache(kept)

def _account_lookup():
    return {a.get("id"): a for a in _account_mgr.list_accounts()}

def _read_local_email_rows(limit=0):
    emails = []
    accounts_by_id = _account_lookup()
    f = RESULTS_DIR / "latest_emails.txt"
    if f.exists():
        lines = f.read_text(encoding="utf-8").strip().split("\n")
        if limit > 0 and len(lines) > limit:
            lines = lines[-limit:]
        for line in lines:
            line = line.strip()
            if not line or "@" not in line:
                continue
            parts = line.split("\t")
            acc_id = parts[1] if len(parts) > 1 else ""
            acc = accounts_by_id.get(acc_id, {})
            emails.append({
                "email": parts[0],
                "account_id": acc_id,
                "account_name": acc.get("name", ""),
                "account_email": acc.get("real_email", ""),
                "icloud_email": acc.get("icloud_email", ""),
                "created_at": "",
                "source": "local",
            })
    emails.reverse()
    return emails

def _active_account_ids():
    return {str(a.get("id") or "") for a in _account_mgr.list_accounts() if a.get("id")}

def _inventory_summary_from_items(items):
    summary = {"all": 0, "unused": 0, "finished": 0, "trash": 0, "disabled": 0, "unread": 0, "with_code": 0}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        summary["all"] += 1
        group = item.get("group") or "unused"
        if group in summary:
            summary[group] += 1
        if item.get("lifecycle_status") == "disabled":
            summary["disabled"] += 1
        if item.get("unread"):
            summary["unread"] += 1
        if item.get("code"):
            summary["with_code"] += 1
    return summary

def _read_inventory_email_rows(limit=0, include_trash=False, account_ids=None):
    """Return saved mailbox rows without requiring the original account online."""
    allowed = None if account_ids is None else {str(x) for x in account_ids if x}
    if account_ids is not None and not allowed:
        return []
    try:
        _sync_inventory_from_known()
        _sync_inventory_from_mail_cache()
    except Exception:
        pass
    rows, _summary = _inventory.list_items(group="all")
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if not include_trash and item.get("group") == "trash":
            continue
        email = str(item.get("email") or "").strip()
        if not email:
            continue
        if allowed is not None and str(item.get("account_id") or "") not in allowed:
            continue
        out.append({
            "email": email,
            "account_id": item.get("account_id", ""),
            "account_name": item.get("account_name", ""),
            "account_email": item.get("account_email", ""),
            "icloud_email": item.get("icloud_email", ""),
            "label": item.get("label", ""),
            "active": item.get("active", True),
            "anonymousId": item.get("anonymousId", ""),
            "createdAt": item.get("created_ts", 0) or 0,
            "created_at": item.get("created_at", ""),
            "lifecycle_status": item.get("lifecycle_status", "active"),
            "lifecycle_reason": item.get("lifecycle_reason", ""),
            "deactivated_at": item.get("deactivated_at", ""),
            "deactivation_alias": item.get("deactivation_alias", ""),
            "deactivation_subject": item.get("deactivation_subject", ""),
            "deactivation_sender": item.get("deactivation_sender", ""),
            "deactivation_message_id": item.get("deactivation_message_id", ""),
            "deactivation_message_date": item.get("deactivation_message_date", ""),
            "deactivation_source": item.get("deactivation_source", ""),
            "source": item.get("source", "inventory") or "inventory",
        })
    if limit > 0:
        out = out[:limit]
    return out

def _enrich_alias_rows(rows):
    accounts_by_id = _account_lookup()
    enriched = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        item = dict(row)
        acc = accounts_by_id.get(item.get("account_id"), {})
        item.setdefault("account_name", acc.get("name", ""))
        item.setdefault("account_email", acc.get("real_email", ""))
        item.setdefault("icloud_email", acc.get("icloud_email", ""))
        enriched.append(item)
    return enriched

def _sync_inventory_from_known(aliases=None):
    rows = []
    rows.extend(_read_local_email_rows())
    rows.extend(_enrich_alias_rows(aliases if aliases is not None else _read_alias_cache().get("aliases", [])))
    return _inventory.sync_aliases(rows)

def _inventory_target_emails(account_ids=None):
    allowed = None if account_ids is None else {str(x) for x in account_ids if x}
    _sync_inventory_from_known()
    rows, _summary = _inventory.list_items(group="all")
    return [
        r.get("email", "") for r in rows
        if r.get("email") and r.get("group") != "trash" and r.get("lifecycle_status") != "disabled"
        and (allowed is None or str(r.get("account_id") or "") in allowed)
    ]

def _inventory_alias_seed(email_addr, account_id=""):
    email_addr = (email_addr or "").strip().lower()
    if not email_addr:
        return {}
    acc = _account_mgr.get_account(account_id) if account_id else {}
    acc = acc or {}
    return {
        "email": email_addr,
        "account_id": account_id or "",
        "account_name": acc.get("name", ""),
        "account_email": acc.get("real_email", ""),
        "icloud_email": acc.get("icloud_email", ""),
        "source": "mail",
    }

def _messages_for_inventory(messages, alias_email=""):
    alias_email = (alias_email or "").strip().lower()
    out = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            continue
        row = dict(msg)
        if alias_email:
            hay = " ".join(str(row.get(k) or "") for k in ("to", "cc", "bcc", "recipient")).lower()
            if alias_email not in hay:
                row["recipient"] = alias_email
        out.append(row)
    return out

def _sync_inventory_from_messages(messages, account_id="", method="iCloud IMAP", seed_aliases=None):
    try:
        _sync_inventory_from_known()
        return _apply_inventory_messages(messages, account_id=account_id, method=method, seed_aliases=seed_aliases)
    except Exception as e:
        _emit_log("warn", f"收件状态同步到收码台失败: {str(e)[:160]}")
        return {"ok": False, "error": str(e)}

def _apply_inventory_messages(messages, account_id="", method="iCloud IMAP", seed_aliases=None):
    seeds = [_inventory_alias_seed(x, account_id) for x in (seed_aliases or [])]
    seeds = [x for x in seeds if x.get("email")]
    if seeds:
        _inventory.sync_aliases(seeds)
    return _inventory.apply_messages(messages or [], account_id=account_id, method=method)

def _sync_inventory_from_mail_cache(force=False):
    global _inventory_cache_sync_ts, _inventory_cache_sync_revision
    now = time.time()
    revision = (id(_account_mgr._cache), _account_mgr._cache.revision)
    if not force and revision == _inventory_cache_sync_revision:
        return {"ok": True, "skipped": True}
    if not force and now - _inventory_cache_sync_ts < 20:
        return {"ok": True, "skipped": True}
    _inventory_cache_sync_ts = now
    total = 0
    try:
        for acc in _account_mgr.list_accounts():
            acc_id = acc.get("id", "")
            if not acc_id:
                continue
            by_alias = _account_mgr._cache.get_all_alias_mail(acc_id)
            alias_messages = []
            seed_aliases = []
            for alias_email, msgs in by_alias.items():
                seed_aliases.append(alias_email)
                alias_messages.extend(_messages_for_inventory(msgs, alias_email))
            if alias_messages:
                result = _apply_inventory_messages(alias_messages, account_id=acc_id, method="本地邮件缓存", seed_aliases=seed_aliases)
                total += int(result.get("count") or 0)
            inbox_messages = _account_mgr._cache.get_inbox(acc_id)
            if inbox_messages:
                result = _apply_inventory_messages(inbox_messages, account_id=acc_id, method="本地收件箱缓存")
                total += int(result.get("count") or 0)
        _inventory_cache_sync_revision = revision
        return {"ok": True, "updated": total}
    except Exception as e:
        _emit_log("warn", f"本地邮件缓存同步到收码台失败: {str(e)[:160]}")
        return {"ok": False, "error": str(e)}

def _run_imap_with_timeout(fn, timeout=35):
    return wait_for_mail(_imap_executor.submit(fn, timeout=timeout))

def _attach_cached_bodies(acc_id, messages):
    enriched = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            enriched.append(msg)
            continue
        row = dict(msg)
        msg_id = str(row.get("id", "")).strip()
        cached = _account_mgr._cache.get_message(acc_id, msg_id) if msg_id else None
        if cached:
            row["body"] = cached.get("body", row.get("body", ""))
            row["content_type"] = cached.get("content_type", row.get("content_type", ""))
            if "body_truncated" in cached:
                row["body_truncated"] = cached["body_truncated"]
            row["has_body"] = True
        else:
            row["has_body"] = bool(row.get("body"))
        enriched.append(row)
    return enriched

def _attach_cached_bodies_by_alias(acc_id, by_alias):
    out = {}
    for alias, messages in (by_alias or {}).items():
        out[alias] = _attach_cached_bodies(acc_id, messages)
    return out

def _fetch_missing_bodies(acc_id, messages, max_bodies=5):
    enriched = _attach_cached_bodies(acc_id, messages or [])
    missing = [m for m in enriched if m.get("id") and not m.get("body")][:max_bodies]
    if not missing:
        return enriched
    mail = None
    by_id = {str(m.get("id")): dict(m) for m in enriched if m.get("id")}
    fetched = {}
    try:
        mail = _account_mgr.get_mail_client(acc_id)
        for msg in missing:
            msg_id = str(msg.get("id"))
            cached = _account_mgr._cache.get_message(acc_id, msg_id)
            if cached:
                merged = dict(msg)
                merged.update(cached)
                by_id[msg_id] = merged
                continue
            full = mail.fetch_full(msg_id.encode())
            if full:
                merged = dict(msg)
                merged.update(full)
                fetched[msg_id] = merged
                by_id[msg_id] = merged
    finally:
        try:
            if fetched:
                _account_mgr._cache.set_messages(acc_id, fetched)
        finally:
            if mail:
                try:
                    mail.disconnect()
                except Exception:
                    pass
    return [by_id.get(str(m.get("id")), m) if m.get("id") else m for m in enriched]

def _best_code_from_messages(messages):
    for msg in messages or []:
        code = extract_verification_code(
            "{}\n{}\n{}".format(msg.get("subject", ""), msg.get("body", ""), msg.get("body_preview", ""))
        )
        if code:
            return code, msg
    return "", (messages or [None])[0]

_time_offset = 0.0
def _sync_time():
    global _time_offset
    for url in ["https://www.baidu.com","https://www.cloudflare.com","https://www.microsoft.com"]:
        try:
            import requests as _r
            resp = _r.head(url, timeout=5)
            date_str = resp.headers.get("Date","")
            if date_str:
                from email.utils import parsedate_to_datetime
                net_time = parsedate_to_datetime(date_str)
                _time_offset = net_time.timestamp() - time.time()
                return _time_offset
        except: continue
    return 0.0

def _now() -> datetime: return datetime.now() + timedelta(seconds=_time_offset)

def _beijing_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(BEIJING_TZ)

def _beijing_now() -> datetime: return _beijing_time(_now())

def _safe_log_message(msg):
    text = str(msg or "")
    return re.sub(r"(trustTokens?\s*[=:]\s*)([^,}\]]+)", r"\1[已隐藏]", text, flags=re.IGNORECASE)

def _cleanup_runtime_log(days=RUNTIME_LOG_RETENTION_DAYS):
    cutoff = _now() - timedelta(days=max(1, int(days or RUNTIME_LOG_RETENTION_DAYS)))
    with _log_file_lock:
        if not RUNTIME_LOG_FILE.exists():
            return {"removed": 0, "kept": 0}
        try:
            raw_lines = RUNTIME_LOG_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {"removed": 0, "kept": 0}
        kept = []
        removed = 0
        for line in raw_lines:
            try:
                entry = json.loads(line)
                stamp = datetime.strptime(str(entry.get("time", "")), "%Y-%m-%d %H:%M:%S")
                if stamp < cutoff:
                    removed += 1
                    continue
            except (ValueError, TypeError, json.JSONDecodeError):
                pass
            kept.append(line)
        content = "\n".join(kept)
        if content:
            content += "\n"
        if len(content.encode("utf-8")) > RUNTIME_LOG_MAX_BYTES:
            kept = kept[-5000:]
            content = "\n".join(kept) + ("\n" if kept else "")
        temp = RUNTIME_LOG_FILE.with_suffix(".tmp")
        try:
            temp.write_text(content, encoding="utf-8")
            temp.replace(RUNTIME_LOG_FILE)
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
        return {"removed": removed, "kept": len(kept)}

def _read_runtime_logs(limit=500):
    try:
        lines = RUNTIME_LOG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    result = []
    for line in lines[-max(1, min(int(limit or 500), 1000)):]:
        try:
            entry = json.loads(line)
        except (ValueError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(entry, dict):
            result.append(entry)
    return result

def _emit_log(level, msg):
    global _last_log_cleanup
    entry = {
        "time": _now().strftime("%Y-%m-%d %H:%M:%S"),
        "level": str(level or "info"),
        "msg": _safe_log_message(msg),
    }
    # Legacy SSE readers use this queue; the current UI reads the log file.
    # Keep the newest entries even when nobody has an SSE connection open.
    while True:
        try:
            _log_queue.put_nowait(entry)
            break
        except queue.Full:
            try:
                _log_queue.get_nowait()
            except queue.Empty:
                pass
    try:
        with _log_file_lock:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            with RUNTIME_LOG_FILE.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        if time.monotonic() - _last_log_cleanup >= 3600:
            _last_log_cleanup = time.monotonic()
            _cleanup_runtime_log()
    except OSError:
        pass

def _update_state(**kw):
    global _today_key
    with _lock:
        today = _beijing_now().strftime("%Y%m%d")
        if today != _today_key: _global_state["today_created"] = 0; _today_key = today
        _global_state.update(kw)

def _increment_state(**kw):
    global _today_key
    with _lock:
        today = _beijing_now().strftime("%Y%m%d")
        if today != _today_key: _global_state["today_created"] = 0; _today_key = today
        for k, delta in kw.items(): _global_state[k] = _global_state.get(k,0) + delta

def _scheduler_loop():
    """后台调度器：北京时间 7:00-20:00，自动补货优先，未启用时保留随机创建。"""
    import random as _random
    from icloud_hme import ICloudHME
    _update_state(running=True, round_status="等待触发窗口")
    _emit_log("info", "调度器已启动 (BJ 7-20h, 自动补货优先, 间隔 60-90min)")
    def _bj_hour() -> int: return _beijing_now().hour
    while not _stop_event.is_set():
        h = _bj_hour()
        if h < 7 or h >= 20: _update_state(round_status=f"非窗口时段 (BJ {h}:00)，等待..."); _stop_event.wait(1800); continue
        active_accounts = [a for a in _account_mgr.list_accounts() if a.get("status") == "active"]
        if not active_accounts: _update_state(creating=False, round_status="无活跃账号，跳过"); _stop_event.wait(1800); continue
        round_total = 0
        try:
            from services.auto_stock_service import run_auto_stock
            _update_state(creating=True, round_status="自动补货检查中...")
            stock_result = run_auto_stock({})
            if stock_result.get("enabled"):
                round_total = int(stock_result.get("created") or 0)
                if stock_result.get("ok"):
                    if not stock_result.get("already_recorded"):
                        email_accounts = stock_result.get("email_accounts") or {}
                        fallback_account_ids = (stock_result.get("config") or {}).get("account_ids") or []
                        fallback_account_id = fallback_account_ids[0] if len(fallback_account_ids) == 1 else ""
                        for email in stock_result.get("emails") or []:
                            try:
                                with open(str(RESULTS_DIR / "latest_emails.txt"), "a", encoding="utf-8") as f:
                                    f.write(f"{email}\t{email_accounts.get(email) or fallback_account_id}\n")
                            except OSError:
                                pass
                    if round_total:
                        _increment_state(today_created=round_total, total_created=round_total)
                        _emit_log("success", f"自动补货完成: 创建 {round_total} 个")
                    else:
                        _emit_log("info", stock_result.get("message") or "自动补货无需创建")
                    _update_state(creating=False, current_round_created=round_total, round_status=f"自动补货创建 {round_total} 个", last_error=None)
                else:
                    err = stock_result.get("error") or "自动补货失败"
                    _emit_log("warn", err)
                    _update_state(creating=False, current_round_created=0, round_status="自动补货失败", last_error=err)
                interval_sec = _random.randint(3600,5400)
                target = _now() + timedelta(seconds=interval_sec)
                _update_state(next_trigger=target.timestamp())
                _emit_log("info", f"下轮 {_beijing_time(target).strftime('%H:%M')} (间隔 {interval_sec//60}min)")
                _stop_event.wait(interval_sec)
                continue
        except Exception as e:
            _emit_log("warn", f"自动补货调度异常，回退随机创建: {str(e)[:120]}")
            _update_state(creating=False)
        for i, account in enumerate(active_accounts):
            if _stop_event.is_set(): break
            acc_id = account["id"]; acc_name = account.get("name", acc_id)
            target_count = _random.randint(3, 5)
            _emit_log("info", f"[{acc_name}] 本轮目标 {target_count} 个")
            client = ICloudHME(account["cookies"], host=account.get("host","icloud.com"), verbose=False)
            created = 0; errors = 0
            while created < target_count and errors < 3 and not _stop_event.is_set():
                try:
                    result = client.create_alias(label=f"{acc_name} {_beijing_now().strftime('%m%d%H%M')}", max_retries=2)
                    email = result.get("email","")
                    if email:
                        created += 1; round_total += 1
                        _emit_log("success", f"[{acc_name}] ({created}/{target_count}) {email}")
                        _increment_state(today_created=1, total_created=1)
                        with open(str(RESULTS_DIR/"latest_emails.txt"),"a",encoding="utf-8") as f: f.write(f"{email}\t{acc_id}\n")
                        _account_mgr.update_account(acc_id, alias_total=account.get("alias_total",0)+1)
                        account["alias_total"] = account.get("alias_total",0)+1
                        errors = 0; time.sleep(_random.uniform(15,45))
                    else: errors += 1
                except Exception as e:
                    err_str = str(e)
                    if _is_limit_error(err_str): _emit_log("info",f"[{acc_name}] 触达上限: {err_str[:60]}"); break
                    errors += 1; _emit_log("warn",f"[{acc_name}] 失败: {err_str[:80]}")
            if i < len(active_accounts)-1: time.sleep(_random.uniform(120,300))
        _update_state(creating=False, current_round_created=round_total, round_status=f"本轮创建 {round_total} 个")
        interval_sec = _random.randint(3600,5400)
        target = _now() + timedelta(seconds=interval_sec)
        _update_state(next_trigger=target.timestamp())
        _emit_log("info", f"下轮 {_beijing_time(target).strftime('%H:%M')} (间隔 {interval_sec//60}min)")
        _stop_event.wait(interval_sec)
    _update_state(running=False, next_trigger=None, round_status="已停止")
    _emit_log("info", "调度器已停止")

def _health_loop():
    _error_reported = set()
    while not _stop_event.is_set():
        if _stop_event.wait(300): break
        for account in _account_mgr.list_accounts():
            if account.get("status") != "active": continue
            try: _account_mgr.validate_account(account["id"]); _error_reported.discard(account["id"])
            except Exception as e:
                if account["id"] not in _error_reported: _emit_log("warn",f"健康检查失败 [{account.get('name','?')}]: {str(e)[:100]}"); _error_reported.add(account["id"])



def init_app(app):
    if not ADMIN_PASSWORD:
        raise RuntimeError("Set ADMIN_PASSWORD before starting the web console; no default password is provided.")
    app.secret_key = _load_admin_secret()
    app.after_request(_admin_no_cache_headers)
    app.before_request(_require_admin_auth)
    return app


__all__ = [name for name in globals() if not (name.startswith("__") and name.endswith("__"))]
