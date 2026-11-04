import threading

from flask import Blueprint

from app_core import *
from services import auto_stock_service

bp = Blueprint("scheduler", __name__)

@bp.route("/api/cache/clear", methods=["POST"])
def api_clear_cache():
    cleared, errors = _clear_backend_caches()
    _emit_log("info", "已清理后台缓存: " + ", ".join(cleared or ["无"]))
    return jsonify({"ok": not errors, "cleared": cleared, "errors": errors})

@bp.route("/admin/clear-cache")
@bp.route("/clear-cache")
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

@bp.route("/api/scheduler/start", methods=["POST"])
def api_scheduler_start():
    global _scheduler_thread, _stop_event
    _stop_event.clear()
    _scheduler_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _scheduler_thread.start()
    _update_state(running=True)
    return jsonify({"ok":True})

@bp.route("/api/scheduler/stop", methods=["POST"])
def api_scheduler_stop():
    _stop_event.set()
    return jsonify({"ok":True})

@bp.route("/api/log-stream")
def api_log_stream():
    def generate():
        while True:
            try: entry = _log_queue.get(timeout=30); yield f"data: {json.dumps(entry,ensure_ascii=False)}\n\n"
            except queue.Empty: yield ": heartbeat\n\n"
    return Response(generate(), mimetype="text/event-stream", headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

@bp.route("/api/logs")
def api_logs():
    return jsonify({"ok": True, "logs": _read_runtime_logs(request.args.get("limit", 500, type=int))})

@bp.route("/api/logs/cleanup", methods=["POST"])
def api_logs_cleanup():
    data = request.get_json(silent=True) or {}
    days = max(1, min(int(data.get("days", RUNTIME_LOG_RETENTION_DAYS)), 365))
    result = _cleanup_runtime_log(days)
    _emit_log("info", f"运行日志清理完成：保留最近 {days} 天，删除 {result.get('removed', 0)} 条")
    return jsonify({"ok": True, "days": days, **result})

@bp.route("/api/auto-stock", methods=["GET", "POST"])
def api_auto_stock():
    if request.method == "GET":
        return auto_stock_service.get_auto_stock_config_response()
    return auto_stock_service.save_auto_stock_config_response()


@bp.route("/api/auto-stock/run", methods=["POST"])
def api_auto_stock_run():
    return auto_stock_service.run_auto_stock_response()
