#!/usr/bin/env python3
"""iCloud HME Web UI startup."""
import os
import signal as _signal
import threading

from flask import Flask

import app_core as core
from routes import register_routes


app = Flask(__name__)
core.init_app(app)
register_routes(app)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="iCloud HME Web UI")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 5050)))
    parser.add_argument("--host", type=str, default=os.environ.get("HOST", "0.0.0.0"))
    parser.add_argument("--scheduler", action="store_true", help="启动时自动运行调度器")
    parser.add_argument("--no-sync", action="store_true", help="跳过时间校准")
    args = parser.parse_args()

    if not args.no_sync:
        offset = core._sync_time()
        if abs(offset) > 0.5:
            print(f"[*] Time sync: offset {offset:.1f}s")

    threading.Thread(target=core._health_loop, daemon=True).start()
    accounts = core._account_mgr.list_accounts()
    if accounts:
        print(f"[+] {len(accounts)} account(s) loaded")
        for a in accounts:
            print(f"    [OK] {a.get('name','?')} - {a.get('real_email','?')} ({a.get('alias_total',0)} aliases)")
    else:
        print("[*] No accounts yet")

    if args.scheduler:
        core._stop_event.clear()
        core._scheduler_thread = threading.Thread(target=core._scheduler_loop, daemon=True)
        core._scheduler_thread.start()
        core._update_state(running=True)
        print("[+] Scheduler auto-started")

    def _shutdown(sig, frame):
        print("\n[*] Shutting down...")
        core._stop_event.set()
        os._exit(0)

    _signal.signal(_signal.SIGINT, _shutdown)
    _signal.signal(_signal.SIGTERM, _shutdown)
    try:
        from waitress import serve
        print(f"\n  Production -> http://{args.host}:{args.port}\n")
        serve(app, host=args.host, port=args.port, threads=32)
    except ImportError:
        print(f"\n  Dev server -> http://{args.host}:{args.port}\n")
        app.run(host=args.host, port=args.port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
